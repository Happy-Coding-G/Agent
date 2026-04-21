---
skill_id: privacy_protocol
name: 隐私计算协议协商
capability_type: skill
description: 根据数据敏感度和买方需求协商隐私计算协议，返回推荐协议、约束条件和成本分摊方案。适用于隐私协作、联合计算协商、脱敏前方案选择。
executor: app.services.skills.privacy_skill:PrivacyComputationSkill.negotiate_protocol
model: deepseek-chat
color: red
tools: []
skills: []
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产唯一标识
    sensitivity:
      type: string
      enum: [low, medium, high, critical]
      description: 数据敏感度级别
    requirements:
      type: object
      nullable: true
      default: null
      description: 买方隐私计算要求，如 {min_protection, precision, max_cost, latency_sensitive}
  required:
    - asset_id
    - sensitivity
output_summary: 返回 protocol（协议详情）、constraints（约束）、cost_allocation（成本分摊）和 reasoning（选择理由）
examples:
  - input:
      asset_id: "asset_123"
      sensitivity: "high"
      requirements:
        min_protection: 3
        precision: "exact"
        max_cost: 1000
    output:
      success: true
      asset_id: "asset_123"
      protocol:
        method: "differential_privacy"
        method_name: "差分隐私"
        description: "通过添加数学噪声保护隐私"
        constraints:
          epsilon: 1.0
          delta: 0.00001
        verification_mechanism: "cryptographic_proof"
        cost_allocation:
          computation: 0.6
          storage: 0.2
          verification: 0.2
      reasoning: "基于high敏感度选择differential_privacy"
  - input:
      asset_id: "asset_456"
      sensitivity: "low"
    output:
      success: true
      asset_id: "asset_456"
      protocol:
        method: "raw_data"
        method_name: "原始数据访问"
        constraints: {}
        verification_mechanism: "none"
        cost_allocation:
          computation: 0.1
          storage: 0.9
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: privacy
---

# 何时使用本 Skill

## 触发条件
- 交易涉及敏感数据，需要协商隐私保护方案
- 联合计算场景中选择合适的协议
- 数据共享前确定脱敏和计算方式
- 合规要求下需要记录隐私协议选择

## 排除条件
- 不要用于直接执行脱敏（使用 anonymize_data 接口）
- 不要用于敏感度评估（使用 assess_sensitivity 接口）
- 低敏感度数据可能直接返回原始数据访问协议

# 输入参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `asset_id` | string | 是 | - | 目标资产唯一标识 |
| `sensitivity` | string | 是 | - | 敏感度：low/medium/high/critical |
| `requirements` | object | 否 | null | 买方需求，见下方说明 |

### requirements 字段说明

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `min_protection` | integer | 最低保护级别 1-4 |
| `precision` | string | 精度要求：exact/high/medium |
| `max_cost` | float | 最大计算成本预算 |
| `latency_sensitive` | boolean | 是否对延迟敏感 |

# 隐私计算方法说明

| 方法 | 适用敏感度 | 数据暴露 | 精度 | 开销 | 信任要求 |
|------|-----------|----------|------|------|----------|
| `raw_data` | low | 完整 | 精确 | 低 | 完全信任 |
| `differential_privacy` | medium-high | 噪声数据 | 高 | 中 | 低 |
| `TEE` | high | 加密 | 精确 | 高 | 硬件信任 |
| `multi_party_computation` | critical | 无暴露 | 精确 | 很高 | 协议信任 |
| `federated_learning` | medium | 梯度 | 中 | 中 | 中 |

# 执行规则

1. `sensitivity` 为必填参数，必须为 low/medium/high/critical 之一
2. 系统根据敏感度和买方需求自动匹配最优协议
3. 高敏感度数据（high/critical）不会推荐原始数据访问
4. 协议协商失败时返回 fallback_method="differential_privacy"

# 输出格式

```json
{
  "success": true,
  "asset_id": "asset_123",
  "protocol": {
    "method": "differential_privacy",
    "method_name": "差分隐私",
    "description": "通过添加数学噪声保护隐私",
    "constraints": {
      "epsilon": 1.0,
      "delta": 0.00001
    },
    "verification_mechanism": "cryptographic_proof",
    "cost_allocation": {
      "computation": 0.6,
      "storage": 0.2,
      "verification": 0.2
    }
  },
  "reasoning": "基于high敏感度选择differential_privacy"
}
```

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `success: false` | 协商失败 | 使用 fallback_method 或降低 requirements 重试 |
| `method` 为 "raw_data" 但 sensitivity 为 high | 输入异常 | 检查 sensitivity 参数是否正确 |
| `constraints` 为空 | 原始数据访问或协商异常 | 正常（raw_data）或重试 |
