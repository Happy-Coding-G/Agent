# 定价计算公式参考

## 基础定价模型

### 1. 成本加成定价
```
price = base_cost * (1 + markup_rate)
```
- `base_cost`: 数据采集、清洗、标注的基础成本
- `markup_rate`: 利润率，通常为 0.2-0.5

### 2. 质量调整定价
```
quality_multiplier = 0.5 + (quality_score * 0.5)
adjusted_price = base_price * quality_multiplier
```
- `quality_score`: 质量评分，范围 0.0-1.0
- 质量为 0 时最低 multiplier 为 0.5，质量为 1 时最高为 1.0

### 3. 权益类型系数

| 权益类型 | 系数 | 说明 |
|----------|------|------|
| `view` | 1.0 | 仅查看，基础价格 |
| `download` | 1.5 | 可下载，加价 50% |
| `compute` | 2.0 | 可计算，加价 100% |
| `full` | 3.0 | 完全权限，加价 200% |

### 4. 最终价格计算
```
final_price = base_cost * (1 + markup_rate) * quality_multiplier * right_type_multiplier
```

## 价格区间参考

- 低价值数据（公开统计）: 100-500
- 中价值数据（行业报告）: 500-2000
- 高价值数据（专业标注）: 2000-10000
- 核心资产（独家数据）: 10000+
