"""
LLM Gateway - LLM 统一网关

实现个人LLM与系统LLM的功能划分：

1. 个人LLM (Personal LLM): 负责个人数据相关的工作流程
   - RAG问答、文件查询、数据处理
   - 资产整理、知识图谱构建
   - 文档摄取、个人助理

2. 系统LLM (System LLM): 负责监管、审计、仲裁、安全
   - 交易协商监管
   - 定价计算与评估
   - Prompt安全审查
   - 仲裁决策
   - 审计日志分析
   - 异常行为检测

使用方式:
    gateway = LLMGateway(db, user_id)

    # 个人任务 - 使用用户自己的LLM API
    client = await gateway.get_personal_client(FeatureType.CHAT)
    response = await client.invoke("总结我的文档")

    # 系统任务 - 使用系统LLM API
    client = await gateway.get_system_client(SystemFeatureType.PRICE_REVIEW)
    response = await client.invoke("评估价格合理性")
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import FeatureType, LLMProvider

logger = logging.getLogger(__name__)


class SystemFeatureType(str, Enum):
    """系统级LLM功能类型"""
    # 交易监管
    TRADE_NEGOTIATION_MONITOR = "trade_negotiation_monitor"  # 交易协商监管
    PRICE_REVIEW = "price_review"  # 价格审查
    ARBITRATION = "arbitration"  # 仲裁决策

    # 安全审查
    PROMPT_SAFETY_CHECK = "prompt_safety_check"  # Prompt安全检测
    CONTENT_MODERATION = "content_moderation"  # 内容审核

    # 审计分析
    AUDIT_ANALYSIS = "audit_analysis"  # 审计日志分析
    ANOMALY_DETECTION = "anomaly_detection"  # 异常检测

    # 定价评估
    PRICING_CALCULATION = "pricing_calculation"  # 定价计算
    MARKET_ANALYSIS = "market_analysis"  # 市场分析

    # 其他系统功能
    SYSTEM_AUDIT = "system_audit"  # 系统审计
    COMPLIANCE_CHECK = "compliance_check"  # 合规检查


@dataclass
class LLMTaskClassification:
    """LLM任务分类结果"""
    is_system_task: bool
    feature_type: SystemFeatureType | FeatureType
    reason: str


class LLMTaskClassifier:
    """
    LLM任务分类器

    根据任务描述自动判断应该使用个人LLM还是系统LLM
    """

    # 系统任务关键词映射
    SYSTEM_TASK_PATTERNS: Dict[SystemFeatureType, List[str]] = {
        SystemFeatureType.TRADE_NEGOTIATION_MONITOR: [
            "交易", "协商", "谈判", "买卖", "议价", "出价", "报价",
            "trade", "negotiation", "bid", "offer", "deal"
        ],
        SystemFeatureType.PRICE_REVIEW: [
            "价格审查", "定价审核", "价格评估", "价格合理性",
            "price review", "price assessment", "pricing validation"
        ],
        SystemFeatureType.ARBITRATION: [
            "仲裁", "裁决", "调解", "争议解决",
            "arbitration", "mediate", "dispute resolution"
        ],
        SystemFeatureType.PROMPT_SAFETY_CHECK: [
            "安全检测", "安全审查", "prompt检查", "注入检测",
            "safety check", "prompt validation", "injection detection"
        ],
        SystemFeatureType.CONTENT_MODERATION: [
            "内容审核", "敏感内容", "违规检测",
            "content moderation", "sensitive content"
        ],
        SystemFeatureType.AUDIT_ANALYSIS: [
            "审计", "日志分析", "行为分析", "交易分析",
            "audit", "log analysis", "behavior analysis"
        ],
        SystemFeatureType.ANOMALY_DETECTION: [
            "异常检测", "欺诈检测", "可疑行为",
            "anomaly detection", "fraud detection", "suspicious"
        ],
        SystemFeatureType.PRICING_CALCULATION: [
            "定价计算", "价格推荐", "估价",
            "pricing", "valuation", "price recommendation"
        ],
        SystemFeatureType.MARKET_ANALYSIS: [
            "市场分析", "市场趋势", "竞争分析",
            "market analysis", "market trend", "competitive analysis"
        ],
        SystemFeatureType.COMPLIANCE_CHECK: [
            "合规检查", "政策检查", "规则验证",
            "compliance", "policy check", "rule validation"
        ],
    }

    # 个人任务关键词映射
    PERSONAL_TASK_PATTERNS: Dict[FeatureType, List[str]] = {
        FeatureType.CHAT: ["问答", "对话", "聊天", "询问", "chat", "qa"],
        FeatureType.FILE_QUERY: ["文件", "文档查询", "检索", "file", "document"],
        FeatureType.ASSET_GENERATION: ["生成", "创建", "generate", "create"],
        FeatureType.ASSET_ORGANIZE: ["整理", "组织", "organize", "categorize"],
        FeatureType.GRAPH_CONSTRUCTION: ["图谱", "关系", "graph", "knowledge"],
        FeatureType.INGEST_PIPELINE: ["摄取", "导入", "ingest", "import"],
        FeatureType.EMBEDDING: ["嵌入", "向量", "embedding", "vector"],
    }

    @classmethod
    def classify_task(
        cls,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> LLMTaskClassification:
        """
        分类任务类型

        Args:
            task_description: 任务描述
            context: 上下文信息

        Returns:
            LLMTaskClassification
        """
        task_lower = task_description.lower()

        # 1. 检查是否是系统任务（优先级更高）
        for feature_type, patterns in cls.SYSTEM_TASK_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in task_lower:
                    return LLMTaskClassification(
                        is_system_task=True,
                        feature_type=feature_type,
                        reason=f"Matched system pattern: {pattern}"
                    )

        # 2. 检查是否是个人任务
        for feature_type, patterns in cls.PERSONAL_TASK_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in task_lower:
                    return LLMTaskClassification(
                        is_system_task=False,
                        feature_type=feature_type,
                        reason=f"Matched personal pattern: {pattern}"
                    )

        # 3. 根据上下文判断
        if context:
            # 如果涉及交易、协商、审计等，使用系统LLM
            if any(k in context for k in ["trade", "negotiation", "audit", "escrow"]):
                return LLMTaskClassification(
                    is_system_task=True,
                    feature_type=SystemFeatureType.SYSTEM_AUDIT,
                    reason="Context indicates system task"
                )

            # 如果涉及个人数据、文档等，使用个人LLM
            if any(k in context for k in ["personal", "document", "my_file", "user_data"]):
                return LLMTaskClassification(
                    is_system_task=False,
                    feature_type=FeatureType.CHAT,
                    reason="Context indicates personal data task"
                )

        # 4. 默认使用个人LLM（更安全的选择）
        return LLMTaskClassification(
            is_system_task=False,
            feature_type=FeatureType.OTHER,
            reason="Default to personal LLM for undefined tasks"
        )


class PersonalLLMClient:
    """
    个人LLM客户端封装

    使用用户自己的LLM API配置
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        feature_type: FeatureType,
        feature_detail: Optional[str] = None,
    ):
        self.db = db
        self.user_id = user_id
        self.feature_type = feature_type
        self.feature_detail = feature_detail
        self._client = None
        self._config = None

    async def _init_client(self):
        """初始化LLM客户端"""
        if self._client is not None:
            return

        from app.services.user_agent_service import UserAgentService

        service = UserAgentService(self.db)
        self._client = await service.get_user_llm_client(
            self.user_id,
            temperature=0.2
        )
        self._config = await service.get_user_agent_settings(self.user_id)

    async def invoke(self, prompt: str, **kwargs) -> str:
        """调用个人LLM"""
        await self._init_client()

        # 使用TrackedLLMClient记录用量
        from app.ai.llm_client import TrackedLLMClient
        from app.db.models import LLMProvider

        # 确定provider
        provider = LLMProvider.DEEPSEEK
        if self._config and self._config.provider:
            try:
                provider = LLMProvider(self._config.provider.upper())
            except ValueError:
                pass

        is_custom = self._config and self._config.api_key is not None

        tracked_client = TrackedLLMClient(
            db=self.db,
            user_id=self.user_id,
            feature_type=self.feature_type,
            feature_detail=self.feature_detail,
            provider=provider,
            model=self._config.model if self._config else None,
            api_key=self._config.api_key if self._config else None,
            base_url=self._config.base_url if self._config else None,
            is_custom_api=is_custom,
        )

        response, _ = await tracked_client.invoke(prompt, **kwargs)
        return response

    async def stream(self, prompt: str, **kwargs):
        """流式调用个人LLM"""
        await self._init_client()

        from app.ai.llm_client import TrackedLLMClient
        from app.db.models import LLMProvider

        provider = LLMProvider.DEEPSEEK
        if self._config and self._config.provider:
            try:
                provider = LLMProvider(self._config.provider.upper())
            except ValueError:
                pass

        is_custom = self._config and self._config.api_key is not None

        tracked_client = TrackedLLMClient(
            db=self.db,
            user_id=self.user_id,
            feature_type=self.feature_type,
            feature_detail=self.feature_detail,
            provider=provider,
            model=self._config.model if self._config else None,
            api_key=self._config.api_key if self._config else None,
            base_url=self._config.base_url if self._config else None,
            is_custom_api=is_custom,
        )

        async for chunk, usage in tracked_client.stream(prompt, **kwargs):
            yield chunk, usage


class SystemLLMClient:
    """
    系统LLM客户端封装

    使用系统配置的LLM API，用于监管、审计、安全等系统级任务
    费用计入平台成本，不记录到个人用户
    """

    def __init__(
        self,
        db: AsyncSession,
        feature_type: SystemFeatureType,
        feature_detail: Optional[str] = None,
    ):
        self.db = db
        self.feature_type = feature_type
        self.feature_detail = feature_detail
        self._client = None

    async def _init_client(self):
        """初始化系统LLM客户端"""
        if self._client is not None:
            return

        from app.services.base import get_llm_client

        # 系统LLM使用较低温度，确保一致性
        self._client = get_llm_client(temperature=0.1)

    async def invoke(self, prompt: str, **kwargs) -> str:
        """调用系统LLM"""
        await self._init_client()

        # 系统LLM调用也记录用量，但使用系统用户ID（0）
        from app.ai.llm_client import TrackedLLMClient
        from app.db.models import LLMProvider, FeatureType

        # 将SystemFeatureType映射到FeatureType用于记录
        feature_type_for_tracking = self._map_to_feature_type()

        tracked_client = TrackedLLMClient(
            db=self.db,
            user_id=0,  # 系统用户ID
            feature_type=feature_type_for_tracking,
            feature_detail=f"[SYSTEM] {self.feature_type.value}: {self.feature_detail or ''}",
            provider=LLMProvider.DEEPSEEK,  # 系统默认使用DeepSeek
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            is_custom_api=False,  # 系统API不是个人自定义
            temperature=0.1,  # 系统任务使用更低温度
        )

        response, _ = await tracked_client.invoke(prompt, **kwargs)

        logger.debug(
            f"System LLM call: feature={self.feature_type.value}, "
            f"detail={self.feature_detail}"
        )

        return response

    async def stream(self, prompt: str, **kwargs):
        """流式调用系统LLM（系统任务通常不需要流式）"""
        await self._init_client()

        from app.ai.llm_client import TrackedLLMClient
        from app.db.models import LLMProvider

        feature_type_for_tracking = self._map_to_feature_type()

        tracked_client = TrackedLLMClient(
            db=self.db,
            user_id=0,
            feature_type=feature_type_for_tracking,
            feature_detail=f"[SYSTEM] {self.feature_type.value}: {self.feature_detail or ''}",
            provider=LLMProvider.DEEPSEEK,
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            is_custom_api=False,
            temperature=0.1,
        )

        async for chunk, usage in tracked_client.stream(prompt, **kwargs):
            yield chunk, usage

    def _map_to_feature_type(self) -> FeatureType:
        """将SystemFeatureType映射到FeatureType用于用量记录"""
        mapping = {
            SystemFeatureType.TRADE_NEGOTIATION_MONITOR: FeatureType.TRADE_NEGOTIATION,
            SystemFeatureType.PRICE_REVIEW: FeatureType.TRADE_PRICING,
            SystemFeatureType.ARBITRATION: FeatureType.REVIEW,
            SystemFeatureType.PROMPT_SAFETY_CHECK: FeatureType.REVIEW,
            SystemFeatureType.CONTENT_MODERATION: FeatureType.REVIEW,
            SystemFeatureType.AUDIT_ANALYSIS: FeatureType.REVIEW,
            SystemFeatureType.ANOMALY_DETECTION: FeatureType.REVIEW,
            SystemFeatureType.PRICING_CALCULATION: FeatureType.TRADE_PRICING,
            SystemFeatureType.MARKET_ANALYSIS: FeatureType.TRADE_PRICING,
            SystemFeatureType.SYSTEM_AUDIT: FeatureType.REVIEW,
            SystemFeatureType.COMPLIANCE_CHECK: FeatureType.REVIEW,
        }
        return mapping.get(self.feature_type, FeatureType.OTHER)


class LLMGateway:
    """
    LLM 统一网关

    根据任务类型自动选择使用个人LLM还是系统LLM
    """

    def __init__(self, db: AsyncSession, user_id: Optional[int] = None):
        self.db = db
        self.user_id = user_id

    async def get_personal_client(
        self,
        feature_type: FeatureType,
        feature_detail: Optional[str] = None
    ) -> PersonalLLMClient:
        """
        获取个人LLM客户端

        用于：RAG问答、文件查询、数据处理、资产整理等个人数据相关任务
        """
        if not self.user_id:
            raise ServiceError(400, "User ID required for personal LLM client")

        return PersonalLLMClient(
            db=self.db,
            user_id=self.user_id,
            feature_type=feature_type,
            feature_detail=feature_detail
        )

    async def get_system_client(
        self,
        feature_type: SystemFeatureType,
        feature_detail: Optional[str] = None
    ) -> SystemLLMClient:
        """
        获取系统LLM客户端

        用于：交易监管、审计、仲裁、安全审查等系统级任务
        """
        return SystemLLMClient(
            db=self.db,
            feature_type=feature_type,
            feature_detail=feature_detail
        )

    async def route_task(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> PersonalLLMClient | SystemLLMClient:
        """
        自动路由任务到正确的LLM

        Args:
            task_description: 任务描述
            context: 上下文信息

        Returns:
            适当的LLM客户端
        """
        classification = LLMTaskClassifier.classify_task(task_description, context)

        logger.info(
            f"LLM task routing: {task_description[:50]}... -> "
            f"{'SYSTEM' if classification.is_system_task else 'PERSONAL'} "
            f"({classification.feature_type.value})"
        )

        if classification.is_system_task:
            return await self.get_system_client(
                feature_type=classification.feature_type,  # type: ignore
                feature_detail=task_description[:100]
            )
        else:
            if not self.user_id:
                raise ServiceError(400, "User ID required for personal LLM task")
            return await self.get_personal_client(
                feature_type=classification.feature_type,  # type: ignore
                feature_detail=task_description[:100]
            )

    async def invoke_with_routing(
        self,
        task_description: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        自动路由并调用LLM

        便捷方法：自动判断任务类型并调用相应的LLM
        """
        client = await self.route_task(task_description, context)
        return await client.invoke(prompt, **kwargs)


# ============================================================================
# 便捷函数
# ============================================================================

async def get_personal_llm(
    db: AsyncSession,
    user_id: int,
    feature_type: FeatureType,
    feature_detail: Optional[str] = None
) -> PersonalLLMClient:
    """便捷函数：获取个人LLM客户端"""
    gateway = LLMGateway(db, user_id)
    return await gateway.get_personal_client(feature_type, feature_detail)


async def get_system_llm(
    db: AsyncSession,
    feature_type: SystemFeatureType,
    feature_detail: Optional[str] = None
) -> SystemLLMClient:
    """便捷函数：获取系统LLM客户端"""
    gateway = LLMGateway(db)
    return await gateway.get_system_client(feature_type, feature_detail)


async def llm_route_and_invoke(
    db: AsyncSession,
    user_id: Optional[int],
    task_description: str,
    prompt: str,
    **kwargs
) -> str:
    """便捷函数：自动路由并调用LLM"""
    gateway = LLMGateway(db, user_id)
    return await gateway.invoke_with_routing(task_description, prompt, **kwargs)
