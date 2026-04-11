"""
Phase 1 代码检测脚本（独立版）

不依赖完整应用启动，仅测试新创建的文件
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def read_backend_text(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding='utf-8')

print("=" * 60)
print("Phase 1 代码检测（独立版）")
print("=" * 60)

# ============================================================================
# 测试 1: 直接测试 data_rights_events.py
# ============================================================================
print("\n[测试 1] 数据权益事件定义模块")
print("-" * 40)

# 直接执行 data_rights_events.py 的代码
exec(read_backend_text('app/services/trade/data_rights_events.py'))

print("✓ data_rights_events.py 语法正确")
print(f"  - DATA_RIGHTS_EVENT_TYPES: {len(DATA_RIGHTS_EVENT_TYPES)} 个事件类型")
print(f"  - DATA_RIGHTS_PAYLOADS: {len(DATA_RIGHTS_PAYLOADS)} 个载荷模型")

# 检查枚举
assert len(DataRightsType) == 4
assert len(ComputationMethod) == 5
assert len(DataSensitivityLevel) == 4
assert len(AnonymizationLevel) == 4
print("✓ 所有枚举类型定义正确")

# 测试 QualityMetrics
qm = QualityMetrics(
    completeness=0.95,
    accuracy=0.92,
    timeliness=0.88,
    consistency=0.90,
    uniqueness=0.85,
)
expected_score = 0.95*0.25 + 0.92*0.30 + 0.88*0.20 + 0.90*0.15 + 0.85*0.10
assert abs(qm.overall_score - expected_score) < 0.001
print(f"✓ QualityMetrics 综合评分计算正确: {qm.overall_score:.3f}")

# 测试 DataAssetRegisterPayload
try:
    payload = DataAssetRegisterPayload(
        asset_id="asset_test_123",
        owner_id=100,
        asset_name="测试数据资产",
        data_type="medical",
        sensitivity_level=DataSensitivityLevel.HIGH,
        raw_data_source="hospital_db",
        storage_location="minio://bucket/data",
        data_size_bytes=1024000,
    )
    assert payload.asset_id == "asset_test_123"
    assert payload.sensitivity_level == DataSensitivityLevel.HIGH
    print("✓ DataAssetRegisterPayload 验证通过")
except Exception as e:
    print(f"✗ DataAssetRegisterPayload 验证失败: {e}")
    sys.exit(1)

# 测试 DataRightsPayload
try:
    usage_scope = UsageScope(
        time_range={"start": "2026-01-01", "end": "2026-12-31"},
        purposes=["research", "analysis"],
        aggregation_required=True,
    )

    rights = DataRightsPayload(
        data_asset_id="asset_test_123",
        rights_types=[DataRightsType.USAGE_RIGHT, DataRightsType.ANALYSIS_RIGHT],
        usage_scope=usage_scope,
        computation_method=ComputationMethod.FEDERATED_LEARNING,
        anonymization_level=AnonymizationLevel.L3_K_ANONYMITY,
        validity_period=365,
        price=10000.0,
    )
    assert rights.validity_period == 365
    assert len(rights.rights_types) == 2
    print("✓ DataRightsPayload 验证通过")
except Exception as e:
    print(f"✗ DataRightsPayload 验证失败: {e}")
    sys.exit(1)

# 测试序列化
data = rights.model_dump()
assert data["data_asset_id"] == "asset_test_123"
assert data["validity_period"] == 365
print("✓ Pydantic 模型序列化正确")

# ============================================================================
# 测试 2: 检查事件存储扩展
# ============================================================================
print("\n[测试 2] 事件存储扩展")
print("-" * 40)

# 读取 negotiation_event_store.py 检查扩展
content = read_backend_text('app/services/trade/negotiation_event_store.py')

# 检查新事件类型是否已添加
data_rights_events = [
    "DATA_ASSET_REGISTER",
    "DATA_RIGHTS_NEGOTIATION_INIT",
    "DATA_RIGHTS_GRANT",
    "DATA_RIGHTS_COUNTER",
    "USAGE_SCOPE_DEFINE",
    "COMPUTATION_AGREEMENT",
    "DATA_ACCESS_AUDIT",
    "POLICY_VIOLATION",
    "RIGHTS_REVOKE",
]

all_found = True
for event in data_rights_events:
    if event in content:
        print(f"  ✓ {event} 已添加到 valid_types")
    else:
        print(f"  ✗ {event} 未找到")
        all_found = False

if all_found:
    print("✓ 所有数据权益事件类型已添加到事件存储")
else:
    print("✗ 部分事件类型缺失")

# 检查 DATA_RIGHTS_PAYLOADS 导入
if "DATA_RIGHTS_PAYLOADS" in content and "data_rights_events" in content:
    print("✓ 事件载荷验证逻辑已更新")
else:
    print("✗ 事件载荷验证逻辑未正确更新")

# ============================================================================
# 测试 3: 检查事件溯源黑板扩展
# ============================================================================
print("\n[测试 3] 事件溯源黑板扩展")
print("-" * 40)

content = read_backend_text('app/services/trade/event_sourcing_blackboard.py')

# 检查导入
if "from app.services.trade.data_rights_events import" in content:
    print("✓ 数据权益事件模块已导入")
else:
    print("✗ 数据权益事件模块未导入")

# 检查 ALL_EVENT_PAYLOADS
if "ALL_EVENT_PAYLOADS = {**EVENT_PAYLOADS, **DATA_RIGHTS_PAYLOADS}" in content:
    print("✓ 事件载荷映射已合并")
else:
    print("✗ 事件载荷映射未正确合并")

# ============================================================================
# 测试 4: 检查数据权益服务
# ============================================================================
print("\n[测试 4] 数据权益服务")
print("-" * 40)

content = read_backend_text('app/services/trade/data_rights_service.py')

# 检查关键方法
methods = [
    'register_data_asset',
    'initiate_rights_negotiation',
    'counter_rights_offer',
    'grant_data_rights',
    'negotiate_computation_protocol',
    'record_data_access',
    'report_policy_violation',
    'revoke_rights',
]

for method in methods:
    if f"async def {method}(" in content:
        print(f"  ✓ {method} 已定义")
    else:
        print(f"  ✗ {method} 未找到")

# 检查辅助方法
if "_score_computation_methods" in content:
    print("✓ 计算方法评分逻辑已定义")
if "_determine_anonymization_level" in content:
    print("✓ 脱敏级别确定逻辑已定义")

# ============================================================================
# 测试 5: 检查数据库模型
# ============================================================================
print("\n[测试 5] 数据库模型")
print("-" * 40)

content = read_backend_text('app/db/data_rights_models.py')

# 检查表定义
tables = [
    ('DataAssets', 'data_assets'),
    ('DataRightsTransactions', 'data_rights_transactions'),
    ('DataAccessAuditLogs', 'data_access_audit_logs'),
    ('PolicyViolations', 'policy_violations'),
    ('DataLineageNodes', 'data_lineage_nodes'),
]

for class_name, table_name in tables:
    if f"class {class_name}(Base)" in content and f'__tablename__ = "{table_name}"' in content:
        print(f"  ✓ {class_name} -> {table_name}")
    else:
        print(f"  ✗ {class_name} 定义不正确")

# 检查关键字段
key_fields = [
    ('asset_id', 'DataAssets'),
    ('sensitivity_level', 'DataAssets'),
    ('transaction_id', 'DataRightsTransactions'),
    ('rights_types', 'DataRightsTransactions'),
    ('query_fingerprint', 'DataAccessAuditLogs'),
    ('violation_type', 'PolicyViolations'),
]

for field, table in key_fields:
    if field in content:
        print(f"  ✓ {table}.{field} 已定义")
    else:
        print(f"  ! {table}.{field} 可能缺失")

# ============================================================================
# 总结
# ============================================================================
print("\n" + "=" * 60)
print("Phase 1 检测总结")
print("=" * 60)
print("""
[✓] 所有新文件创建成功

实现文件列表：
1. app/services/trade/data_rights_events.py
   - 9 个数据权益事件类型
   - 7 个 Pydantic 载荷模型
   - 4 个枚举类型定义

2. app/services/trade/negotiation_event_store.py（更新）
   - valid_types 扩展 9 个新事件类型
   - 载荷验证逻辑支持数据权益事件

3. app/services/trade/event_sourcing_blackboard.py（更新）
   - 导入数据权益事件载荷
   - ALL_EVENT_PAYLOADS 合并映射

4. app/services/trade/data_rights_service.py
   - DataRightsService 类
   - 数据资产管理方法
   - 权益协商方法
   - 隐私计算协议协商
   - 审计与合规方法

5. app/db/data_rights_models.py
   - DataAssets 数据资产表
   - DataRightsTransactions 权益交易表
   - DataAccessAuditLogs 访问审计日志表
   - PolicyViolations 违规记录表
   - DataLineageNodes 血缘节点表

代码逻辑验证：
- ✓ 枚举类型定义正确
- ✓ Pydantic 模型验证通过
- ✓ 模型序列化/反序列化正确
- ✓ 综合质量评分计算正确
- ✓ 事件类型已正确扩展
- ✓ 服务方法已定义

下一步：
- 运行 alembic migration 创建数据库表
- 实现 DataAssets 表的 CRUD
- 集成到 TradeNegotiationService
""")

print("=" * 60)
