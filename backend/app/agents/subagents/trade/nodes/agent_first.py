"""
Agent-First Trade Nodes

Agent-First 架构的新交易处理节点。

这些节点实现了完整的交易目标执行链路：
normalize_goal -> load_user_config -> load_asset_context -> evaluate_market -> evaluate_risk
-> select_mechanism -> create_session -> run_negotiation -> check_approval -> settle_or_continue -> publish_state
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


async def normalize_goal(self, state: TradeState) -> TradeState:
    """
    标准化交易目标

    将用户的交易目标转换为内部标准格式。
    """
    try:
        goal = state.get("trade_goal", {})

        # 标准化价格
        target_price = goal.get("target_price")
        if target_price is None:
            if goal.get("intent") == "sell_asset":
                goal["target_price"] = goal.get("min_price", 0) * 1.1
            elif goal.get("intent") == "buy_asset":
                goal["target_price"] = goal.get("max_price", 0) * 0.9

        # 标准化截止时间
        deadline = goal.get("deadline")
        if not deadline:
            goal["deadline"] = (datetime.utcnow() + timedelta(days=7)).isoformat()

        state["trade_goal"] = goal
        state["current_step"] = "normalize_goal"

        # 记录决策
        if "decisions" not in state:
            state["decisions"] = []
        state["decisions"].append({
            "type": "normalize_goal",
            "timestamp": datetime.utcnow().isoformat(),
        })

        return state

    except Exception as e:
        logger.error(f"Goal normalization failed: {e}")
        state["success"] = False
        state["error"] = f"Goal normalization failed: {e}"
        return state


async def load_user_config(self, state: TradeState) -> TradeState:
    """
    加载用户配置

    获取用户的 Agent 配置、偏好设置等。
    """
    try:
        user_id = state.get("user_id")
        if not user_id:
            state["user_config"] = {}
            return state

        # 加载用户 Agent 配置
        from app.services.user_agent_service import UserAgentService

        user_agent_service = UserAgentService(self.db)
        try:
            settings = await user_agent_service.get_user_agent_settings(user_id)
            state["user_config"] = {
                "auto_negotiate": settings.trade_auto_negotiate,
                "min_profit_margin": settings.trade_min_profit_margin,
                "max_budget_ratio": settings.trade_max_budget_ratio,
                "max_rounds": settings.trade_max_rounds,
                "temperature": settings.temperature,
            }
        except Exception:
            # 使用默认配置
            state["user_config"] = {
                "auto_negotiate": False,
                "min_profit_margin": 0.1,
                "max_budget_ratio": 1.0,
                "max_rounds": 10,
                "temperature": 0.7,
            }

        state["current_step"] = "load_user_config"
        return state

    except Exception as e:
        logger.error(f"User config loading failed: {e}")
        state["user_config"] = {}
        return state


async def load_asset_context(self, state: TradeState) -> TradeState:
    """
    加载资产上下文

    获取资产的详细信息、历史交易记录、血缘关系等。
    """
    try:
        goal = state.get("trade_goal", {})
        asset_id = goal.get("asset_id")

        if not asset_id:
            state["asset_context"] = None
            return state

        # 加载资产信息
        asset_info = await self.assets.get_asset_by_id(asset_id)
        state["asset_context"] = asset_info

        # 加载资产血缘（如果 skill 可用）
        if "lineage" in self.skills:
            try:
                lineage = await self.skills["lineage"].analyze_asset_lineage(asset_id)
                state["lineage_context"] = lineage
            except Exception as e:
                logger.warning(f"Lineage analysis failed: {e}")
                state["lineage_context"] = None

        state["current_step"] = "load_asset_context"
        return state

    except Exception as e:
        logger.error(f"Asset context loading failed: {e}")
        state["asset_context"] = None
        return state


async def evaluate_market(self, state: TradeState) -> TradeState:
    """
    评估市场状态

    分析当前市场情况：价格趋势、流动性、竞争状况等。
    """
    try:
        goal = state.get("trade_goal", {})
        asset_id = goal.get("asset_id")

        market_context = {
            "current_avg_price": None,
            "price_volatility": 0.0,
            "market_liquidity": "medium",
            "recent_trades_count": 0,
            "active_listings_count": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # 如果有市场分析 skill，使用它
        if "market" in self.skills and asset_id:
            try:
                analysis = await self.skills["market"].analyze_market(
                    asset_id=asset_id,
                    intent=goal.get("intent"),
                )
                market_context.update({
                    "current_avg_price": analysis.get("avg_price"),
                    "price_volatility": analysis.get("volatility", 0.0),
                    "market_liquidity": analysis.get("liquidity", "medium"),
                    "recent_trades_count": analysis.get("recent_trades", 0),
                    "active_listings_count": analysis.get("active_listings", 0),
                })
            except Exception as e:
                logger.warning(f"Market analysis failed: {e}")

        state["market_context"] = market_context
        state["current_step"] = "evaluate_market"
        return state

    except Exception as e:
        logger.error(f"Market evaluation failed: {e}")
        state["market_context"] = {
            "market_liquidity": "medium",
            "error": str(e),
        }
        return state


async def evaluate_risk(self, state: TradeState) -> TradeState:
    """
    风险评估

    评估交易风险等级，决定是否需要额外审批。
    """
    try:
        goal = state.get("trade_goal", {})
        constraints = state.get("trade_constraints", {})

        # 计算风险因素
        risk_factors = []
        risk_level = "low"

        # 价格风险
        target_price = goal.get("target_price", 0)
        if target_price > 10000:
            risk_factors.append("high_value")
            risk_level = "medium"
        if target_price > 50000:
            risk_level = "high"

        # 时间风险
        urgency = goal.get("urgency", "medium")
        if urgency == "high":
            risk_factors.append("urgent")

        # 用户风险
        user_config = state.get("user_config", {})
        if not user_config.get("auto_negotiate", False):
            risk_factors.append("manual_mode")

        risk_context = {
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "user_trust_score": 1.0,  # 可从用户历史计算
            "requires_manual_review": risk_level == "high" or constraints.get("approval_policy") == "always",
        }

        state["risk_context"] = risk_context
        state["current_step"] = "evaluate_risk"

        # 记录决策
        if "decisions" not in state:
            state["decisions"] = []
        state["decisions"].append({
            "type": "risk_evaluation",
            "risk_level": risk_level,
            "requires_manual_review": risk_context["requires_manual_review"],
        })

        return state

    except Exception as e:
        logger.error(f"Risk evaluation failed: {e}")
        state["risk_context"] = {"risk_level": "low", "error": str(e)}
        return state


async def create_session(self, state: TradeState) -> TradeState:
    """
    创建或恢复协商会话

    根据选择的机制创建对应的协商会话。
    """
    try:
        if not state.get("success"):
            return state

        mechanism = state.get("selected_mechanism", "bilateral")
        engine_type = state.get("engine_type", "simple")
        goal = state.get("trade_goal", {})

        session_id = None

        if mechanism == "direct":
            # 直接交易，不需要会话
            state["session_id"] = None
            state["current_step"] = "direct_trade"
            return state

        elif engine_type == "simple" or mechanism == "bilateral":
            # 使用简化版引擎（双边协商）
            from app.services.trade.simple_negotiation_service import SimpleNegotiationService

            service = SimpleNegotiationService(self.db)
            result = await service.create_negotiation(
                buyer_id=state.get("user_id"),
                listing_id=goal.get("listing_id"),
                requirements={
                    "max_budget": goal.get("max_price"),
                    "preferred_price": goal.get("target_price"),
                    "message": "Auto-created by TradeAgent",
                },
            )
            session_id = result.get("negotiation_id")

        else:
            # 使用事件溯源引擎（拍卖）
            from app.services.trade.hybrid_negotiation_service import HybridNegotiationService

            service = HybridNegotiationService(self.db)
            result = await service.create_negotiation(
                mechanism_type="auction",
                seller_id=state.get("user_id"),
                buyer_id=None,
                listing_id=goal.get("listing_id"),
                config={
                    "starting_price": goal.get("min_price", 0),
                    "reserve_price": goal.get("min_price", 0),
                    "requires_audit": True,
                },
                expected_participants=state.get("mechanism_selection", {}).get("expected_participants", 2),
            )
            session_id = result.get("session_id")

        state["session_id"] = session_id
        state["current_step"] = "create_session"

        # 记录决策
        if "decisions" not in state:
            state["decisions"] = []
        state["decisions"].append({
            "type": "session_created",
            "session_id": session_id,
            "mechanism": mechanism,
            "engine": engine_type,
        })

        return state

    except Exception as e:
        logger.error(f"Session creation failed: {e}")
        state["success"] = False
        state["error"] = f"Session creation failed: {e}"
        return state


async def run_negotiation(self, state: TradeState) -> TradeState:
    """
    执行协商回合

    根据当前状态执行一轮协商。
    """
    try:
        session_id = state.get("session_id")
        if not session_id:
            # 直接交易模式
            state["result"] = {
                "status": "direct",
                "message": "Direct trade, no negotiation needed",
            }
            return state

        # 这里应该调用协商执行逻辑
        # 简化实现：返回等待对方响应状态
        state["result"] = {
            "status": "pending",
            "session_id": session_id,
            "message": "Negotiation initiated, waiting for counterparty",
        }
        state["current_step"] = "run_negotiation"

        return state

    except Exception as e:
        logger.error(f"Negotiation execution failed: {e}")
        state["result"] = {"status": "error", "error": str(e)}
        return state


async def check_approval(self, state: TradeState) -> TradeState:
    """
    检查审批门控

    检查是否需要人工审批，并记录审批请求。
    """
    try:
        if not state.get("approval_required"):
            return state

        # 创建审批请求
        pending_decision = {
            "type": "approval_required",
            "step": state.get("current_step"),
            "reason": state.get("mechanism_selection", {}).get("selection_reason", ""),
            "requires_action": True,
            "created_at": datetime.utcnow().isoformat(),
        }

        state["pending_decision"] = pending_decision
        state["result"] = {
            "status": "pending_approval",
            "message": "Waiting for user approval",
            "decision": pending_decision,
        }

        # 记录决策
        if "decisions" not in state:
            state["decisions"] = []
        state["decisions"].append({
            "type": "approval_requested",
            "reason": pending_decision["reason"],
        })

        return state

    except Exception as e:
        logger.error(f"Approval check failed: {e}")
        return state


async def settle_or_continue(self, state: TradeState) -> TradeState:
    """
    结算或继续

    根据当前状态决定是结算还是继续协商。
    """
    try:
        result = state.get("result", {})
        status = result.get("status")

        if status in ["accepted", "completed"]:
            # 执行结算
            result["settled"] = True
            result["settled_at"] = datetime.utcnow().isoformat()

            # 记录决策
            if "decisions" not in state:
                state["decisions"] = []
            state["decisions"].append({
                "type": "settlement",
                "status": "completed",
                "result": result,
            })

        elif status == "rejected":
            # 协商失败
            result["settled"] = False
            state["success"] = False
            state["error"] = "Negotiation rejected"

        # 其他状态：继续协商
        state["current_step"] = "settle_or_continue"
        return state

    except Exception as e:
        logger.error(f"Settlement failed: {e}")
        state["success"] = False
        state["error"] = f"Settlement failed: {e}"
        return state


async def publish_state(self, state: TradeState) -> TradeState:
    """
    发布状态

    将最终状态发布到外部系统（如更新 AgentTask、发送通知等）。
    """
    try:
        task_id = state.get("task_id")
        if task_id:
            # 更新 AgentTask
            from app.services.agent_task_service import AgentTaskService

            task_service = AgentTaskService(self.db)
            await task_service.update_task(
                task_id=task_id,
                status="completed" if state.get("success") else "failed",
                output_data={
                    "result": state.get("result"),
                    "decisions": state.get("decisions"),
                    "session_id": state.get("session_id"),
                },
            )

        state["current_step"] = "completed"
        state["completed_at"] = datetime.utcnow()

        return state

    except Exception as e:
        logger.error(f"State publishing failed: {e}")
        return state
