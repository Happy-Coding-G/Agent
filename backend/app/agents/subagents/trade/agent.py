"""
TradeAgent - LangGraph-based Trading Agent with User-Level Configuration

基于LangGraph的交易协商Agent，支持用户级LLM配置和个性化协商策略。
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
from app.services.skills import (
    PricingSkill,
    DataLineageSkill,
    MarketAnalysisSkill,
    PrivacyComputationSkill,
    AuditSkill,
)
from app.services.user_agent_service import UserAgentService, UserAgentSettings

# LangGraph imports
from app.agents.subagents.trade.graph import create_trade_graph
from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


class TradeAgent(SpaceAwareService):
    """
    TradeAgent - LangGraph-based trading agent with user-level configuration.

    核心设计：
    1. 使用LangGraph编排交易流程
    2. 支持用户级LLM配置（每个用户可使用自己的API Key）
    3. 支持用户级协商策略（自动/手动、利润率、预算等）
    4. 协商状态持久化 (NegotiationSessions表)
    5. 集成5个Skills提供业务能力
    """

    PLATFORM_FEE_RATE = 0.05

    def __init__(self, db: AsyncSession, llm_client: Optional[Any] = None):
        super().__init__(db)
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.negotiation_service = TradeNegotiationService(db)
        self.user_agent_service = UserAgentService(db)
        self.skills = self._init_skills()
        # 创建LangGraph实例
        self.graph = create_trade_graph(db, self.skills)

    def _init_skills(self) -> Dict[str, Any]:
        """初始化Skills"""
        return {
            "pricing": PricingSkill(self._db),
            "lineage": DataLineageSkill(self._db),
            "market": MarketAnalysisSkill(self._db),
            "privacy": PrivacyComputationSkill(self._db),
            "audit": AuditSkill(self._db),
        }

    async def _get_user_config(self, user_id: int) -> UserAgentSettings:
        """
        获取用户Agent配置

        Args:
            user_id: 用户ID

        Returns:
            UserAgentSettings
        """
        return await self.user_agent_service.get_user_agent_settings(user_id)

    async def _get_user_llm(self, user_id: int, temperature: Optional[float] = None):
        """
        获取用户级LLM客户端

        Args:
            user_id: 用户ID
            temperature: 温度参数

        Returns:
            LLM客户端
        """
        return await self.user_agent_service.get_user_llm_client(
            user_id, temperature=temperature
        )

    # ========================================================================
    # High-Level API (Unified Interface via LangGraph)
    # ========================================================================

    async def run(
        self,
        action: str,
        space_public_id: str,
        user: Users,
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的LangGraph入口

        Args:
            action: 操作类型 ("listing", "purchase", "auction_bid", "bilateral")
            space_public_id: Space ID
            user: 当前用户
            **kwargs: 其他参数

        Returns:
            执行结果
        """
        try:
            # 构建初始状态
            initial_state: TradeState = {
                "action": action,
                "space_public_id": space_public_id,
                "user_id": user.id,
                "user_role": "seller" if action == "listing" else "buyer",
                "started_at": datetime.utcnow(),
                "success": True,
                "result": {},
            }

            # 添加额外参数
            initial_state.update(kwargs)

            # 执行Graph
            final_state = await self.graph.ainvoke(initial_state)

            return final_state.get("result", {
                "success": False,
                "error": "No result generated"
            })

        except Exception as e:
            logger.exception(f"TradeAgent run failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "agent_type": "trade",
            }

    # ========================================================================
    # Legacy API (保持向后兼容)
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
        创建资产上架 (使用LangGraph)
        """
        return await self.run(
            action="listing",
            space_public_id=space_public_id,
            user=user,
            asset_id=asset_id,
            pricing_strategy=pricing_strategy,
            reserve_price=reserve_price,
            license_scope=license_scope,
            mechanism_hint=mechanism_hint,
            category=category,
            tags=tags,
        )

    async def initiate_purchase(
        self,
        user: Users,
        listing_id: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
        budget_max: float = 0.0,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发起购买请求 (使用LangGraph)
        """
        return await self.run(
            action="purchase",
            space_public_id="",  # 购买时可能不需要space
            user=user,
            listing_id=listing_id,
            requirements=requirements,
            budget_max=budget_max,
            mechanism_hint=mechanism_hint,
        )

    async def place_auction_bid(
        self,
        lot_id: str,
        user: Users,
        amount: float,
    ) -> Dict[str, Any]:
        """
        拍卖出价 (使用LangGraph)
        """
        return await self.run(
            action="auction_bid",
            space_public_id="",
            user=user,
            listing_id=lot_id,
            bid_amount=amount,
        )

    async def create_bilateral_negotiation(
        self,
        listing_id: str,
        buyer: Users,
        initial_offer: float,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """
        创建双边协商 (使用LangGraph)
        """
        return await self.run(
            action="bilateral",
            space_public_id="",
            user=buyer,
            listing_id=listing_id,
            budget_max=initial_offer,
            mechanism_hint="bilateral",
        )

    # ========================================================================
    # User-Level Negotiation API (with personalized configuration)
    # ========================================================================

    async def negotiate_with_user_config(
        self,
        negotiation_id: str,
        user: Users,
        user_offer: Optional[float] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用用户级配置的协商接口

        根据用户的 Agent 配置决定：
        - 是否自动响应
        - 利润率/预算约束
        - 使用用户的 LLM API

        Args:
            negotiation_id: 协商会话ID
            user: 当前用户
            user_offer: 用户报价（买方）或反报价（卖方）
            message: 协商消息

        Returns:
            协商结果
        """
        try:
            # 获取用户配置
            config = await self._get_user_config(user.id)

            # 获取协商会话
            negotiation = await self.negotiation_service.get_negotiation(negotiation_id)
            if not negotiation:
                return {"success": False, "error": "Negotiation not found"}

            # 判断用户角色
            is_seller = negotiation.get("seller_user_id") == user.id
            is_buyer = negotiation.get("buyer_id") == user.id

            if not (is_seller or is_buyer):
                return {"success": False, "error": "Not authorized for this negotiation"}

            # 获取用户级 LLM
            llm = await self._get_user_llm(user.id, temperature=config.temperature)

            # 根据配置决定自动/手动模式
            if config.trade_auto_negotiate:
                # 自动协商模式 - 使用 LLM 生成响应
                return await self._auto_negotiate(
                    negotiation, user, config, is_seller, user_offer, message, llm
                )
            else:
                # 手动模式 - 只记录用户输入，等待人工确认
                return await self._manual_negotiate(
                    negotiation, user, user_offer, message
                )

        except Exception as e:
            logger.exception(f"Negotiation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _auto_negotiate(
        self,
        negotiation: Dict[str, Any],
        user: Users,
        config: UserAgentSettings,
        is_seller: bool,
        user_offer: Optional[float],
        message: Optional[str],
        llm: Any,
    ) -> Dict[str, Any]:
        """
        自动协商逻辑

        使用用户的 LLM 和配置生成协商响应
        """
        try:
            current_price = negotiation.get("current_price", 0)
            reserve_price = negotiation.get("reserve_price", 0)
            mechanism = negotiation.get("mechanism_type", "bilateral")

            if is_seller:
                # 卖方逻辑：确保不低于最小利润率
                min_acceptable = reserve_price * (1 + config.trade_min_profit_margin)

                # 构建卖方提示词
                prompt = f"""你是一位数据资产卖方Agent，正在与用户进行价格协商。

协商信息：
- 当前报价: {user_offer or '等待买方报价'}
- 你的底价: {reserve_price}
- 最低可接受价格（考虑{config.trade_min_profit_margin*100}%利润率）: {min_acceptable:.2f}
- 协商轮数限制: {config.trade_max_rounds}

用户消息: {message or '无'}

请决定：
1. accept - 接受报价（如果 >= {min_acceptable:.2f}）
2. reject - 拒绝报价（如果太低）
3. counter - 提供反报价

请用JSON格式回复：{{"action": "accept/reject/counter", "price": 反报价价格, "reason": "原因", "message": "给用户的消息"}}"""

            else:
                # 买方逻辑：确保不超过预算比例
                max_budget = negotiation.get("budget_max", float('inf'))
                effective_budget = max_budget * config.trade_max_budget_ratio

                prompt = f"""你是一位数据资产买方Agent，正在与卖方进行价格协商。

协商信息：
- 卖方报价: {current_price}
- 你的预算: {max_budget}
- 有效预算上限（考虑{config.trade_max_budget_ratio*100}%比例）: {effective_budget:.2f}
- 你的出价: {user_offer or '待决定'}
- 协商轮数限制: {config.trade_max_rounds}

请决定：
1. accept - 接受卖方报价（如果 <= {effective_budget:.2f}）
2. reject - 拒绝（如果太高）
3. counter - 提供反报价

请用JSON格式回复：{{"action": "accept/reject/counter", "price": 出价, "reason": "原因", "message": "给卖方的消息"}}"""

            # 添加自定义系统提示词（如果有）
            if config.system_prompt:
                prompt = f"{config.system_prompt}\n\n{prompt}"

            # 调用用户级 LLM
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # 解析响应
            import json
            try:
                decision = json.loads(content)
            except json.JSONDecodeError:
                # 如果解析失败，使用默认决策
                decision = {
                    "action": "counter",
                    "price": current_price * 0.9 if not is_seller else current_price * 1.1,
                    "reason": "解析失败，使用默认策略",
                    "message": "请重新考虑这个价格"
                }

            # 执行决策
            action = decision.get("action", "counter")
            price = decision.get("price", 0)

            if action == "accept":
                # 接受报价
                result = await self.negotiation_service.accept_offer(
                    negotiation["negotiation_id"],
                    user.id,
                    accepted_price=price if not is_seller else current_price
                )
            elif action == "reject":
                # 拒绝报价
                result = await self.negotiation_service.reject_offer(
                    negotiation["negotiation_id"],
                    user.id,
                    reason=decision.get("reason", "价格不符合预期")
                )
            else:
                # 反报价
                result = await self.negotiation_service.make_counter_offer(
                    negotiation["negotiation_id"],
                    user.id,
                    price=price,
                    message=decision.get("message", "")
                )

            return {
                "success": True,
                "action": action,
                "price": price,
                "reason": decision.get("reason"),
                "message": decision.get("message"),
                "llm_provider": config.provider,
                "is_auto": True,
            }

        except Exception as e:
            logger.error(f"Auto negotiate failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "is_auto": True,
            }

    async def _manual_negotiate(
        self,
        negotiation: Dict[str, Any],
        user: Users,
        user_offer: Optional[float],
        message: Optional[str],
    ) -> Dict[str, Any]:
        """
        手动协商模式

        只记录用户输入，等待人工确认
        """
        # 记录用户意向
        await self.negotiation_service.record_intent(
            negotiation["negotiation_id"],
            user.id,
            {
                "offer": user_offer,
                "message": message,
                "mode": "manual",
                "status": "pending_approval",
            }
        )

        return {
            "success": True,
            "action": "pending",
            "message": "您的报价已记录，等待人工确认",
            "offer": user_offer,
            "is_auto": False,
            "requires_approval": True,
        }

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _select_mechanism(self, pricing_strategy: str) -> str:
        """根据定价策略选择机制"""
        strategy_map = {
            "negotiable": "bilateral",
            "auction": "auction",
            "competitive": "contract_net",
        }
        return strategy_map.get(pricing_strategy, "bilateral")

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """清理标签"""
        return [t.strip()[:32] for t in tags if t.strip()][:10]
