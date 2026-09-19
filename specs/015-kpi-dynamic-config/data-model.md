# 数据模型：KPI 按需分类与动态口径配置

## 数据分层

```text
Git 基础资源
  ├── deploy/data/kpi/base/metrics.json
  └── deploy/data/kpi/base/units.json

SQLite 动态配置
  ├── kpi_classifications                     # 既有
  ├── kpi_classification_revisions            # 既有
  ├── kpi_classification_audits               # 既有
  ├── kpi_metric_rules
  ├── kpi_metric_formulas
  ├── kpi_thresholds
  ├── kpi_capacity_rules
  ├── kpi_display_rules
  ├── kpi_common_config
  ├── kpi_rule_config_revisions
  └── kpi_rule_config_audits

任务快照
  └── output/<task_id>/kpi/kpi_catalog_snapshot.json
```

## 基础资源

继续由离线工具生成，运行时只读。

### `base/metrics.json`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `schema_version` | integer | 当前为 1 |
| `source_csv_sha256` | string | 64 位小写 SHA-256 |
| `metrics` | array | 完整替换的基础指标 |

每个指标：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `resource_id` | string | `ME_[A-Za-z0-9_]+`，全局唯一 |
| `key` | string | `resource_id.lower()`，全局唯一 |
| `name_zh` | string | 非空 |
| `name_en` | string | 非空 |
| `unit_key` | string \| null | 当前必须为 `null` |

### `base/units.json`

只保存 `UNIT_*` 预留单位；当前不参与指标单位映射。

## 动态配置模型

### `kpi_metric_rules`

保存基础指标的业务计算口径；`metric_key` 主键。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `metric_key` | string | 必须存在于基础资源 |
| `metric_type` | enum | `count`、`rate`、`capacity`、`latency`、`gauge` |
| `semantic_group` | enum | `traffic`、`quality`、`latency`、`capacity`、`other` |
| `display_role` | enum | `highlight`、`context` |
| `unit` | string | 非空 |
| `source_type` | enum | `raw`、`derived` |
| `aggregation_kind` | enum | `sum`、`min`、`max`、`mean`、`count`、`median`、`stddev`、`success_rate` |
| `description` | string \| null | 可选 |
| `created_at` / `updated_at` | datetime | UTC |

状态：

- 无行时执行器使用默认 raw/sum 规则。
- `source_type=raw` 时公式必须为空。
- `source_type=derived` 时必须存在公式行。

### `kpi_metric_formulas`

与 `metric_key` 一对一。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `metric_key` | string | 主键，存在于 `kpi_metric_rules` |
| `numerator` | string | 存在的基础指标 key |
| `denominator` | string | 存在的基础指标 key |
| `denominator_fallback_inputs` | JSON array | 可为空；元素唯一且存在 |
| `scale` | number | 有限数字 |
| `created_at` / `updated_at` | datetime | UTC |

约束：

- `aggregation_kind=success_rate` 只用于已配置受控 `ratio` 公式的派生指标；`min`、`max`、`mean`、`median`、`stddev` 用于 raw 指标。
- 分子、分母和兜底输入不得形成循环。
- 派生指标及其输入应属于同一有效业务域；未分类输入导致快照配置无效。
- 被公式引用的指标不得重新分类。

### `kpi_thresholds`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | integer | 主键 |
| `domain` | enum | `call`、`api`、`media` |
| `metric_key` | string | 存在于基础资源 |
| `label` | string | 非空 |
| `direction` | enum | `min`、`max` |
| `unit` | string | 非空 |
| `default` | number | 有限数字 |
| `periods` | JSON object | key 只能是 `5`、`15`、`30`、`60` |
| `created_at` / `updated_at` | datetime | UTC |

唯一性：`domain + metric_key`。

### `kpi_capacity_rules`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | integer | 主键 |
| `source_name` | string | 非空，全局唯一 |
| `metric_key` | string | 存在于基础资源 |
| `domain` | enum \| null | 可选；为空时按分类归属 |
| `semantics` | enum \| null | `peak`、`concurrency`、`gauge` |
| `status` | enum | `confirmed`、`unknown` |
| `created_at` / `updated_at` | datetime | UTC |

约束：`status=confirmed` 时 `semantics` 必填；`status=unknown` 时 `semantics` 必须为空。

### `kpi_display_rules`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | integer | 主键 |
| `domain` | enum | `call`、`api`、`media` |
| `metric_key` | string | 存在于基础资源 |
| `role` | enum | `highlight`、`context` |
| `created_at` / `updated_at` | datetime | UTC |

唯一性：`domain + metric_key`。

### `kpi_common_config`

单行表，`id=1`。

| 字段 | 类型 | 默认值 |
| --- | --- | --- |
| `input_timezone` | string | `Asia/Shanghai` |
| `max_files` | integer | `1000` |
| `max_records` | integer | `200000` |
| `updated_at` | datetime | UTC |

### `kpi_rule_config_revisions`

单行表，`id=1`。

| 字段 | 说明 |
| --- | --- |
| `revision` | 从 0 开始；任一动态配置成功修改后递增 1 |
| `updated_at` | UTC |

### `kpi_rule_config_audits`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 主键 |
| `entity_type` | string | `metric_rule`、`threshold`、`capacity_rule`、`display_rule`、`common_config` |
| `entity_key` | string | metric key 或行 ID 字符串 |
| `operation` | enum | `upsert`、`delete` |
| `operator` | string | 非空 |
| `before` | JSON \| null | 变更前资源 |
| `after` | JSON \| null | 变更后资源 |
| `result` | string | 成功审计固定 `success` |
| `rule_config_version` | integer | 本次提交后的版本 |
| `detail` | JSON \| null | 可选上下文 |
| `operated_at` | datetime | UTC |

## 任务 KPI 快照 v2

```json
{
  "schema_version": 2,
  "base_data_version": "sha256:...",
  "classification_version": 12,
  "rule_config_version": 34,
  "captured_at": "2026-09-19T00:00:00Z",
  "base_metrics": [],
  "metrics": [],
  "rules": {
    "common": {},
    "metric_rules": [],
    "thresholds": [],
    "capacity_rules": [],
    "display_rules": []
  }
}
```

语义：

- `base_metrics`：任务生成时的完整基础资源。
- `metrics`：已分类指标与其有效规则。
- `rules`：任务生成时从数据库组装并校验后的有效规则。
- `classification_version`：既有分类修订号。
- `rule_config_version`：除分类外的动态配置修订号。
- `captured_at`：UTC。
- 文件写入后不可变；缺失时新任务按当前状态重建，旧任务单规则重跑要求可解析快照。

兼容性：

- v1 快照仍可读取；缺失 `rule_config_version` 视为 0。
- v1 快照不自动升级；全量重建才生成 v2。
- 读取或校验失败必须报错，不得回退规则 JSON。

## 按需分类线索

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_name` | string | CSV 原始列名 |
| `metric_key` | string \| null | 唯一匹配时返回 |
| `candidates` | array | 多候选时的基础资源摘要 |
| `clue_status` | enum | `unclassified`、`classified`、`unregistered`、`ambiguous` |
| `rule_code` | string | 产生线索的 KPI 规则 |
| `domain` | string | KPI 文件解析出的业务域 |
| `source_files` | array | 出现该列的文件 |
| `record_count` | integer | 记录数 |
| `sample_values` | array | 截断后的样例值 |
| `resolution_note` | string \| null | 解析失败或歧义说明 |

状态：

- `unclassified`：匹配唯一基础资源且当前分类为空。
- `classified`：匹配唯一基础资源且已有业务域，但任务快照旧。
- `unregistered`：没有基础资源匹配。
- `ambiguous`：匹配多个候选。

## 引用与生命周期

### 分类生命周期

```text
未分类 → call/api/media
call/api/media → 另一个业务域
任意状态 → 未分类
```

限制：

- 指标被公式、阈值、容量规则或展示规则引用时禁止变更业务域。
- 批量分类任一指标失败时整批回滚。

### 指标规则生命周期

```text
无规则（默认 raw/sum）
  → raw 规则
  → derived + formula
  → raw 规则 / 无规则
```

### 阈值生命周期

```text
不存在 → 创建 → 修改 → 删除
```

### 基础数据替换

```text
读取 CSV → 生成新 base JSON
  → 校验 Git/CSV 结构
  → 校验数据库引用完整性
  → 原子替换 base 文件
```

任一阶段失败时，`base/metrics.json` 与 `base/units.json` 必须保持不变。
