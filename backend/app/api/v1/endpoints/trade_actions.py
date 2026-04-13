"""
Trade Action API - 业务动作导向的交易接口

提供统一的交易业务动作入口，简化前端调用。
所有交易操作（协商、拍卖、购买）都通过 /execute 端点完成。
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.trade_action_service import (
    TradeActionService,
    TradeAction,
    TradeActionResult,
    execute_trade_action,
)
from app.core.errors import ServiceError

router = APIRouter(prefix="/trade", tags=["trade-actions"])


class TradeActionRequest(BaseModel):
    """交易动作请求"""
    action: str = Field(
        ...,
        description="业务动作类型",
        examples=["initiate_negotiation", "make_offer", "accept_offer", "place_bid"]
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="动作参数"
    )


class TradeActionResponse(BaseModel):
    """交易动作响应"""
    success: bool
    action: str
    message: str
    data: Dict[str, Any]
    transaction_id: Optional[str] = None
    next_actions: list = Field(default_factory=list)


class AvailableActionsResponse(BaseModel):
    """可用动作列表响应"""
    actions: list


@router.post("/execute", response_model=TradeActionResponse)
async def execute_trade_action_endpoint(
    request: TradeActionRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    执行交易业务动作

    统一的交易操作入口。一个动作自动处理所有相关操作。

    ## 可用动作

    ### 协商相关
    - **initiate_negotiation** - 发起协商
      ```json
      {"listing_id": "lst_abc123", "initial_offer": 800, "max_rounds": 10}
      ```

    - **make_offer** - 提交报价
      ```json
      {"negotiation_id": "neg_xyz789", "price": 850, "message": "这是我的最佳报价"}
      ```

    - **accept_offer** - 接受报价
      ```json
      {"negotiation_id": "neg_xyz789"}
      ```

    - **reject_offer** - 拒绝报价
      ```json
      {"negotiation_id": "neg_xyz789"}
      ```

    - **counter_offer** - 还价
      ```json
      {"negotiation_id": "neg_xyz789", "price": 900}
      ```

    - **withdraw_negotiation** - 撤回协商
      ```json
      {"negotiation_id": "neg_xyz789"}
      ```

    ### 拍卖相关
    - **place_bid** - 出价
      ```json
      {"lot_id": "lot_abc123", "amount": 1000}
      ```

    - **close_auction** - 关闭拍卖（卖方）
      ```json
      {"lot_id": "lot_abc123"}
      ```

    ### 购买相关
    - **direct_purchase** - 直接购买
      ```json
      {"listing_id": "lst_abc123"}
      ```

    ### 上架相关
    - **create_listing** - 创建上架
      ```json
      {"space_public_id": "spc_abc", "asset_id": "ast_xyz", "price": 1000}
      ```

    - **cancel_listing** - 取消上架
      ```json
      {"listing_id": "lst_abc123"}
      ```
    """
    try:
        result = await execute_trade_action(
            db,
            request.action,
            current_user,
            request.params,
        )

        return TradeActionResponse(
            success=result.success,
            action=result.action.value,
            message=result.message,
            data=result.data,
            transaction_id=result.transaction_id,
            next_actions=result.next_actions,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/actions", response_model=AvailableActionsResponse)
async def get_available_actions(
    current_user: Users = Depends(get_current_user),
):
    """
    获取所有可用的交易动作

    返回完整的动作列表及其描述。
    """
    actions = [
        {
            "action": action.value,
            "category": _get_category(action),
            "description": _get_description(action),
        }
        for action in TradeAction
    ]

    return AvailableActionsResponse(actions=actions)


@router.get("/actions/{action_name}", response_model=Dict[str, Any])
async def get_action_details(
    action_name: str,
    current_user: Users = Depends(get_current_user),
):
    """
    获取特定动作的详细信息和参数要求
    """
    try:
        action = TradeAction(action_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action_name}")

    return {
        "action": action.value,
        "category": _get_category(action),
        "description": _get_description(action),
        "required_params": _get_required_params(action),
        "optional_params": _get_optional_params(action),
        "example_request": _get_example(action),
    }


# ============================================================================
# 辅助函数
# ============================================================================

def _get_category(action: TradeAction) -> str:
    """获取动作分类"""
    categories = {
        TradeAction.INITIATE_NEGOTIATION: "negotiation",
        TradeAction.MAKE_OFFER: "negotiation",
        TradeAction.ACCEPT_OFFER: "negotiation",
        TradeAction.REJECT_OFFER: "negotiation",
        TradeAction.COUNTER_OFFER: "negotiation",
        TradeAction.WITHDRAW_NEGOTIATION: "negotiation",
        TradeAction.PLACE_BID: "auction",
        TradeAction.CLOSE_AUCTION: "auction",
        TradeAction.DIRECT_PURCHASE: "purchase",
        TradeAction.CONFIRM_PURCHASE: "purchase",
        TradeAction.CREATE_LISTING: "listing",
        TradeAction.UPDATE_LISTING: "listing",
        TradeAction.CANCEL_LISTING: "listing",
    }
    return categories.get(action, "unknown")


def _get_description(action: TradeAction) -> str:
    """获取动作描述"""
    descriptions = {
        TradeAction.INITIATE_NEGOTIATION: "发起与卖方的价格协商",
        TradeAction.MAKE_OFFER: "提交价格报价",
        TradeAction.ACCEPT_OFFER: "接受对方的报价，完成交易",
        TradeAction.REJECT_OFFER: "拒绝对方的报价",
        TradeAction.COUNTER_OFFER: "拒绝当前报价并提出新的报价",
        TradeAction.WITHDRAW_NEGOTIATION: "撤回协商并退还诚意金",
        TradeAction.PLACE_BID: "在拍卖中出价",
        TradeAction.CLOSE_AUCTION: "关闭拍卖（仅卖方）",
        TradeAction.DIRECT_PURCHASE: "直接购买固定价格商品",
        TradeAction.CREATE_LISTING: "创建新的商品上架",
        TradeAction.CANCEL_LISTING: "取消商品上架",
    }
    return descriptions.get(action, "Unknown action")


def _get_required_params(action: TradeAction) -> list:
    """获取必需参数"""
    params = {
        TradeAction.INITIATE_NEGOTIATION: ["listing_id"],
        TradeAction.MAKE_OFFER: ["negotiation_id", "price"],
        TradeAction.ACCEPT_OFFER: ["negotiation_id"],
        TradeAction.REJECT_OFFER: ["negotiation_id"],
        TradeAction.COUNTER_OFFER: ["negotiation_id", "price"],
        TradeAction.WITHDRAW_NEGOTIATION: ["negotiation_id"],
        TradeAction.PLACE_BID: ["lot_id", "amount"],
        TradeAction.CLOSE_AUCTION: ["lot_id"],
        TradeAction.DIRECT_PURCHASE: ["listing_id"],
        TradeAction.CREATE_LISTING: ["space_public_id", "asset_id", "price"],
        TradeAction.CANCEL_LISTING: ["listing_id"],
    }
    return params.get(action, [])


def _get_optional_params(action: TradeAction) -> list:
    """获取可选参数"""
    params = {
        TradeAction.INITIATE_NEGOTIATION: ["initial_offer", "max_rounds", "message"],
        TradeAction.MAKE_OFFER: ["message", "terms"],
        TradeAction.COUNTER_OFFER: ["message"],
        TradeAction.CREATE_LISTING: ["category", "tags"],
    }
    return params.get(action, [])


def _get_example(action: TradeAction) -> Dict[str, Any]:
    """获取示例请求"""
    examples = {
        TradeAction.INITIATE_NEGOTIATION: {
            "action": "initiate_negotiation",
            "params": {
                "listing_id": "lst_abc123",
                "initial_offer": 800,
                "max_rounds": 10,
                "message": "我对这个商品很感兴趣，希望能以800元成交"
            }
        },
        TradeAction.MAKE_OFFER: {
            "action": "make_offer",
            "params": {
                "negotiation_id": "neg_xyz789",
                "price": 850,
                "message": "我的最终报价"
            }
        },
        TradeAction.ACCEPT_OFFER: {
            "action": "accept_offer",
            "params": {
                "negotiation_id": "neg_xyz789"
            }
        },
        TradeAction.PLACE_BID: {
            "action": "place_bid",
            "params": {
                "lot_id": "lot_abc123",
                "amount": 1000
            }
        },
        TradeAction.DIRECT_PURCHASE: {
            "action": "direct_purchase",
            "params": {
                "listing_id": "lst_abc123"
            }
        },
    }
    return examples.get(action, {"action": action.value, "params": {}})
