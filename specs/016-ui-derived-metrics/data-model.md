# 数据模型：界面新增动态派生指标

## 实体

### KpiDerivedMetric

SQLite 表：`kpi_derived_metrics`

| 字段 | 类型/约束 | 说明 |
| --- | --- | --- |
| `metric_key` | String(128), PK | 稳定 key；非空、小写 snake_case，唯一，不得与基础指标/单位 key 冲突 |
| `name_zh` | String(256), 非空 | 中文显示名 |
| `name_en` | String(256), 非空 | 英文显示名 |
| `domain` | String(32), 非空 | 仅允许 `call` / `api` / `media` |
| `metric_type` | String(32), 非空 | 沿用现有 KPI 指标类型枚举 |
| `semantic_group` | String(32), 非空 | 沿用现有语义分组枚举 |
| `display_role` | String(32), 非空 | 沿用现有展示角色枚举 |
| `unit` | String(64), 非空 | 展示单位 |
| `description` | String(512), nullable | 描述 |
| `enabled` | Boolean, 非空 | 停用后不进入新任务快照 |
| `formula_kind` | String(16), 非空 | `ratio` 或 `inverse_ratio` |
| `numerator` | String(128), 非空 | 分子原始指标 key |
| `denominator` | String(128), 非空 | 分母原始指标 key |
| `denominator_fallback_inputs` | JSON list | 可选分母回退输入，全部为原始指标 key |
| `scale` | Float, 非空 | 缩放倍数，有限且大于 0 |
| `created_at` / `updated_at` | UTC datetime | 时间字段使用 `*_at` 命名 |

### 配置修订与审计

- 复用 `kpi_rule_config_revisions` 递增配置版本。
- 复用 `kpi_rule_config_audits` 记录 `entity_type=derived_metric` 的 create/update/delete、操作人、时间、变更前后内容和配置版本。

### 任务快照

`KpiTaskCatalogSnapshot` 升级为 schema version 3，新增：

- `derived_metrics: list[dict]`：保存任务执行时启用的在线派生指标及其受控公式。
- `schema_version` 兼容读取 1、2、3；1/2 无该字段时视为空列表。
- 已有快照文件不重写、不自动补写派生指标。
- 快照中的派生指标不是基础资源，不参与 CSV 名称匹配，也不产生 `resource_id`。

## 校验规则

1. `metric_key` 必须唯一，且不得等于任何基础指标或单位 key。
2. 创建时 key 不存在；更新时只能更新同 key 的在线派生指标。
3. 名称、单位、业务域、指标类型、语义分组、展示角色和公式均完整。
4. `numerator`、`denominator` 和每个回退输入必须：
   - 存在于离线基础资源全集；
   - 已分类为业务域；
   - 与派生指标 `domain` 相同；
   - 不是派生指标、单位或未知 key。
5. 不允许公式输入引用自身；由于第一期输入只能是 raw 指标，派生指标循环引用被结构性阻断。
6. `scale` 为有限数值且大于 0；回退输入去重。
7. 删除前检查阈值、容量规则和展示规则是否引用该 key；被引用时返回冲突和引用来源。
8. 停用的派生指标保留配置与审计，但不进入新任务快照。

## 状态流转

```text
不存在 --create--> 启用
启用 --update(enabled=true)--> 启用
启用/停用 --update(enabled=false)--> 停用
停用 --update(enabled=true)--> 启用
未引用的启用/停用配置 --delete--> 不存在
被引用配置 --delete--> 保持原状态并返回冲突
```

## 任务执行投影

配置快照进入 `KpiConfig` 后：

- 每个启用派生指标成为对应 `KpiDomainConfig.metrics` 中的 `KpiMetricDefinition`。
- `source_type=derived`，`aggregation.kind=success_rate`，`formula.kind` 保留正向/反向类型。
- 不加入 CSV 名称别名索引，避免在线派生 key 被误认为 CSV 原始列。
- KPI 输出继续使用 `KpiMetricResult`；`provenance` 包含输入聚合值、缺失输入、分母为零和公式类型。
