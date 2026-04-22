"""Asset tools backed by AssetService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class AssetManageInput(BaseModel):
    action: str = Field(description="操作类型: list, get, generate")
    space_id: str = Field(description="空间public_id")
    asset_id: Optional[str] = Field(None, description="资产ID（get时使用）")
    prompt: Optional[str] = Field(None, description="生成提示（generate时使用）")
    source_asset_ids: Optional[List[str]] = Field(
        None, description="来源资产ID列表（generate时使用）"
    )
    publish_to_trade: Optional[bool] = Field(
        None, description="[DEPRECATED] 生成与上架已分离，此字段不再生效", deprecated=True
    )


class OrganizeAssetsInput(BaseModel):
    asset_ids: List[str] = Field(description="资产ID列表")
    space_id: str = Field(description="空间public_id")


class GetAssetLineageInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    max_depth: int = Field(default=3, ge=1, le=5, description="血缘追溯最大深度")


class GetAssetPriceInput(BaseModel):
    asset_id: str = Field(description="资产ID")


class SimulateAssetPriceInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    rights_types: Optional[List[str]] = Field(
        default=None,
        description="权益类型覆盖，如 ['view', 'download', 'derivative_right']",
    )


class VerifyAssetLineageInput(BaseModel):
    asset_id: str = Field(description="资产ID")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def asset_manage(
        action: str,
        space_id: str,
        asset_id: Optional[str] = None,
        prompt: Optional[str] = None,
        source_asset_ids: Optional[List[str]] = None,
        publish_to_trade: Optional[bool] = None,
    ) -> Dict[str, Any]:
        from app.services.asset_service import AssetService
        from app.core.errors import ServiceError

        service = AssetService(db)

        try:
            if action == "list":
                assets = await service.list_assets(space_id, user)
                return {"success": True, "assets": assets}
            elif action == "get":
                if not asset_id:
                    return {"success": False, "error": "asset_id is required"}
                asset = await service.get_asset(space_id, asset_id, user)
                return {"success": True, "asset": asset}
            elif action == "generate":
                record = await service.generate_asset(
                    space_public_id=space_id,
                    prompt=prompt,
                    user=user,
                    source_asset_ids=source_asset_ids,
                    asset_origin="chat_generated",
                )
                return {
                    "success": True,
                    "asset": record,
                    "message": (
                        f"数字资产已生成完毕（{record.get('asset_id')}）。"
                        f"当前状态：{record.get('asset_status')}。"
                        f"如需上架到交易平台，请告诉我。"
                    ),
                }
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"asset_manage failed: {e}")
            return {"success": False, "error": str(e)}

    async def organize_assets(asset_ids: List[str], space_id: str) -> Dict[str, Any]:
        """对指定资产执行特征提取与聚类整理。"""
        from app.services.asset_service import AssetService
        from app.services.base import get_llm_client

        try:
            asset_service = AssetService(db)
            assets = []
            for aid in asset_ids:
                try:
                    asset = await asset_service.get_asset(space_id, aid, user)
                    assets.append({
                        "asset_id": aid,
                        "name": asset.get("title", f"Asset {aid}"),
                        "content": asset.get("content_markdown", ""),
                        "category": asset.get("asset_type", "knowledge_report"),
                    })
                except Exception:
                    pass

            if not assets:
                return {"success": False, "error": "No assets could be loaded", "clusters": []}

            # Simple categorization
            clusters_dict: Dict[str, List[Dict[str, Any]]] = {}
            for asset in assets:
                cat = asset.get("category", "未分类")
                clusters_dict.setdefault(cat, []).append(asset)

            clusters = []
            for idx, (category, items) in enumerate(clusters_dict.items()):
                clusters.append({
                    "cluster_id": f"cluster_{idx}",
                    "category": category,
                    "asset_ids": [a["asset_id"] for a in items],
                    "size": len(items),
                    "method": "category",
                })

            # Generate summary report
            try:
                llm = get_llm_client(temperature=0.3)
                report_prompt = f"""你是资产整理助手。根据以下资产聚类结果生成一份简短的中文整理报告。

资产总数: {len(assets)}
聚类数量: {len(clusters)}

聚类详情:
"""
                for c in clusters:
                    report_prompt += f"- {c['category']}: {c['size']} 个资产\n"

                report_prompt += "\n请生成包含概况、聚类描述和建议的整理报告（Markdown格式）："

                response = await llm.ainvoke(report_prompt)
                summary_report = response.content if hasattr(response, "content") else str(response)
            except Exception as e:
                logger.warning(f"Summary generation failed: {e}")
                summary_report = f"## 资产整理报告\n\n共整理 {len(assets)} 个资产，分为 {len(clusters)} 个类别。"

            return {
                "success": True,
                "clusters": clusters,
                "num_clusters": len(clusters),
                "summary_report": summary_report,
                "publication_ready": True,
            }

        except Exception as e:
            logger.exception(f"organize_assets failed: {e}")
            return {"success": False, "error": str(e), "clusters": []}

    async def get_asset_lineage(asset_id: str, max_depth: int = 3) -> Dict[str, Any]:
        """获取资产的血缘图数据。"""
        from app.services.asset_lineage_pricing_service import AssetLineagePricingService

        try:
            service = AssetLineagePricingService(db)
            graph = await service.get_lineage_graph(asset_id, max_depth)
            return {"success": True, "asset_id": asset_id, "graph": graph}
        except Exception as e:
            logger.exception(f"get_asset_lineage failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_asset_price(asset_id: str) -> Dict[str, Any]:
        """获取资产的推荐定价。"""
        from app.services.asset_lineage_pricing_service import AssetLineagePricingService

        try:
            service = AssetLineagePricingService(db)
            pricing = await service.calculate_price(asset_id)
            return {
                "success": True,
                "asset_id": asset_id,
                "recommended_price": pricing.recommended_price,
                "fair_value": pricing.fair_value,
                "price_range": {
                    "min": pricing.price_range_min,
                    "max": pricing.price_range_max,
                },
                "lineage_verified": pricing.lineage_verified,
                "quality_score": pricing.quality_score,
            }
        except Exception as e:
            logger.exception(f"get_asset_price failed: {e}")
            return {"success": False, "error": str(e)}

    async def simulate_asset_price(
        asset_id: str, rights_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """模拟不同权益配置下的资产价格。"""
        from app.services.asset_lineage_pricing_service import AssetLineagePricingService

        try:
            service = AssetLineagePricingService(db)
            pricing = await service.calculate_price(asset_id, rights_types=rights_types)
            return {
                "success": True,
                "asset_id": asset_id,
                "rights_types": rights_types,
                "recommended_price": pricing.recommended_price,
                "fair_value": pricing.fair_value,
                "price_range": {
                    "min": pricing.price_range_min,
                    "max": pricing.price_range_max,
                },
                "factors": {
                    "base_value": pricing.factors.base_value,
                    "quality_multiplier": pricing.factors.quality_multiplier,
                    "scarcity_multiplier": pricing.factors.scarcity_multiplier,
                    "lineage_multiplier": pricing.factors.lineage_multiplier,
                    "rights_scope_multiplier": pricing.factors.rights_scope_multiplier,
                    "market_multiplier": pricing.factors.market_multiplier,
                    "sensitivity_multiplier": pricing.factors.sensitivity_multiplier,
                    "computation_cost": pricing.factors.computation_cost,
                },
            }
        except Exception as e:
            logger.exception(f"simulate_asset_price failed: {e}")
            return {"success": False, "error": str(e)}

    async def verify_asset_lineage(asset_id: str) -> Dict[str, Any]:
        """验证资产血缘链的完整性。"""
        from app.services.asset_lineage_pricing_service import AssetLineagePricingService

        try:
            service = AssetLineagePricingService(db)
            verified = await service.verify_lineage_integrity(asset_id)
            return {
                "success": True,
                "asset_id": asset_id,
                "lineage_verified": verified,
            }
        except Exception as e:
            logger.exception(f"verify_asset_lineage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="asset_manage",
            func=asset_manage,
            description="管理数字资产（列出、获取、生成资产）",
            args_schema=AssetManageInput,
            coroutine=asset_manage,
        ),
        StructuredTool.from_function(
            name="organize_assets",
            func=organize_assets,
            description="对指定资产列表执行特征提取与聚类整理，生成整理报告。",
            args_schema=OrganizeAssetsInput,
            coroutine=organize_assets,
        ),
        StructuredTool.from_function(
            name="get_asset_lineage",
            func=get_asset_lineage,
            description="获取指定资产的数据血缘图（上下游关系）",
            args_schema=GetAssetLineageInput,
            coroutine=get_asset_lineage,
        ),
        StructuredTool.from_function(
            name="get_asset_price",
            func=get_asset_price,
            description="获取资产推荐定价（基于血缘、质量、稀缺性等因子）",
            args_schema=GetAssetPriceInput,
            coroutine=get_asset_price,
        ),
        StructuredTool.from_function(
            name="simulate_asset_price",
            func=simulate_asset_price,
            description="模拟不同权益配置下的资产价格",
            args_schema=SimulateAssetPriceInput,
            coroutine=simulate_asset_price,
        ),
        StructuredTool.from_function(
            name="verify_asset_lineage",
            func=verify_asset_lineage,
            description="验证资产血缘链的完整性（哈希校验）",
            args_schema=VerifyAssetLineageInput,
            coroutine=verify_asset_lineage,
        ),
    ]
