---
skill_id: audit_report
name: 审计报告生成
capability_type: skill
description: 生成交易或访问行为的审计报告，包含访问统计、风险评估、违规检测和改进建议。适用于审计查询、风控解释、合规检查。
executor: app.services.skills.audit_skill:AuditSkill.generate_audit_report
model: deepseek-chat
color: yellow
tools: []
skills: []
input_schema:
  type: object
  properties:
    transaction_id:
      type: string
      description: 交易唯一标识
    days:
      type: integer
      minimum: 1
      maximum: 365
      default: 30
      description: 报告时间窗口（天）
  required:
    - transaction_id
output_summary: 返回 summary（统计摘要）、violations（违规记录）、recommendations（改进建议）和 access_trend（访问趋势）
examples:
  - input:
      transaction_id: "tx_123"
      days: 30
    output:
      success: true
      transaction_id: "tx_123"
      period: "2026-03-22 to 2026-04-21"
      summary:
        total_access_count: 150
        average_risk_score: 0.25
        violation_count: 2
        risk_level: "low"
      access_trend: []
      violations:
        - type: "unauthorized_access"
          severity: "medium"
      recommendations:
        - "加强监控和审查"
        - "向买方发送合规提醒"
  - input:
      transaction_id: "tx_456"
      days: 7
    output:
      success: true
      transaction_id: "tx_456"
      summary:
        total_access_count: 50
        average_risk_score: 0.65
        violation_count: 5
        risk_level: "high"
      recommendations:
        - "立即暂停数据访问，人工审核"
        - "通知数据所有者和管理员"
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: audit
---

# 何时使用本 Skill

## 触发条件
- 用户需要查询某个交易的审计记录
- 风控场景下评估交易风险
- 合规检查，确认数据访问是否合法
- 定期审计报告生成

## 排除条件
- 不要用于实时监控（使用 get_real_time_metrics 接口）
- 不要用于批量审计（使用 batch_audit 接口）
- 不要用于访问摘要（使用 get_access_summary 接口）

# 输入参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `transaction_id` | string | 是 | - | 交易唯一标识 |
| `days` | integer | 否 | `30` | 报告时间窗口（天），范围 1-365 |

# 风险等级判定

| 风险等级 | 平均风险分 | 违规数 | 建议动作 |
|----------|-----------|--------|----------|
| `low` | < 0.3 | 0-2 | 保持现有监控策略 |
| `medium` | 0.3-0.5 | 1-2 | 加强监控，审查访问目的 |
| `high` | 0.5-0.7 | 3+ | 暂停访问，人工审核 |
| `critical` | >= 0.7 | 5+ | 立即冻结，通知管理层 |

# 执行规则

1. 聚合指定时间窗口内的所有访问记录
2. 计算平均风险评分和违规数量
3. 根据评分自动判定风险等级
4. 生成针对性的改进建议
5. 返回完整的访问趋势和违规详情

# 输出格式

```json
{
  "success": true,
  "transaction_id": "tx_123",
  "period": "2026-03-22 to 2026-04-21",
  "summary": {
    "total_access_count": 150,
    "average_risk_score": 0.25,
    "violation_count": 2,
    "risk_level": "low"
  },
  "access_trend": [],
  "violations": [
    {
      "type": "unauthorized_access",
      "severity": "medium"
    }
  ],
  "recommendations": [
    "加强监控和审查",
    "向买方发送合规提醒"
  ],
  "generated_at": "2026-04-21T10:00:00Z"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 报告生成是否成功 |
| `transaction_id` | string | 交易标识 |
| `period` | string | 报告覆盖的时间范围 |
| `summary` | object | 统计摘要，含 total_access_count、average_risk_score、violation_count、risk_level |
| `access_trend` | array | 访问趋势数据 |
| `violations` | object[] | 违规记录列表 |
| `recommendations` | string[] | 改进建议列表 |
| `generated_at` | string | 报告生成时间 |
| `error` | string | 错误信息（失败时出现） |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `success: false` | 审计服务异常 | 检查 transaction_id 是否存在，稍后重试 |
| `total_access_count` 为 0 | 该交易无访问记录 | 可能是新交易，建议延长 days 参数 |
| `risk_level` 与预期不符 | 基于平均风险分自动判定 | 可结合 violation_count 人工复核 |
