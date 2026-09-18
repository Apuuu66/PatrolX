# Git KPI 目录 JSON 契约

## 文件

- 路径：`deploy/data/kpi_catalog.json`
- 编码：UTF-8
- 换行：LF
- 格式：JSON object
- 版本：由文件字节内容 SHA-256 计算，不在文件内自声明

## 顶层

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer | 是 | 固定 `1` |
| `source_csv_sha256` | string | 是 | 64 位小写十六进制 |
| `metrics` | array | 是 | 基础指标，按 `key` 升序，key 唯一 |
| `units` | array | 是 | 预留单位，按 `key` 升序，key 唯一 |
| `rules` | object | 是 | 公式、阈值、容量语义和展示规则 |

## Metric

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `resource_id` | string | 是 | 必须匹配 `ME_[A-Za-z0-9_]+` |
| `key` | string | 是 | 小写资源 ID，匹配 `^[a-z][a-z0-9_]*$` |
| `name_zh` | string | 是 | 非空，原文保留 |
| `name_en` | string | 是 | 非空 |
| `unit_key` | string \| null | 是 | 当前固定 `null` |

## Unit

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `resource_id` | string | 是 | 必须匹配 `UNIT_[A-Za-z0-9_]+` |
| `key` | string | 是 | 小写资源 ID |
| `name_zh` | string | 是 | 非空 |
| `name_en` | string | 是 | 非空 |

`ME_*` 与 `UNIT_*` 的资源 ID 和稳定 key 全局唯一。当前不校验或建立 `unit_key` 指向 `units` 的映射。

## Rules

`rules.common`：

- `input_timezone`：IANA 时区名。
- `budgets`：`max_files`、`max_records` 正整数。

`rules.metric_rules[]`：

- `key`：基础指标 key。
- `metric_type`：`count`、`rate`、`capacity`、`latency`、`gauge`。
- `semantic_group`：`traffic`、`quality`、`latency`、`capacity`、`other`。
- `display_role`：`highlight`、`context`。
- `unit`：当前巡检结果展示单位字符串。
- `source_type`：`raw`、`derived`。
- `aggregation`：现有聚合对象；`percentile` 需要量化范围 `[0,1]` 的 `quantile`。
- `formula`：`derived` 时必填；当前支持 `ratio`，输入必须是基础指标 key，不得循环。
- `description`：可选。

`rules.thresholds[]`：

- `domain`：`call`、`api`、`media`。
- `metric_key`：基础指标 key。
- `label`：非空。
- `direction`：`min` 或 `max`。
- `default`：数字。
- `periods`：可选对象，键为 `5/15/30/60` 分钟字符串，值为数字。

同一 `domain + metric_key` 最多一个阈值。

`rules.capacity_rules[]`：

- `source_name`：非空源列名。
- `metric_key`：基础指标 key。
- `semantics`：`peak`、`concurrency`、`gauge`。
- `status`：`confirmed`、`unknown`。

`rules.display_rules[]`：

- `domain`：`call`、`api`、`media`。
- `metric_key`：基础指标 key。
- `role`：`highlight`、`context`。

同一 `domain + metric_key` 最多一个展示规则。

## 校验失败语义

任一重复、未知字段、非法引用或循环依赖都会导致加载失败。运行时不得跳过无效项后继续暴露部分目录。
