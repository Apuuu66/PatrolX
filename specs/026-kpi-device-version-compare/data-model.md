# 数据模型：KPI 同设备版本对比

## 既有存储

### 任务元数据

- `task_id`：任务唯一标识。
- `status`：只有 `completed` 且 `completed_at` 存在的任务可作为候选。
- `customer_version`：任务系统版本；空值表示“版本未知”。
- `system.customer.device_id`：同设备匹配键；空值或缺失表示设备未知。
- `completed_at`：UTC 时间；用于选择同版本最新任务。

### 任务私有历史索引

路径：`output/<task_id>/kpi/history/index.jsonl`

每行必须包含：

- `task_id`
- `measurement_unit_id`
- `metric_resource_id`
- `object_key`（空值读取为 `__all__`）
- `period_minutes`
- `measured_at`
- `value`
- `source_file`
- `line_number`（可选）

索引坏行跳过；同任务同维度同时间点已由写索引逻辑合并均值。

## API 模型

### MeasurementVersionCandidateTask

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务 ID |
| `completed_at` | string/UTC | 完成时间 |
| `version` | string \| null | 系统版本 |
| `version_known` | boolean | 是否有版本元数据 |

### MeasurementVersionCandidate

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version` | string \| null | 版本；null 表示版本未知 |
| `version_known` | boolean | 是否有版本元数据 |
| `latest_task_id` | string | 该版本完成时间最新任务 |
| `latest_completed_at` | string/UTC | 最新任务完成时间 |
| `task_count` | integer | 该版本同设备任务数 |
| `tasks` | array | 全部同设备任务，按完成时间倒序 |

### MeasurementVersionCandidateList

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 当前任务 |
| `device_id` | string \| null | 当前设备 ID |
| `current_version` | string \| null | 当前版本 |
| `items` | array | 版本候选；不包含当前任务自身 |

### MeasurementVersionComparisonMatch

沿用历史匹配的 `status` / `reason_code` / `message` 语义。新增稳定原因码：

- `device_id_missing`
- `current_index_missing`
- `current_metric_dimension_missing`
- `baseline_task_not_found`
- `baseline_device_mismatch`
- `baseline_task_not_completed`
- `baseline_same_version`
- `baseline_version_unknown`
- `baseline_index_missing`
- `baseline_index_empty`
- `baseline_unit_or_metric_missing`
- `baseline_object_or_period_mismatch`

### MeasurementVersionComparisonSummary

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `current_value` | number \| null | 当前任务该维度均值 |
| `baseline_value` | number \| null | 基线任务该维度均值 |
| `absolute_change` | number \| null | 当前均值 - 基线均值 |
| `change_ratio` | number \| null | 绝对变化 / 基线均值绝对值 |
| `direction` | string | `up` / `down` / `flat` / `unknown` |
| `sample_count` | integer | 当前 + 基线有效点数 |
| `message` | string | 中文业务解释 |

### MeasurementVersionComparison

| 字段 | 说明 |
| --- | --- |
| 请求上下文 | `task_id`、`baseline_task_id`、`rule_code`、`measurement_unit_id`、`metric_resource_id`、`object_key`、`period_minutes` |
| 版本信息 | `device_id`、`current_version`、`baseline_version` |
| 任务信息 | `current_task`、`baseline_task`（ID + 完成时间） |
| 曲线 | `current_points`、`baseline_points` |
| 结果 | `summary`、`match` |

## 状态与方向

- `status=matched`：存在至少一条当前点且至少一条基线点。
- `status=no_history`：任务与索引可访问，但基线维度无有效点。
- `status=degraded`：缺少设备、版本约束不满足、索引缺失或当前维度缺失。
- `direction`：变化超过 `1e-9` 判断涨跌，否则持平；任一侧缺失时为 `unknown`。
