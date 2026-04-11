"""
Data Rights Models - Compatibility Module

这个文件现在仅提供兼容性导入。
所有模型已合并到 app.db.models 中。

请在新代码中直接使用:
    from app.db.models import DataAssets, DataRightsTransactions, ...
"""

# 兼容性导入 - 所有模型现在都在 models.py 中定义
from app.db.models import (
    DataAssets,
    DataRightsTransactions,
    DataAccessAuditLogs,
    PolicyViolations,
    DataLineageNodes,
    DataSensitivityLevel,
    ComputationMethod,
    DataRightsStatus,
)

__all__ = [
    "DataAssets",
    "DataRightsTransactions",
    "DataAccessAuditLogs",
    "PolicyViolations",
    "DataLineageNodes",
    "DataSensitivityLevel",
    "ComputationMethod",
    "DataRightsStatus",
]
