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

from app.services.trade import NegotiationService
from app.db.models import Users, NegotiationSessions
from app.core.errors import ServiceError
from app.services.base import SpaceAwareService
from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository
from app.utils.sanitizer import redact_sensitive_info, compact_text

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
        # 使用新的NegotiationService (支持跨用户持久化)
        self.negotiation_service = NegotiationService(db)

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

        # 自动计算底价
        if reserve_price is None or reserve_price <= 0:
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
        """
        messages = await self.negotiation_service.poll_messages(
            user_id=user.id,
            negotiation_id=negotiation_id,
            limit=limit,
        )

        return [
            {
                "message_id": msg.message_id,
                "negotiation_id": msg.negotiation_id,
                "from_user_id": msg.from_agent_user_id,
                "msg_type": msg.msg_type,
                "payload": msg.payload,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
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

        # 计算默认底价（如果没有指定）
        if floor_price <= 0:
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
