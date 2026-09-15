# 数据模型：KPI 指标字典与分组展示

## 1. 概览

本功能新增三类运行时模型：

1. **静态 KPI 目录配置**：由 `deploy/config/kpi/*.yaml` 维护。
2. **规则结果 KPI 元数据**：写入 `RuleResult.metadata`，供 API 和前端消费。
3. **原始记录投影**：不新增持久化数据，按请求从规则结果元数据投影分页结果。

历史 `output/<task_id>/rules/*.json` 不迁移。

## 2. 配置实体

### KpiCommonConfig

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `version` | integer | 是 | 固定为 `2`。 |
| `input_timezone` | string | 是 | IANA 时区；解析输入时间后存储为 UTC。 |
| `budgets` | object | 是 | 继承既有五项解析预算：文件大小、行数、列数、领域文件数、领域记录数。 |

校验：
- `version != 2` 时配置错误。
- `input_timezone` 必须可被 `zoneinfo.ZoneInfo` 解析。
- 五个预算必须为正整数。

### KpiMetricDefinition

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `key` | string | 是 | 领域内唯一稳定标识，匹配 `[a-z][a-z0-9_]*`。 |
| `name_zh` | string | 是 | 中文展示名。 |
| `name_en` | string | 是 | 英文展示名或英文语义名。 |
| `aliases` | array | 是 | 源数据列名别名；至少包含目标源数据叫法。 |
| `metric_type` | enum | 是 | `count`、`rate`、`capacity`、`latency`、`gauge`。 |
| `semantic_group` | enum | 是 | `quality`、`traffic`、`capacity`、`latency`、`other`。 |
| `display_role` | enum | 是 | `highlight`、`context`、`diagnostic`、`catalog`。 |
| `unit` | string \| null | 是 | 展示单位；无单位使用空串或 `null`，序列化后保持稳定。 |
| `source_type` | enum | 是 | `raw`、`derived`。 |
| `aggregation` | object | 是 | 主值汇总方式。 |
| `formula` | object \| null | 条件 | `source_type=derived` 时必填。 |
| `description` | string \| null | 否 | 指标业务说明。 |

别名项：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `language` | enum | 是 | `zh`、`en`、`unknown`。 |
| `value` | string | 是 | 源数据原始列名。 |

校验：
- `key` 在同一领域唯一。
- 归一化后 `name_zh`、`name_en` 和全部 `aliases[].value` 不得指向同一领域的多个指标。
- `metric_type`、`semantic_group`、`display_role`、`source_type` 必须在枚举内。
- `raw` 指标不得声明 `formula`。
- `derived` 指标必须声明公式，且公式输入存在、可解析类型并形成无环依赖。

### KpiAggregation

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `kind` | enum | `sum`、`max`、`percentile`、`ratio_from_inputs`。 |
| `percentile` | number | `kind=percentile` 时必填，范围 `0 < percentile <= 100`。 |

校验与默认语义：
- `count` 使用 `sum`。
- `capacity` 使用 `max`。
- `latency` 使用 `max` 或 `percentile`。
- `rate` 使用 `ratio_from_inputs`，表示先聚合公式输入再计算。
- `gauge` 可按业务声明聚合方式，但不得与上述类型约束冲突。

### KpiRatioFormula

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `kind` | enum | 是 | 第一版固定 `ratio`。 |
| `numerator` | string | 是 | 输入指标稳定 key。 |
| `denominator` | string | 是 | 输入指标稳定 key。 |
| `denominator_fallback` | object \| null | 否 | 分母缺失时的声明式兜底。 |
| `scale` | number | 否 | 输出缩放，默认 `1`；百分比使用 `100`。 |

`denominator_fallback`：

```yaml
kind: sum
inputs:
  - call_success_count
  - call_failure_count
```

校验：
- `kind=sum` 时 `inputs` 至少两项且都存在。
- 公式引用的指标必须与输出属于同一领域。
- 不允许直接或间接自引用。
- 主值仍必须先聚合输入，再执行公式。

### KpiThreshold

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `key` | string | 是 | 已登记指标 key。 |
| `label` | string | 是 | 展示名。 |
| `direction` | enum | 是 | `min`、`max`。 |
| `unit` | string | 是 | 阈值单位。 |
| `default` | number | 是 | 默认阈值。 |
| `periods` | map | 否 | 按 `5/15/30/60` 分钟覆盖默认阈值。 |

校验：
- `key` 必须指向已登记指标。
- 无阈值指标不产生业务状态。

### KpiCapacityAlias

继续兼容既有容量语义：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_name` | string | 源数据列名。 |
| `metric` | string | 稳定容量指标 key。 |
| `semantics` | enum | `peak`、`concurrency`、`gauge`。 |
| `status` | enum | `confirmed`、`unknown`。 |

校验：
- `metric` 必须指向同领域已登记指标。
- 同一源列名不得同时是普通别名冲突目标。

## 3. 规则结果元数据

### KpiRuleMetadata

写入 `RuleResult.metadata`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `version` | integer | 是 | 新结果固定 `2`。 |
| `domain` | string | 是 | `call`、`api` 或 `media`。 |
| `config_source` | string | 是 | `deploy/config/kpi`。 |
| `input_timezone` | string | 是 | 与公共配置一致。 |
| `metric_catalog` | array | 是 | 指标定义的契约化投影。 |
| `kpi_results` | array | 是 | 每个已识别指标的主值和溯源。 |
| `unclassified_metrics` | array | 是 | 未登记源列；无未登记列时为空数组。 |
| `kpi_files` | array | 是 | 保留既有文件摘要；新结果可继续包含原始记录，旧前端默认接口行为不变。 |

### KpiMetricCatalogItem

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | string | 稳定指标标识。 |
| `name_zh` | string | 中文名。 |
| `name_en` | string | 英文名。 |
| `aliases` | array | 原始叫法。 |
| `metric_type` | string | 类型。 |
| `semantic_group` | string | 语义分组。 |
| `display_role` | string | 展示角色。 |
| `unit` | string \| null | 单位。 |
| `source_type` | string | `raw` 或 `derived`。 |
| `aggregation` | object | 主值汇总方式。 |
| `formula` | object \| null | 派生公式。 |

### KpiMetricResult

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `key` | string | 是 | 指向目录 key。 |
| `main_value` | number \| string \| null | 是 | 可用时为数值；不可用时为 `null` 或 `N/A`。 |
| `value_available` | boolean | 是 | 派生失败或无记录时为 `false`。 |
| `unavailable_reason` | string \| null | 条件 | `value_available=false` 时提供可读原因。 |
| `display_status` | enum | 是 | `pass`、`warn`、`fail`、`neutral`、`unavailable`。 |
| `unit` | string \| null | 是 | 展示单位。 |
| `aggregation` | string | 是 | 实际使用的汇总方式。 |
| `threshold` | object \| null | 是 | 阈值方向、默认值和周期覆盖；无阈值为 `null`。 |
| `breach_count` | integer | 是 | 越限记录数；无阈值为 `0`。 |
| `series` | array | 是 | 周期序列；可为空。 |
| `source_files` | array | 是 | 参与聚合的来源文件。 |
| `provenance` | object | 是 | 来源、公式、输入、直接列交叉参考。 |

`display_status` 语义：
- `pass` / `warn` / `fail`：有阈值且可计算。
- `neutral`：无阈值。
- `unavailable`：公式输入缺失、分母为零或数值不可计算。
- 该状态不改变 `RuleResult.status`；规则状态仍由解析错误、一致性和既有阈值越限语义决定。

### KpiProvenance

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_type` | string | `raw` 或 `derived`。 |
| `formula` | string \| null | 人类可读公式。 |
| `inputs` | array | 每个输入 key、聚合后值和聚合方式。 |
| `missing_inputs` | array | 缺失输入 key 和原因。 |
| `direct_cross_reference` | array | 直接同语义列的名称、来源文件和值。 |
| `denominator_zero` | boolean | 分母是否为零。 |
| `fallback_used` | boolean | 是否使用声明式分母兜底。 |

约束：
- `fallback_used=true` 仅表示声明式分母兜底生效，不表示使用直接同语义值兜底。
- 直接列交叉参考不得覆盖 `main_value`。

### KpiUnclassifiedMetric

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_name` | string | 未登记原始列名。 |
| `source_files` | array | 出现该列的文件。 |
| `record_count` | integer | 出现记录数。 |
| `sample_values` | array | 截断后的样例值。 |
| `reason` | string | `metric_not_registered`。 |

约束：
- 不进入 `metric_catalog` 和 `kpi_results`。
- 只因未登记指标不产生解析错误、不改变规则状态。

## 4. 原始记录查询投影

不新增落盘文件。查询服务读取 `RuleResult.metadata.kpi_files[].records`，结合 `metric_catalog`、公式和阈值投影记录。

### KpiRecordPage

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | integer | 过滤后记录总数。 |
| `page` | integer | 当前页，从 1 开始。 |
| `page_size` | integer | 每页条数。 |
| `items` | array | 原始记录投影。 |

### KpiRecordItem

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `metric_key` | string | 稳定指标 key。 |
| `metric_name_zh` | string | 中文展示名。 |
| `source_file` | string | 来源文件。 |
| `line_number` | integer | 源文件行号。 |
| `period_minutes` | integer | 统计周期。 |
| `start_at` | string | UTC 时间。 |
| `end_at` | string | UTC 时间。 |
| `value` | number \| string \| null | 记录级原始或派生值。 |
| `status` | string | 记录级阈值状态；无阈值为 `neutral`。 |
| `errors` | array | 行级错误。 |

## 5. 状态与转换

### 配置状态

```text
loaded → validated → available
        ↘ invalid → rule error
```

### 指标结果状态

```text
raw parsed → available
derived formula complete → available
formula input missing / denominator zero / value invalid → unavailable
threshold evaluated → pass | warn | fail
threshold absent → neutral
```

### 规则状态

保持既有语义：
- 解析失败或阈值越限：`fail`。
- 一致性告警：`warn`。
- 无匹配文件：`skip`。
- 配置加载失败：`error`。
- 仅未分类指标不改变上述状态。

## 6. 关系

- `KpiMetricDefinition.key` ← `KpiThreshold.key`
- `KpiMetricDefinition.key` ← `KpiMetricResult.key`
- `KpiMetricDefinition.key` ← `KpiRatioFormula.numerator/denominator/fallback.inputs`
- `KpiMetricResult.key` → `KpiRecordItem.metric_key`
- `KpiMetricDefinition.domain` → KPI 领域文件
- `KpiRecordItem` → `RuleResult.metadata.kpi_files[].records[]`
