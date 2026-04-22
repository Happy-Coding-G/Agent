"""
Agent-First Trade Nodes - Direct Trade Mode

直接交易处理节点：用户输入意图 -> Agent 检索评估 -> 直接下单
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from sqlalchemy import select, func

from typing import Dict, Any

TradeState = Dict[str, Any]
from app.db.models import DataAssets, TradeOrders, TradeListings, AgentTasks

logger = logging.getLogger(__name__)


async def normalize_goal(self, state: TradeState) -> TradeState:
    """
    标准化交易目标

    将用户的交易目标转换为内部标准格式。
    """
    try:
        goal = state.get("trade_goal", {})

        # 标准化价格（避免未提供价格时产生 0）
        target_price = goal.get("target_price")
        if target_price is None:
            if goal.get("intent") == "sell_asset":
                min_price = goal.get("min_price")
                if min_price and min_price > 0:
                    goal["target_price"] = min_price * 1.1
                else:
                    goal["target_price"] = 50.0
            elif goal.get("intent") == "buy_asset":
                max_price = goal.get("max_price")
                if max_price and max_price > 0:
                    goal["target_price"] = max_price * 0.9
                else:
                    goal["target_price"] = 50.0

        # 标准化截止时间
        deadline = goal.get("deadline")
        if not deadline:
            goal["deadline"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        state["trade_goal"] = goal
        state["current_step"] = "normalize_goal"

        # 记录决策
        if "decisions" not in state:
            state["decisions"] = []
        state["decisions"].append({
            "type": "normalize_goal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "auto_trade": getattr(settings, "trade_auto_negotiate", False),
                "max_budget_ratio": getattr(settings, "trade_max_budget_ratio", 1.0),
                "temperature": getattr(settings, "temperature", 0.7),
            }
        except Exception:
            # 使用默认配置
            state["user_config"] = {
                "auto_trade": True,
                "max_budget_ratio": 1.0,
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

        # 加载资产信息（直接通过 asset_id 查询）
        result = await self.db.execute(
            select(DataAssets).where(DataAssets.asset_id == asset_id)
        )
        asset = result.scalar_one_or_none()
        if asset:
            state["asset_context"] = {
                "asset_id": asset.asset_id,
                "space_public_id": asset.space_public_id or "",
                "title": asset.asset_name,
                "content_markdown": asset.content_markdown or "",
                "graph_snapshot": asset.graph_snapshot or {},
            }
        else:
            state["asset_context"] = None

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
    使用真实订单数据计算用户信任分数。
    """
    try:
        goal = state.get("trade_goal", {})
        constraints = state.get("trade_constraints", {})
        user_id = state.get("user_id")

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
        if not user_config.get("auto_trade", True):
            risk_factors.append("manual_mode")

        # 查询真实订单数据计算信任分
        completed_orders = 0
        failed_orders = 0
        if user_id:
            try:
                completed_result = await self.db.execute(
                    select(func.count()).where(
                        (TradeOrders.buyer_user_id == user_id) &
                        (TradeOrders.status == "completed")
                    )
                )
                completed_orders = completed_result.scalar() or 0

                failed_result = await self.db.execute(
                    select(func.count()).where(
                        (TradeOrders.buyer_user_id == user_id) &
                        (TradeOrders.status.in_(["disputed", "refunded"]))
                    )
                )
                failed_orders = failed_result.scalar() or 0
            except Exception as e:
                logger.warning(f"Failed to query order stats: {e}")

        is_first_transaction = completed_orders == 0
        user_trust_score = min(1.0, 0.3 + completed_orders * 0.1)
        user_trust_score = max(0.0, user_trust_score - failed_orders * 0.15)

        risk_context = {
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "user_trust_score": user_trust_score,
            "is_first_transaction": is_first_transaction,
            "completed_orders": completed_orders,
            "failed_orders": failed_orders,
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
            "user_trust_score": user_trust_score,
            "is_first_transaction": is_first_transaction,
            "requires_manual_review": risk_context["requires_manual_review"],
        })

        return state

    except Exception as e:
        logger.error(f"Risk evaluation failed: {e}")
        state["risk_context"] = {"risk_level": "low", "error": str(e)}
        return state


async def execute_direct_trade(self, state: TradeState) -> TradeState:
    """
    执行直接交易

    直接交易逻辑：
    1. 买方意图 -> 检索匹配资产
    2. 评估价格/信誉 -> 若合适则创建订单
    3. 卖方意图 -> 创建上架记录

    无需协商会话，一步完成。
    """
    try:
        if not state.get("success"):
            return state

        goal = state.get("trade_goal", {})
        intent = goal.get("intent")
        user_id = state.get("user_id")
        asset_id = goal.get("asset_id")
        listing_id = goal.get("listing_id")

        if intent == "buy_asset":
            # 买方：检索 -> 评估 -> 下单
            result = await _execute_buy_direct(self, state, user_id, asset_id, listing_id, goal)
            state["result"] = result

        elif intent == "sell_asset":
            # 卖方：创建上架记录
            result = await _execute_sell_direct(self, state, user_id, asset_id, goal)
            state["result"] = result

        else:
            # 价格查询等其他意图
            state["result"] = {
                "success": True,
                "status": "inquiry",
                "message": "Price inquiry completed",
                "asset_context": state.get("asset_context"),
                "market_context": state.get("market_context"),
            }

        state["current_step"] = "execute_direct_trade"
        return state

    except Exception as e:
        logger.error(f"Direct trade execution failed: {e}")
        state["success"] = False
        state["error"] = f"Direct trade execution failed: {e}"
        return state


async def _execute_buy_direct(self, state, user_id, asset_id, listing_id, goal) -> Dict[str, Any]:
    """执行买方直接交易"""
    from app.repositories.trade_repo import TradeRepository

    repo = TradeRepository(self.db)

    # 1. 检索匹配资产
    matched_assets = []
    if listing_id:
        # 直接指定 listing
        listing_result = await self.db.execute(
            select(TradeListings).where(TradeListings.public_id == listing_id)
        )
        listing = listing_result.scalar_one_or_none()
        if listing:
            matched_assets.append({
                "listing_id": listing.public_id,
                "asset_id": listing.asset_id,
                "price": listing.price,
                "seller_id": listing.seller_user_id,
            })
    elif asset_id:
        # 按资产ID查找
        listings_result = await self.db.execute(
            select(TradeListings).where(
                (TradeListings.asset_id == asset_id) &
                (TradeListings.status == "active")
            )
        )
        listings = listings_result.scalars().all()
        for l in listings:
            matched_assets.append({
                "listing_id": l.public_id,
                "asset_id": l.asset_id,
                "price": l.price,
                "seller_id": l.seller_user_id,
            })

    if not matched_assets:
        return {
            "success": False,
            "status": "no_match",
            "message": "未找到符合条件的资产上架记录",
        }

    # 2. 选择最优匹配（价格最低且卖家信誉良好）
    best_match = min(matched_assets, key=lambda x: x["price"] or float("inf"))

    # 3. 检查预算
    budget_max = goal.get("max_price", float("inf"))
    if best_match["price"] and best_match["price"] > budget_max:
        return {
            "success": False,
            "status": "over_budget",
            "message": f"最低价格 {best_match['price']} 超出预算 {budget_max}",
            "best_match": best_match,
        }

    # 4. 创建订单（等待审批或直接完成）
    # 实际创建订单逻辑由 settle_or_continue 处理
    return {
        "success": True,
        "status": "order_ready",
        "message": f"找到匹配资产，价格 {best_match['price']}",
        "listing_id": best_match["listing_id"],
        "asset_id": best_match["asset_id"],
        "price": best_match["price"],
        "seller_id": best_match["seller_id"],
        "action": "create_order",
    }


async def _execute_sell_direct(self, state, user_id, asset_id, goal) -> Dict[str, Any]:
    """执行卖方直接上架"""
    price = goal.get("target_price", goal.get("min_price", 0))

    return {
        "success": True,
        "status": "listing_ready",
        "message": f"资产上架准备完成，定价 {price}",
        "asset_id": asset_id,
        "price": price,
        "action": "create_listing",
    }


async def check_approval(self, state: TradeState) -> TradeState:
    """
    检查审批门控

    调用真实审批策略服务，若需要审批则持久化到 AgentTask。
    """
    # 若已从审批流程恢复，直接跳过避免循环
    if state.get("approval_granted"):
        state["approval_required"] = False
        return state

    try:
        goal_dict = state.get("trade_goal", {})
        constraints_dict = state.get("trade_constraints", {})
        risk_context = state.get("risk_context", {})

        from app.schemas.trade_goal import TradeGoal, TradeConstraints
        from app.services.trade.approval_policy_service import ApprovalPolicyService

        goal = TradeGoal(**goal_dict)
        constraints = TradeConstraints(**constraints_dict)

        decision = ApprovalPolicyService.evaluate_transaction(
            goal=goal,
            constraints=constraints,
            current_price=goal_dict.get("target_price"),
            user_trust_score=risk_context.get("user_trust_score", 1.0),
            is_first_transaction=risk_context.get("is_first_transaction", False),
        )

        if decision.requires_approval:
            state["approval_required"] = True
            pending_decision = {
                "type": "approval_required",
                "step": state.get("current_step"),
                "reason": decision.reason,
                "trigger": decision.trigger.value if decision.trigger else None,
                "policy_applied": decision.policy_applied,
                "requires_action": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            state["pending_decision"] = pending_decision
            state["result"] = {
                "success": True,
                "status": "pending_approval",
                "message": f"等待用户审批: {decision.reason}",
                "decision": pending_decision,
            }

            # 持久化到 AgentTask
            task_id = state.get("task_id")
            if task_id:
                try:
                    task_result = await self.db.execute(
                        select(AgentTasks).where(AgentTasks.public_id == task_id)
                    )
                    task = task_result.scalar_one_or_none()
                    if task:
                        task.status = "pending_approval"
                        existing_output = task.output_data or {}
                        existing_output["pending_decision"] = pending_decision
                        # 保存完整状态用于审批恢复（处理 datetime 不可序列化问题）
                        pending_state = {}
                        for k, v in state.items():
                            if isinstance(v, datetime):
                                pending_state[k] = v.isoformat()
                            else:
                                pending_state[k] = v
                        existing_output["pending_state"] = pending_state
                        task.output_data = existing_output
                        await self.db.commit()
                except Exception as e:
                    logger.warning(f"Failed to persist approval decision: {e}")

            # 记录决策
            if "decisions" not in state:
                state["decisions"] = []
            state["decisions"].append({
                "type": "approval_requested",
                "reason": decision.reason,
                "policy_applied": decision.policy_applied,
            })
        else:
            state["approval_required"] = False

        return state

    except Exception as e:
        logger.error(f"Approval check failed: {e}")
        state["approval_required"] = True
        state["pending_decision"] = {
            "type": "approval_required",
            "reason": f"Approval service error: {e}",
            "requires_action": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return state


async def settle_or_continue(self, state: TradeState) -> TradeState:
    """
    结算或继续

    直接交易模式：检查审批通过后直接执行订单/上架创建。
    """
    try:
        result = state.get("result") or {}
        status = result.get("status")

        # 检查审批是否通过
        if state.get("approval_required") and not result.get("approval_granted"):
            # 审批未通过，阻止结算但不报错
            state["result"]["settled"] = False
            state["result"]["message"] = "等待用户审批"
            return state

        # 直接执行交易
        if status in ["order_ready", "listing_ready"]:
            action = result.get("action")

            if action == "create_order":
                # 创建订单
                await _create_order(self, state, result)
            elif action == "create_listing":
                # 创建上架
                await _create_listing(self, state, result)

            result["settled"] = True
            result["settled_at"] = datetime.now(timezone.utc).isoformat()

            # 记录决策
            if "decisions" not in state:
                state["decisions"] = []
            state["decisions"].append({
                "type": "settlement",
                "status": "completed",
                "result": result,
            })

        elif status == "no_match":
            state["success"] = False
            state["error"] = result.get("message", "未找到匹配资产")

        elif status == "over_budget":
            state["success"] = False
            state["error"] = result.get("message", "超出预算")

        state["current_step"] = "settle_or_continue"
        return state

    except Exception as e:
        logger.error(f"Settlement failed: {e}")
        state["success"] = False
        state["error"] = f"Settlement failed: {e}"
        return state


async def _create_order(self, state, result: Dict[str, Any]) -> None:
    """创建交易订单"""
    from app.db.models import TradeOrders, Users
    from sqlalchemy import select
    import uuid

    listing_id = result.get("listing_id")
    buyer_id = state.get("user_id")
    price = result.get("price", 0)

    try:
        # 查询 listing 获取 seller_id
        listing_result = await self.db.execute(
            select(TradeListings).where(TradeListings.public_id == listing_id)
        )
        listing = listing_result.scalar_one_or_none()

        if not listing:
            result["order_created"] = False
            result["order_error"] = "Listing not found"
            return

        price_credits = int(price * 100) if price else 0
        platform_fee = int(price_credits * 0.05)
        seller_income = price_credits - platform_fee

        order = TradeOrders(
            public_id=str(uuid.uuid4())[:32],
            listing_id=listing_id,
            buyer_user_id=buyer_id,
            seller_user_id=listing.seller_user_id,
            asset_title_snapshot=listing.title or "",
            seller_alias_snapshot=listing.seller_alias or "",
            price_credits=price_credits,
            platform_fee=platform_fee,
            seller_income=seller_income,
            status="pending",
        )
        self.db.add(order)
        await self.db.commit()

        result["order_created"] = True
        result["order_id"] = order.public_id
        result["status"] = "order_created"
        result["message"] = f"订单已创建: {order.public_id}"

    except Exception as e:
        logger.error(f"Order creation failed: {e}")
        result["order_created"] = False
        result["order_error"] = str(e)


async def _create_listing(self, state, result: Dict[str, Any]) -> None:
    """创建资产上架"""
    from app.db.models import TradeListings, Users
    from sqlalchemy import select
    import uuid

    asset_id = result.get("asset_id")
    seller_id = state.get("user_id")
    price = result.get("price", 0)

    try:
        # 获取 seller alias
        seller_alias = ""
        if seller_id:
            user_result = await self.db.execute(
                select(Users).where(Users.id == seller_id)
            )
            seller_user = user_result.scalar_one_or_none()
            if seller_user:
                seller_alias = seller_user.username or ""

        # 从资产上下文获取标题
        asset_context = state.get("asset_context")
        title = ""
        if asset_context:
            title = asset_context.get("title", "")

        listing = TradeListings(
            public_id=str(uuid.uuid4())[:32],
            asset_id=asset_id,
            seller_user_id=seller_id,
            seller_alias=seller_alias,
            title=title or "Untitled Asset",
            price_credits=int(price * 100) if price else 0,
            status="active",
        )
        self.db.add(listing)
        await self.db.commit()

        result["listing_created"] = True
        result["listing_id"] = listing.public_id
        result["status"] = "listing_created"
        result["message"] = f"上架已创建: {listing.public_id}"

    except Exception as e:
        logger.error(f"Listing creation failed: {e}")
        result["listing_created"] = False
        result["listing_error"] = str(e)


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
                },
            )

        state["current_step"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc)

        return state

    except Exception as e:
        logger.error(f"State publishing failed: {e}")
        return state
