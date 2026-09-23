# 数据模型：KPI 跨任务历史趋势

## 概览

本功能不新增数据库历史点表，不改变任务 ID 生成规则。设备 ID 是任务元数据；历史点是任务输出内索引记录；API 响应是查询期投影。

## 1. 设备标识 / DeviceIdentity

### 存储

| 位置 | 字段/结构 | 说明 |
| --- | --- | --- |
| SQLite `tasks` | `customer["device_id"]` | 在线任务元数据兜底。 |
| `output/<task_id>/system.json` | `customer["device_id"]` | 任务结果唯一数据源。 |
| `output/<task_id>/task.json` | `system.customer["device_id"]` | 任务摘要引用。 |
| API `TaskSummary` | `device_id: string \| null` | 由上述来源派生，便于列表和详情展示。 |

### 校验

- 可选字段；未填写或空字符串表示无设备归属。
- 保存前去除首尾空格。
- 非空时长度为 1–128。
- 允许 Unicode；不使用设备 ID 拼接路径。
- admin 修改时，pending/running 任务返回 `task_busy`。

### 状态与匹配

- `device_id` 为空：任务正常巡检，但不参与跨任务匹配。
- 当前任务 `device_id` 为空：历史趋势降级为单任务趋势。
- 修改设备 ID 后，后续历史查询立即按新值匹配；历史索引不保存设备 ID。

## 2. KPI 历史点索引记录 / KpiHistoryIndexRecord

### 文件

`output/<task_id>/kpi/history/index.jsonl`

- UTF-8、LF。
- 每行一个 JSON 对象。
- 使用临时文件 + `rename` 原子写入。
- `schema_version` 当前为 `1`。
- 删除任务时随 `output/<task_id>/` 删除。

### 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | integer | 是 | 当前固定 `1`。 |
| `task_id` | string | 是 | 来源任务 ID。 |
| `measurement_unit_id` | string | 是 | 测量单元资源 ID，如 `MU_*`。 |
| `metric_resource_id` | string | 是 | 指标资源 ID，如 `ME_*`。 |
| `object_key` | string | 是 | 行对象；无行对象时使用 `__all__`。 |
| `period_minutes` | integer \| null | 是 | 周期分钟数；无法识别时为 `null`，只能与同为 `null` 的记录匹配。 |
| `measured_at` | string | 是 | UTC ISO-8601 时间。 |
| `value` | number | 是 | 去重后的数值。 |
| `source_file` | string | 是 | 相对任务解压目录的来源文件路径。 |
| `line_number` | integer \| null | 否 | 来源行号。 |

### 生成规则

- 数据来自当前任务 KPI 测量单元巡检的时间序列。
- 只索引原始绑定指标的有效数值；解析失败、空值不入索引。
- 同一任务内同对象、同周期、同时间的重复点沿用现有规则求均值。
- 同一来源文件的列缺失不生成点。
- 索引不保存 `device_id`，避免设备 ID 修改时重写全部索引。

## 3. 历史查询投影 / MeasurementHistoryTrend

API 不直接返回索引文件结构，而是返回单个指标、单个对象、单个周期的投影。

### 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 当前任务 ID。 |
| `rule_code` | string | 当前规则代码，本期为 `kpi.measurement_units`。 |
| `measurement_unit_id` | string | 测量单元 ID。 |
| `metric_resource_id` | string | 指标 ID。 |
| `device_id` | string \| null | 当前任务设备 ID。 |
| `object_key` | string | 查询行对象。 |
| `period_minutes` | integer \| null | 查询周期。 |
| `window` | `HistoryWindow` | 最近 7 个自然日窗口。 |
| `match` | `HistoryMatchStatus` | 可用性和降级原因。 |
| `coverage` | `HistoryCoverage` | 历史/当前覆盖摘要。 |
| `current_points` | `HistoryPoint[]` | 当前任务窗口内点。 |
| `history_series` | `HistoryDateSeries[]` | 历史任务按日期分组曲线。 |
| `baseline_points` | `HistoryBaselinePoint[]` | 按 `HH:mm` 的基线与偏差。 |
| `source_tasks` | `HistoryTaskSource[]` | 参与计算的历史任务摘要。 |

### HistoryWindow

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `end_date` | string(`YYYY-MM-DD`) | 当前任务最新 KPI 测量时间所在 UTC 自然日。 |
| `start_date` | string(`YYYY-MM-DD`) | `end_date - 6` 天。 |
| `days` | integer | 固定 `7`。 |
| `anchor_measured_at` | string | 当前任务最新有效 KPI 测量时间。 |

### HistoryMatchStatus

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | enum | `matched`、`no_history`、`degraded`。 |
| `reason_code` | string \| null | 降级原因；`matched` 时为 `null`。 |
| `message` | string | 中文解释。 |

降级原因包括但不限于：

- `device_id_missing`
- `current_measurement_time_missing`
- `history_index_missing`
- `period_mismatch`
- `metric_not_supported`
- `insufficient_samples`

### HistoryCoverage

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `history_task_count` | integer | 参与历史计算的任务数。 |
| `history_date_count` | integer | 有历史点的日期数。 |
| `history_point_count` | integer | 冲突去重后的历史点数。 |
| `current_point_count` | integer | 当前任务窗口内点数。 |
| `latest_history_date` | string \| null | 最新历史日期。 |

### HistoryPoint

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `measured_at` | string | UTC 时间。 |
| `date` | string | UTC 自然日。 |
| `time_label` | string | `HH:mm`。 |
| `value` | number | 指标值。 |
| `task_id` | string | 来源任务 ID。 |
| `source_file` | string | 来源文件。 |
| `line_number` | integer \| null | 来源行号。 |

### HistoryDateSeries

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string | UTC 自然日。 |
| `source_task_ids` | string[] | 去重后的来源任务 ID；一天内可来自多个任务，但同一时间点已去重。 |
| `points` | `HistoryPoint[]` | 按时间升序排列。 |

### HistoryBaselinePoint

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `time_label` | string | `HH:mm`。 |
| `baseline_value` | number \| null | 历史中位数。 |
| `current_value` | number \| null | 当前任务同 `HH:mm` 的最新值。 |
| `deviation` | number \| null | `current_value - baseline_value`。 |
| `deviation_ratio` | number \| null | `deviation / abs(baseline_value)`；基线为 0 时为 `null`。 |
| `sample_count` | integer | 历史样本数。 |
| `date_count` | integer | 覆盖历史日期数。 |
| `significance` | enum | `insufficient`、`normal`、`higher`、`lower`。 |

## 4. 任务关系

```text
TaskRecord / task.json
  └── device_id
        ↓ 查询期匹配
output/<task_id>/kpi/history/index.jsonl
  ├── measurement_unit_id
  ├── metric_resource_id
  ├── object_key
  ├── period_minutes
  └── measured_at / value / source
```

不建立任务之间的持久化关系。每次历史查询都根据当前任务元数据和索引动态匹配。

## 5. 一致性规则

- 当前任务 `device_id` 修改后，不需要修改索引；下一次查询使用新设备 ID。
- 任务重跑后重建 `index.jsonl`；索引中 `task_id` 必须等于所在任务目录的 `task_id`。
- 任务删除后，SQLite 记录、`uploads/<task_id>/`、`output/<task_id>/` 和索引一起消失。
- 历史候选必须是 `status=completed`；pending、running、failed、error 数据不参与。
- 查询响应中的时间字段统一 UTC；前端只负责展示。
- 重复查询同一组任务和同一参数时，响应除运行时间类字段外必须稳定一致。
