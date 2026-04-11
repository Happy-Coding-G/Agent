"""
TradeAgent - Multi-Agent Distributed Negotiation Architecture (Cross-User)

基于持久化消息队列的跨用户Agent协商架构：
- 协商状态持久化到数据库 (NegotiationSessions)
- Agent间通过消息队列异步通信 (AgentMessageQueue)
- 支持买卖双方Agent独立运行
- 自动/半自动/人工三种执行模式
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.trade_negotiation_service import TradeNegotiationService
from app.db.models import Users, NegotiationSessions
from app.core.errors import ServiceError
from app.services.base import SpaceAwareService
from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository
from app.utils.sanitizer import redact_sensitive_info, compact_text
from app.agents.skills import (
    PricingSkill,
    DataLineageSkill,
    MarketAnalysisSkill,
    PrivacyComputationSkill,
    AuditSkill,
)

logger = logging.getLogger(__name__)


class TradeAgent(SpaceAwareService):
    """
    TradeAgent - 跨用户多Agent交易协商系统。

    核心设计：
    1. 协商状态持久化 (NegotiationSessions表)
    2. 消息队列实现异步通信 (AgentMessageQueue表)
    3. 每个用户独立运行自己的Agent实例
    4. 通过数据库共享协商状态和消息
    """

    PLATFORM_FEE_RATE = 0.05

    def __init__(self, db: AsyncSession, llm_client: Optional[Any] = None):
        super().__init__(db)
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        # 使用V2事件溯源服务
        self.negotiation_service = TradeNegotiationService(db)
        # 初始化Skills
        self.skills = self._init_skills()

    # ========================================================================
    # High-Level API (Cross-User Support)
    # ========================================================================

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        pricing_strategy: str = "negotiable",
        reserve_price: Optional[float] = None,
        license_scope: Optional[List[str]] = None,
        mechanism_hint: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        创建资产上架，启动跨用户多Agent协商流程。

        流程：
        1. 创建数据库listing记录
        2. 创建协商会话 (状态: pending)
        3. 等待卖方发布公告
        """
        # 验证空间访问
        await self._require_space(space_public_id, user)

        # 获取资产
        asset = await self.assets.get_asset(space_public_id, asset_id, user)

        # 创建脱敏摘要
        content = asset.get("content_markdown", "")
        summary = compact_text(redact_sensitive_info(asset.get("summary", "")), 240)
        preview = compact_text(redact_sensitive_info(content), 320)

        # 自动计算底价 - 使用PricingSkill
        if reserve_price is None or reserve_price <= 0:
            try:
                # 尝试使用动态定价引擎计算
                price_result = await self.skills["pricing"].calculate_quick_price(
                    asset_id=asset_id,
                    rights_types=["usage", "analysis"],
                    duration_days=365,
                )
                # 使用推荐价格的80%作为底价
                reserve_price = price_result["price_range"]["min"]
            except Exception as e:
                logger.warning(f"PricingSkill failed for {asset_id}, using fallback: {e}")
                # 回退到简单计算
                graph = asset.get("graph_snapshot", {})
                node_count = graph.get("node_count", 0)
                edge_count = graph.get("edge_count", 0)
                length_factor = min(len(content) / 180.0, 120.0)
                reserve_price = 20.0 + length_factor + node_count * 1.5 + edge_count * 1.2
                reserve_price = max(5.0, min(500.0, reserve_price))

        # 确定机制类型
        mechanism = mechanism_hint or self._select_mechanism(pricing_strategy)

        # 创建数据库listing记录
        listing = await self.repo.create_listing(
            seller_user_id=user.id,
            seller_alias=f"seller_{user.id}",
            title=asset.get("title", "Untitled")[:255],
            category=(category or "knowledge_report").strip()[:64],
            price_credits=int(reserve_price * 100),
            public_summary=summary,
            preview_excerpt=preview,
            delivery_payload={
                "content_markdown": redact_sensitive_info(content),
                "graph_snapshot": asset.get("graph_snapshot", {}),
            },
            asset_id=asset_id,
            space_public_id=space_public_id,
            tags=self._sanitize_tags(tags or []),
        )
        await self._db.commit()

        # 创建协商会话 (跨用户持久化)
        negotiation_id = await self.negotiation_service.create_negotiation(
            seller_user_id=user.id,
            buyer_id=None,  # 买方待定
            listing_id=listing.public_id,
            asset_id=asset_id,
            mechanism_type=mechanism,
            reserve_price=reserve_price,
            max_rounds=10,
        )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "listing_id": listing.public_id,
            "mechanism": mechanism,
            "seller_alias": f"seller_{user.id}",
            "status": "pending",
            "message": "Listing created. Use announce() to start negotiation.",
        }

    async def initiate_purchase(
        self,
        user: Users,
        listing_id: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
        budget_max: float = 0.0,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        买方发起购买请求，加入多 Agent 协商。
        """
        # 验证钱包
        wallet = await self.repo.get_or_create_wallet(user.id)
        if budget_max > 0 and wallet.liquid_credits < int(budget_max * 100):
            raise ServiceError(400, "Insufficient wallet balance for stated budget")

        # 如果有指定 listing，获取其协商会话
        if listing_id:
            listing = await self.repo.get_listing_by_public_id(listing_id)
            if not listing:
                raise ServiceError(404, "Listing not found")

            # 买方加入现有协商
            # 实际实现需要查询该 listing 对应的 negotiation_id
            # 这里简化处理
            return {
                "success": True,
                "listing_id": listing_id,
                "buyer_id": user.id,
                "status": "joining_negotiation",
            }

        # 没有指定 listing，创建新的购买需求
        negotiation_id = await self.negotiation_service.create_negotiation(
            seller_user_id=None,
            buyer_id=user.id,
            listing_id=None,
            asset_id="",
            mechanism_type=mechanism_hint or "contract_net",
            initial_state={
                "buyer_requirements": requirements,
                "budget_max": budget_max,
            },
        )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "buyer_alias": f"buyer_{user.id}",
            "status": "bidding",
        }

    async def create_auction(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        auction_type: str,
        starting_price: float,
        reserve_price: Optional[float] = None,
        duration_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        创建拍卖 - 启动跨用户Seller Agent发布公告。
        """
        # 创建listing和协商会话
        result = await self.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            pricing_strategy="auction",
            reserve_price=reserve_price or starting_price * 0.8,
            mechanism_hint="auction",
        )

        # 发布公告 (Seller Agent行动)
        await self.negotiation_service.seller_announce(
            negotiation_id=result["negotiation_id"],
            seller_user_id=user.id,
            announcement={
                "auction_type": auction_type,
                "starting_price": starting_price,
                "reserve_price": reserve_price,
                "duration_minutes": duration_minutes,
            },
        )

        return {
            **result,
            "auction_type": auction_type,
            "starting_price": starting_price,
            "status": "active",
        }

    async def place_auction_bid(
        self,
        lot_id: str,
        user: Users,
        amount: float,
    ) -> Dict[str, Any]:
        """
        拍卖出价 - Buyer Agent 发送BID消息到队列。
        """
        result = await self.negotiation_service.buyer_place_bid(
            negotiation_id=lot_id,
            buyer_user_id=user.id,
            amount=amount,
        )

        return {
            "success": True,
            "bid_placed": True,
            "amount": amount,
            "status": result.get("status"),
        }

    async def create_bilateral_negotiation(
        self,
        listing_id: str,
        buyer: Users,
        initial_offer: float,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """
        创建双边协商会话 (买方发起)。
        """
        listing = await self.repo.get_listing_by_public_id(listing_id)
        if not listing:
            raise ServiceError(404, "Listing not found")

        # 创建协商会话
        negotiation_id = await self.negotiation_service.create_negotiation(
            seller_user_id=listing.seller_user_id,
            buyer_id=buyer.id,
            listing_id=listing_id,
            asset_id=listing.asset_id,
            mechanism_type="bilateral",
            reserve_price=listing.price_credits / 100,
            max_rounds=max_rounds,
        )

        # 买方发送初始出价 (OFFER消息)
        await self.negotiation_service.buyer_make_offer(
            negotiation_id=negotiation_id,
            buyer_user_id=buyer.id,
            price=initial_offer,
            terms={},
            message="Initial offer",
        )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "session_id": negotiation_id,
            "seller_id": listing.seller_user_id,
            "buyer_id": buyer.id,
            "status": "active",
        }

    async def make_negotiation_offer(
        self,
        session_id: str,
        user: Users,
        price: float,
        terms: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        在双边协商中出价 (买方)。
        """
        result = await self.negotiation_service.buyer_make_offer(
            negotiation_id=session_id,
            buyer_user_id=user.id,
            price=price,
            terms=terms,
            message=message,
        )

        return {
            "success": True,
            "offer_sent": True,
            "status": result.get("status"),
        }

    async def respond_to_negotiation_offer(
        self,
        session_id: str,
        user: Users,
        response: str,
        counter_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        响应协商出价 (卖方): 接受/拒绝/反报价。
        """
        result = await self.negotiation_service.seller_respond_to_bid(
            negotiation_id=session_id,
            seller_user_id=user.id,
            response=response,
            counter_amount=counter_price,
        )

        return {
            "success": True,
            "response": response,
            "status": result.get("status"),
        }

    async def announce_contract_net_task(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        task_description: Dict[str, Any],
        eligibility_criteria: Optional[Dict[str, Any]] = None,
        deadline_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        发布合同网任务 (Seller Agent发布公告)。
        """
        result = await self.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            pricing_strategy="competitive",
            mechanism_hint="contract_net",
        )

        # 发布公告
        await self.negotiation_service.seller_announce(
            negotiation_id=result["negotiation_id"],
            seller_user_id=user.id,
            announcement={
                "task_description": task_description,
                "eligibility_criteria": eligibility_criteria,
                "deadline_minutes": deadline_minutes,
            },
        )

        return {
            **result,
            "announcement_id": result["negotiation_id"],
            "phase": "bidding",
        }

    async def submit_contract_net_bid(
        self,
        announcement_id: str,
        user: Users,
        bid_amount: float,
        qualifications: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        提交合同网投标 (Buyer Agent)。
        """
        result = await self.negotiation_service.buyer_place_bid(
            negotiation_id=announcement_id,
            buyer_user_id=user.id,
            amount=bid_amount,
            qualifications=qualifications,
        )

        return {
            "success": True,
            "bid_submitted": True,
            "status": result.get("status"),
        }

    # ========================================================================
    # Status & Query APIs
    # ========================================================================

    async def get_negotiation_status(
        self,
        negotiation_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """获取协商状态。"""
        session = await self.negotiation_service.get_negotiation(negotiation_id)

        if not session:
            raise ServiceError(404, "Negotiation not found")

        # 验证用户参与权
        if user.id not in [session.seller_user_id, session.buyer_user_id]:
            # 公开协商返回有限信息
            return {
                "negotiation_id": negotiation_id,
                "status": session.status,
                "mechanism": session.mechanism_type,
                "current_price": session.current_price / 100 if session.current_price else None,
            }

        return {
            "negotiation_id": negotiation_id,
            "status": session.status,
            "mechanism": session.mechanism_type,
            "current_round": session.current_round,
            "current_turn": session.current_turn,
            "current_price": session.current_price / 100 if session.current_price else None,
            "agreed_price": session.agreed_price / 100 if session.agreed_price else None,
            "seller_id": session.seller_user_id,
            "buyer_id": session.buyer_user_id,
            "shared_board": session.shared_board,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        }

    async def poll_messages(
        self,
        user: Users,
        negotiation_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        轮询当前用户的消息 (Agent Worker使用)。
        使用V2事件溯源替代消息队列。
        """
        events = await self.negotiation_service.poll_events(
            user_id=user.id,
            negotiation_id=negotiation_id,
            limit=limit,
        )

        # 将BlackboardEvents映射为消息格式
        return [
            {
                "message_id": event.event_id,
                "negotiation_id": event.session_id,
                "from_user_id": event.agent_id,
                "msg_type": event.event_type,
                "payload": event.payload,
                "created_at": event.event_timestamp.isoformat(),
                "sequence_number": event.sequence_number,
                "agent_role": event.agent_role,
            }
            for event in events
        ]

    async def list_active_auctions(self) -> List[Dict[str, Any]]:
        """列出活跃拍卖。"""
        sessions = await self.negotiation_service.list_user_negotiations(
            user_id=0,  # 系统查询
            status="active",
            limit=50,
        )

        return [
            {
                "negotiation_id": s.negotiation_id,
                "mechanism": s.mechanism_type,
                "current_price": s.current_price / 100 if s.current_price else None,
                "seller_id": s.seller_user_id,
                "round": s.current_round,
            }
            for s in sessions
            if s.mechanism_type == "auction"
        ]

    async def get_auction_status(self, lot_id: str) -> Dict[str, Any]:
        """获取拍卖状态。"""
        session = await self.negotiation_service.get_negotiation(lot_id)
        if not session:
            return {"error": "Auction not found"}

        return {
            "lot_id": lot_id,
            "status": session.status,
            "current_price": session.current_price / 100 if session.current_price else None,
            "current_winner": session.winner_user_id,
            "total_bids": len([e for e in session.shared_board.get("event_log", [])
                             if e.get("event") == "BID"]),
            "round": session.current_round,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        }

    # ========================================================================
    # Agent Configuration
    # ========================================================================

    async def get_agent_config(
        self,
        user: Users,
        role: str,  # "seller" or "buyer"
    ) -> Dict[str, Any]:
        """获取用户Agent配置。"""
        config = await self.negotiation_service.get_or_create_agent_config(
            user_id=user.id,
            agent_role=role,
        )
        return {
            "user_id": user.id,
            "role": role,
            "pricing_strategy": config.pricing_strategy,
            "auto_accept_threshold": config.auto_accept_threshold,
            "max_auto_rounds": config.max_auto_rounds,
            "use_llm_decision": config.use_llm_decision,
            "webhook_url": config.webhook_url,
        }

    async def update_agent_config(
        self,
        user: Users,
        role: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """更新Agent配置。"""
        config = await self.negotiation_service.update_agent_config(
            user_id=user.id,
            agent_role=role,
            **kwargs,
        )
        return {
            "success": True,
            "user_id": user.id,
            "role": role,
            "updated_fields": list(kwargs.keys()),
        }

    # ========================================================================
    # Skills Initialization
    # ========================================================================

    def _init_skills(self) -> Dict[str, Any]:
        """初始化Agent Skills"""
        return {
            "pricing": PricingSkill(self._db),
            "lineage": DataLineageSkill(self._db),
            "market": MarketAnalysisSkill(self._db),
            "privacy": PrivacyComputationSkill(self._db),
            "audit": AuditSkill(self._db),
        }

    # ========================================================================
    # Helpers
    # ========================================================================

    def _select_mechanism(self, pricing_strategy: str) -> str:
        """选择市场机制。"""
        strategy_map = {
            "fixed": "fixed_price",
            "negotiable": "bilateral",
            "auction": "auction",
            "competitive": "contract_net",
        }
        return strategy_map.get(pricing_strategy, "bilateral")

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """清理标签。"""
        result: List[str] = []
        for tag in tags:
            candidate = (tag or "").strip().lower()
            if candidate and candidate not in result:
                result.append(candidate[:32])
        return result[:8]

    # ========================================================================
    # Blackboard Mode API - 黑板模式协商
    # ========================================================================

    async def create_blackboard_negotiation(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        floor_price: float,
        target_price: Optional[float] = None,
        buyer_id: Optional[int] = None,
        starting_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        创建黑板模式协商会话。

        黑板模式特点：
        1. 卖方设置最低接受价格（floor_price）
        2. 买方设置最高接受价格（ceiling_price）
        3. 双方都能看到完整的协商历史
        4. 系统自动验证底线约束

        Args:
            floor_price: 卖方最低接受价格
            target_price: 卖方期望价格（用于决策参考）
            buyer_id: 买方用户ID（可选）
            starting_price: 起始报价
        """
        await self._require_space(space_public_id, user)

        # 获取资产信息
        asset = await self.assets.get_asset(space_public_id, asset_id, user)

        # 计算默认底价（如果没有指定）- 使用PricingSkill
        if floor_price <= 0:
            try:
                price_result = await self.skills["pricing"].calculate_quick_price(
                    asset_id=asset_id,
                    rights_types=["usage", "analysis"],
                )
                # 使用推荐价格的80%作为底价
                floor_price = price_result["price_range"]["min"]
            except Exception as e:
                logger.warning(f"PricingSkill failed for blackboard floor price, using fallback: {e}")
                content = asset.get("content_markdown", "")
                graph = asset.get("graph_snapshot", {})
                length_factor = min(len(content) / 180.0, 120.0)
                floor_price = 20.0 + length_factor + graph.get("node_count", 0) * 1.5
                floor_price = max(5.0, min(500.0, floor_price))

        # 创建黑板模式协商
        negotiation_id = await self.negotiation_service.create_blackboard_negotiation(
            seller_user_id=user.id,
            buyer_user_id=buyer_id,
            listing_id=asset_id,
            asset_id=asset_id,
            seller_floor_price=floor_price,
            seller_target_price=target_price or floor_price * 1.2,
            starting_price=starting_price,
        )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "floor_price": floor_price,
            "target_price": target_price or floor_price * 1.2,
            "status": "pending",
            "mechanism": "blackboard",
            "message": "Blackboard negotiation created. Waiting for buyer to set ceiling.",
        }

    async def join_blackboard_negotiation(
        self,
        negotiation_id: str,
        buyer: Users,
        ceiling_price: float,
        target_price: Optional[float] = None,
        initial_offer: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        买方加入黑板模式协商。

        Args:
            ceiling_price: 买方最高接受价格（必须）
            target_price: 买方期望价格
            initial_offer: 初始出价
        """
        # 设置买方天花板价格
        result = await self.negotiation_service.set_buyer_ceiling(
            negotiation_id=negotiation_id,
            buyer_user_id=buyer.id,
            ceiling_price=ceiling_price,
            target_price=target_price,
        )

        # 如果有初始出价，立即提交
        if initial_offer:
            offer_result = await self.negotiation_service.submit_offer(
                negotiation_id=negotiation_id,
                from_user_id=buyer.id,
                price=initial_offer,
                message="Initial offer",
                reasoning="First offer in blackboard negotiation",
            )
            result["initial_offer"] = offer_result

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "buyer_id": buyer.id,
            "ceiling_price": ceiling_price,
            "target_price": target_price,
            "deal_possible": result.get("deal_possible", True),
            "status": "active",
        }

    async def get_blackboard_context(
        self,
        negotiation_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """
        获取完整的黑板上下文 - 用于 Agent 决策。

        返回给 Agent 的完整上下文包含：
        - 当前协商状态
        - 双方底线价格
        - 完整协商历史
        - 价格演变趋势
        - 系统分析和建议
        """
        context = await self.negotiation_service.get_full_blackboard_context(
            negotiation_id=negotiation_id,
            for_user_id=user.id,
        )

        # 补充资产信息
        session = await self.negotiation_service.get_negotiation(negotiation_id)
        if session and session.asset_id:
            try:
                # 获取资产摘要（脱敏）
                context["asset_summary"] = {
                    "asset_id": session.asset_id,
                    "listing_id": session.listing_id,
                }
            except Exception:
                pass

        return context

    async def submit_blackboard_offer(
        self,
        negotiation_id: str,
        user: Users,
        price: float,
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """
        在黑板模式中提交出价。

        系统会自动验证：
        - 卖方出价 >= floor_price
        - 买方出价 <= ceiling_price
        """
        result = await self.negotiation_service.submit_offer(
            negotiation_id=negotiation_id,
            from_user_id=user.id,
            price=price,
            message="",
            reasoning=reasoning,
        )

        return {
            "success": True,
            "offer_price": price,
            "round": result["round"],
            "status": result["status"],
            "agreed": result.get("agreed", False),
        }

    async def accept_blackboard_offer(
        self,
        negotiation_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """接受当前出价，达成协议。"""
        result = await self.negotiation_service.accept_offer(
            negotiation_id=negotiation_id,
            user_id=user.id,
        )

        return {
            "success": True,
            "agreed_price": result["agreed_price"],
            "status": result["status"],
            "message": f"Agreement reached at {result['agreed_price']}",
        }

    async def counter_blackboard_offer(
        self,
        negotiation_id: str,
        user: Users,
        counter_price: float,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        拒绝当前并反报价。

        在黑板模式中，双方都可以主动反报价。
        """
        result = await self.negotiation_service.reject_and_counter(
            negotiation_id=negotiation_id,
            user_id=user.id,
            counter_price=counter_price,
            message="Counter offer",
            reason=reason,
        )

        return {
            "success": True,
            "counter_price": result["counter_price"],
            "round": result["round"],
            "status": result["status"],
        }

    async def settle_blackboard(
        self,
        negotiation_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """完成黑板协商结算。"""
        result = await self.negotiation_service.finalize_settlement(
            negotiation_id=negotiation_id,
            seller_id=user.id,
        )

        return {
            "success": True,
            "settlement": result["settlement"],
            "message": f"Transaction completed. Final price: {result['settlement']['final_price']}",
        }

    async def list_blackboard_negotiations(
        self,
        user: Users,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出用户参与的黑板协商。"""
        negotiations = await self.negotiation_service.list_negotiations(
            user_id=user.id,
            status=status_filter,
        )

        return [
            {
                **n,
                "mechanism": "blackboard",
            }
            for n in negotiations
        ]

    # ========================================================================
    # Pricing Skill APIs
    # ========================================================================

    async def get_pricing_suggestion(
        self,
        asset_id: str,
        user: Users,
        rights_types: Optional[List[str]] = None,
        duration_days: int = 365,
    ) -> Dict[str, Any]:
        """
        获取资产定价建议。

        使用PricingSkill计算公允价格和市场分析。
        """
        try:
            price_result = await self.skills["pricing"].calculate_quick_price(
                asset_id=asset_id,
                rights_types=rights_types or ["usage", "analysis"],
                duration_days=duration_days,
            )

            # 获取市场分析
            market_analysis = await self.skills["pricing"].analyze_market(
                asset_id=asset_id
            )

            return {
                "success": True,
                "asset_id": asset_id,
                "pricing": price_result,
                "market": {
                    "demand_score": market_analysis.demand_score,
                    "competition_level": market_analysis.competition_level,
                    "similar_assets": market_analysis.similar_assets_count,
                },
            }
        except Exception as e:
            logger.error(f"Failed to get pricing suggestion for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def get_negotiation_advice(
        self,
        asset_id: str,
        current_offer: float,
        is_seller: bool,
        user: Users,
        negotiation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        获取协商策略建议。

        Args:
            asset_id: 资产ID
            current_offer: 当前报价
            is_seller: 是否为卖方
            negotiation_context: 协商上下文
        """
        try:
            advice = await self.skills["pricing"].advise_negotiation(
                asset_id=asset_id,
                current_offer=current_offer,
                is_seller=is_seller,
                negotiation_context=negotiation_context,
            )

            return {
                "success": True,
                "asset_id": asset_id,
                "advice": {
                    "action": advice.action,
                    "suggested_price": advice.suggested_price,
                    "confidence": advice.confidence,
                    "reasoning": advice.reasoning,
                    "fallback_options": advice.fallback_options,
                },
            }
        except Exception as e:
            logger.error(f"Failed to get negotiation advice for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def get_comparable_assets(
        self,
        asset_id: str,
        user: Users,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        获取可比资产及其价格。
        """
        try:
            comparables = await self.skills["pricing"].get_comparable_prices(
                asset_id=asset_id,
                limit=limit,
            )

            return {
                "success": True,
                "asset_id": asset_id,
                "comparables": comparables,
            }
        except Exception as e:
            logger.error(f"Failed to get comparable assets for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    # ========================================================================
    # Data Lineage Skill APIs
    # ========================================================================

    async def get_asset_lineage(self, asset_id: str, user: Users) -> Dict[str, Any]:
        """
        获取资产数据血缘。

        使用DataLineageSkill查询血缘关系和质量。
        """
        try:
            # 血缘摘要
            summary = await self.skills["lineage"].get_lineage_summary(asset_id)

            # 血缘图
            graph = await self.skills["lineage"].get_lineage_graph(asset_id)

            # 质量评估
            quality = await self.skills["lineage"].assess_quality(asset_id)

            # 影响分析
            impact = await self.skills["lineage"].analyze_impact(asset_id)

            return {
                "success": True,
                "asset_id": asset_id,
                "lineage": {
                    "node_count": summary.node_count,
                    "data_source": summary.data_source,
                    "processing_steps": summary.processing_steps,
                    "integrity_verified": summary.integrity_verified,
                    "root_hash": summary.root_hash,
                },
                "graph": graph,
                "quality": {
                    "overall_score": quality.overall_score,
                    "grade": self._score_to_grade(quality.overall_score),
                    "dimensions": {
                        "completeness": quality.completeness,
                        "accuracy": quality.accuracy,
                        "timeliness": quality.timeliness,
                        "consistency": quality.consistency,
                        "uniqueness": quality.uniqueness,
                    },
                    "recommendations": quality.recommendations,
                },
                "impact": {
                    "upstream_count": impact.upstream_count,
                    "downstream_count": impact.downstream_count,
                    "risk_level": impact.risk_level,
                    "affected_assets": impact.affected_assets[:5],  # 限制数量
                },
            }
        except Exception as e:
            logger.error(f"Failed to get lineage for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    def _score_to_grade(self, score: float) -> str:
        """分数转等级"""
        if score >= 0.9:
            return "A+"
        elif score >= 0.8:
            return "A"
        elif score >= 0.7:
            return "B"
        elif score >= 0.6:
            return "C"
        else:
            return "D"

    async def verify_asset_integrity(self, asset_id: str, user: Users) -> Dict[str, Any]:
        """
        验证资产血缘完整性。
        """
        try:
            result = await self.skills["lineage"].verify_integrity(asset_id)
            return {
                "success": True,
                **result,
            }
        except Exception as e:
            logger.error(f"Failed to verify integrity for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    # ========================================================================
    # Market Analysis Skill APIs
    # ========================================================================

    async def get_market_intelligence(
        self,
        user: Users,
        data_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取市场情报。

        使用MarketAnalysisSkill分析市场趋势和竞争状况。
        """
        try:
            # 市场概览
            overview = await self.skills["market"].get_market_overview()

            # 市场趋势
            trend = await self.skills["market"].get_market_trend(data_type)

            return {
                "success": True,
                "overview": overview,
                "trend": {
                    "data_type": trend.data_type,
                    "transaction_count": trend.transaction_count,
                    "avg_price": trend.avg_price,
                    "trend": trend.trend,
                    "top_assets": trend.top_assets,
                },
            }
        except Exception as e:
            logger.error(f"Failed to get market intelligence: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def analyze_asset_competition(
        self,
        asset_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """
        分析资产竞争状况。
        """
        try:
            # 竞争分析
            competition = await self.skills["market"].analyze_competition(asset_id)

            # 网络价值
            network = await self.skills["market"].get_network_value(asset_id)

            # 定价策略建议
            pricing_strategy = await self.skills["market"].recommend_pricing_strategy(
                asset_id
            )

            return {
                "success": True,
                "asset_id": asset_id,
                "competition": {
                    "competitor_count": competition.competitor_count,
                    "market_position": competition.market_position,
                    "price_percentile": competition.price_percentile,
                    "quality_percentile": competition.quality_percentile,
                    "differentiation_score": competition.differentiation_score,
                },
                "network_value": network,
                "pricing_strategy": pricing_strategy,
            }
        except Exception as e:
            logger.error(f"Failed to analyze competition for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def get_buyer_intelligence(
        self,
        buyer_id: int,
        user: Users,
    ) -> Dict[str, Any]:
        """
        获取买方情报（画像和推荐）。
        """
        try:
            # 买方画像
            persona = await self.skills["market"].get_buyer_persona(buyer_id)

            # 资产推荐
            recommendations = await self.skills["market"].recommend_assets(buyer_id)

            # 相似买方
            similar_buyers = await self.skills["market"].find_similar_buyers(buyer_id)

            return {
                "success": True,
                "buyer_id": buyer_id,
                "persona": {
                    "segment": persona.segment,
                    "buying_power": persona.buying_power,
                    "price_sensitivity": persona.price_sensitivity,
                    "reputation_score": persona.reputation_score,
                    "transaction_history": persona.transaction_history,
                },
                "recommendations": [
                    {
                        "asset_id": r.asset_id,
                        "asset_name": r.asset_name,
                        "relevance_score": r.relevance_score,
                        "reason": r.reason,
                    }
                    for r in recommendations[:5]
                ],
                "similar_buyers": similar_buyers[:3],
            }
        except Exception as e:
            logger.error(f"Failed to get buyer intelligence for {buyer_id}: {e}")
            return {
                "success": False,
                "buyer_id": buyer_id,
                "error": str(e),
            }

    # ========================================================================
    # Privacy Skill APIs
    # ========================================================================

    async def negotiate_privacy_protocol(
        self,
        asset_id: str,
        sensitivity: str,
        user: Users,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        协商隐私计算协议。

        使用PrivacyComputationSkill协商最佳隐私计算方法。
        """
        try:
            result = await self.skills["privacy"].negotiate_protocol(
                asset_id=asset_id,
                sensitivity=sensitivity,
                requirements=requirements,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to negotiate privacy protocol for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def recommend_privacy_protocols(
        self,
        asset_id: str,
        sensitivity: str,
        user: Users,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """
        推荐多种隐私计算协议。
        """
        try:
            result = await self.skills["privacy"].recommend_protocols(
                asset_id=asset_id,
                sensitivity=sensitivity,
                top_k=top_k,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to recommend privacy protocols for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def assess_data_sensitivity(
        self,
        asset_id: str,
        user: Users,
        data_sample: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        评估数据敏感度。
        """
        try:
            result = await self.skills["privacy"].assess_sensitivity(
                asset_id=asset_id,
                data_sample=data_sample,
                metadata=metadata,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to assess sensitivity for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    async def check_privacy_compliance(
        self,
        data: List[Dict[str, Any]],
        user: Users,
        compliance_standard: str = "GDPR",
    ) -> Dict[str, Any]:
        """
        检查隐私合规性。

        Args:
            data: 数据样本
            compliance_standard: 合规标准 (GDPR, CCPA, HIPAA)
        """
        try:
            result = await self.skills["privacy"].check_compliance(
                data=data,
                compliance_standard=compliance_standard,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to check privacy compliance: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # ========================================================================
    # Audit Skill APIs
    # ========================================================================

    async def get_transaction_audit_report(
        self,
        transaction_id: str,
        user: Users,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取交易审计报告。

        使用AuditSkill生成完整审计报告。
        """
        try:
            report = await self.skills["audit"].generate_audit_report(
                transaction_id=transaction_id,
                days=days,
            )
            return report
        except Exception as e:
            logger.error(f"Failed to get audit report for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def assess_transaction_risk(
        self,
        transaction_id: str,
        user: Users,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        评估交易风险。
        """
        try:
            result = await self.skills["audit"].assess_risk(
                transaction_id=transaction_id,
                days=days,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to assess risk for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def check_transaction_compliance(
        self,
        transaction_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """
        检查交易合规状态。
        """
        try:
            result = await self.skills["audit"].check_compliance(
                transaction_id=transaction_id,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to check compliance for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def get_transaction_violations(
        self,
        transaction_id: str,
        user: Users,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取交易违规详情。
        """
        try:
            result = await self.skills["audit"].get_violation_details(
                transaction_id=transaction_id,
                days=days,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to get violations for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def get_transaction_metrics(
        self,
        transaction_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """
        获取交易实时指标。
        """
        try:
            result = await self.skills["audit"].get_real_time_metrics(
                transaction_id=transaction_id,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to get metrics for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    # ========================================================================
    # Legacy API (Backward Compatibility)
    # ========================================================================

    async def run_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        price_credits: Optional[float] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """遗留 API 兼容。"""
        return await self.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            pricing_strategy="fixed" if price_credits else "negotiable",
            reserve_price=price_credits,
            category=category,
            tags=tags,
        )

    async def run_purchase(
        self,
        listing_id: str,
        buyer: Users,
    ) -> Dict[str, Any]:
        """遗留 API 兼容。"""
        return await self.initiate_purchase(
            user=buyer,
            listing_id=listing_id,
            budget_max=0,  # 将从 listing 获取
        )

    async def close_auction(self, lot_id: str, user: Users) -> Dict[str, Any]:
        """关闭拍卖。"""
        session = await self.negotiation_service.get_negotiation(lot_id)
        if not session:
            raise ServiceError(404, "Auction not found")

        if session.seller_user_id != user.id:
            raise ServiceError(403, "Only seller can close auction")

        # 结算给当前最高出价者
        if session.winner_user_id and session.current_price:
            await self.negotiation_service.finalize_settlement(
                negotiation_id=lot_id,
                final_price=session.current_price / 100,
                buyer_id=session.winner_user_id,
                seller_id=user.id,
            )

        return {
            "success": True,
            "status": "closed",
            "winner": session.winner_user_id,
        }
