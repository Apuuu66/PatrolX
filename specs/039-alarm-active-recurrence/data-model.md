# 数据模型：未清除告警与反复上报巡检

**日期**：2026-11-04 | **规格**：[spec.md](./spec.md) | **计划**：[plan.md](./plan.md)

本功能不新增数据库表、HTTP Schema 或 Mine 类型；以下为规则内部与 `RuleResult.metadata` 的数据模型。公共 `RuleResult`、`Metric`、`Finding` 仍按既有 Pydantic 模型输出。

## 1. 枚举与常量

### AlarmState

| 值 | 含义 | 是否活动 |
| --- | --- | --- |
| `Not Cleared` | 告警仍未清除 | 是 |
| `Normal Cleared` | 正常清除状态 | 否 |
| `Reset Cleared` | 清除状态被重置，不等于稳定恢复 | 否 |
| `Unknown` | 未命中映射；不得猜测 | 否，整行排除 |

### AlarmSeverity

| 值 | 排序 | 说明 |
| --- | --- | --- |
| `CRITICAL` | 0 | 紧急 |
| `HIGH` | 1 | 严重 |
| `MEDIUM` | 2 | 重要 |
| `LOW` | 3 | 次要 |
| `UNKNOWN` | 4 | 未知严重级，保留并审计 |

### AlarmFlag

`multi_lifecycle`、`repeat_reporting`、`short_alarm`、`rapid_recurrence`、`reset_cleared`。

### AlarmParameters

| 字段 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `short_alarm_sec` | integer | 300 | `> 0` |
| `rapid_recurrence_window_sec` | integer | 3600 | `> 0` |
| `rapid_recurrence_min_count` | integer | 3 | `>= 2` |

## 2. 内部实体

### AlarmRecord

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `app_name` | string | 是 | 缺失时稳定占位 `应用未识别` |
| `alarm_id` | string | 是 | 缺失时稳定占位 `告警ID未识别` |
| `alarm_name` | string | 是 | 缺失时稳定占位 `告警名称未识别` |
| `severity` | AlarmSeverity | 是 | 规范化严重级 |
| `state` | AlarmState | 是 | 仅已知状态进入有效记录 |
| `raised_at` | datetime(UTC) | 是 | Raised/Raised Time 解析结果 |
| `cleared_at` | datetime(UTC) \| null | 否 | 清除时间；缺失可为空 |
| `duration_sec` | integer \| null | 否 | 已清除为差值；未清除在规则层按 coverage_end 计算 |
| `repeat_times` | integer \| null | 否 | 非负整数；缺失/非法为 `null` |
| `object_key` | string | 是 | 归一化对象或 `对象未识别` |
| `serial_no` | string \| null | 否 | 原始告警流水号 |
| `source_file` | string | 是 | `alarm/<file>.csv` 相对路径 |
| `line_no` | integer | 是 | CSV 物理行号，数据首行为 2 |
| `location_info` | string \| null | 否 | 原始定位信息，仅用于对象解析与去重 |
| `additional_info` | string \| null | 否 | 原始附加信息，仅用于对象解析与去重 |

派生属性：

- `estimated_report_count = 1 + repeat_times`（`repeat_times != null`）
- `is_active = state == Not Cleared`

### AlarmCoverage

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `start_at` | datetime(UTC) \| null | 有效 Raised 最小值 |
| `end_at` | datetime(UTC) \| null | 全部有效 Raised/Cleared 最大值 |
| `span_sec` | integer | `end_at - start_at`，无覆盖时为 0 |
| `end_basis` | string | 固定 `max_valid_alarm_timestamp` |
| `observation_note` | string | 说明末刻不是任务执行时刻或真实恢复时刻 |
| `timezone_policy` | string | 无时区 UTC+8、带偏移转 UTC |

### AlarmQuality

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `excluded_rows` | integer | 无法形成有效记录的总行数 |
| `invalid_status_rows` | integer | 空白/未知状态行数 |
| `unknown_status_values` | map[string,int] | 原始未知状态计数 |
| `unknown_severity_values` | map[string,int] | 原始未知严重级计数 |
| `unknown_headers` | map[string,int] | 未命中映射的原始表头计数 |
| `invalid_raised_time_rows` | integer | Raised 时间不可解析行数 |
| `invalid_cleared_time_rows` | integer | 非空 Cleared 时间不可解析行数 |
| `missing_cleared_time_rows` | integer | 已清除但缺少清除时间的记录数 |
| `cleared_before_raised_rows` | integer | 清除早于发生，持续时长不可用 |
| `invalid_repeat_times_rows` | integer | 负数/非整数重复次数 |
| `missing_repeat_times_rows` | integer | 缺少重复次数 |
| `missing_app_name_rows` | integer | 使用应用占位 |
| `missing_alarm_id_rows` | integer | 使用告警 ID 占位 |
| `missing_alarm_name_rows` | integer | 使用告警名称占位 |
| `missing_object_rows` | integer | 使用对象占位 |
| `repeat_totals_complete` | boolean | 所有有效记录重复次数均有效 |
| `estimated_report_totals_complete` | boolean | 与重复次数完整性一致 |

### AlarmParseResult

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `records` | list[AlarmRecord] | 去重后的有效生命周期 |
| `coverage` | AlarmCoverage | 覆盖信息 |
| `quality` | AlarmQuality | 质量统计 |
| `files` | list[AlarmFileResult] | 每个匹配文件的处理结果 |
| `raw_rows` | integer | 数据行总数（不含表头） |
| `duplicate_rows` | integer | 完全重复记录数 |
| `budget_exceeded` | boolean | 是否遇到行/大小预算 |
| `budget_message` | string \| null | 降级原因 |

### AlarmFileResult

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_file` | string | 任务内相对路径 |
| `status` | `matched` / `failed` / `budget_exceeded` | 文件结果 |
| `rows` | integer | 数据行数 |
| `valid_rows` | integer | 解析并入候选的有效行 |
| `excluded_rows` | integer | 被排除行数 |
| `duplicate_rows` | integer | 去重行数 |
| `error_code` | string \| null | 稳定机器可读错误码 |
| `error_message` | string \| null | 中文说明，不含绝对路径 |

## 3. 活动告警结果

### ActiveAlarmRecordView

在 AlarmRecord 基础上增加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `duration_sec` | integer | 到 coverage_end 的持续秒数 |
| `estimated_report_count` | integer \| null | 估算上报次数 |
| `source_ref` | object | `{source_file, line_no}` |

### ActiveAlarmGroup

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `group_key` | string | 稳定哈希键，不包含时间 |
| `app_name` | string | 应用 |
| `alarm_id` | string | 告警 ID |
| `alarm_name` | string | 告警名称 |
| `object` | string | 归一化对象 |
| `severity` | AlarmSeverity | 组内最高严重级 |
| `first_raised_at` | datetime(UTC) | 组内最早发生 |
| `last_raised_at` | datetime(UTC) | 组内最近发生 |
| `duration_sec` | integer | 组内最长当前持续时长 |
| `lifecycle_count` | integer | 组内活动记录数 |
| `raw_repeat_times_total` | integer | 有效重复次数合计 |
| `max_single_repeat_times` | integer | 单条最大值 |
| `estimated_report_total` | integer | `Σ(1 + Repeat Times)`（仅有效值） |
| `repeat_totals_complete` | boolean | 组内重复次数是否完整 |
| `source_refs` | list[SourceRef] | 去重后来源 |

排序键：`severity_rank asc, raw_repeat_times_total desc, duration_sec desc, group_key asc`。

## 4. 反复上报结果

### AlarmTypeSummary

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type_key` | string | `App Name + Alarm ID` 稳定键 |
| `app_name` | string | 应用 |
| `alarm_id` | string | 告警 ID |
| `alarm_name` | string | 代表性告警名称 |
| `lifecycle_count` | integer | 类型全部对象生命周期数 |
| `not_cleared_count` | integer | 未清除生命周期数 |
| `raw_repeat_times_total` | integer | 有效原始重复合计 |
| `max_single_repeat_times` | integer | 单条最大原始重复 |
| `estimated_report_total` | integer | 估算上报总数 |
| `repeat_totals_complete` | boolean | 重复口径是否完整 |
| `first_raised_at` | datetime(UTC) | 最早发生 |
| `last_raised_at` | datetime(UTC) | 最近发生 |
| `max_duration_sec` | integer \| null | 最长有效持续；未清除计算到 coverage_end |
| `min_adjacent_gap_sec` | integer \| null | 排序后相邻 Raised 最小间隔 |
| `status_counts` | map[AlarmState,int] | 四个状态（有效记录中 Unknown 为 0） |
| `severity_counts` | map[AlarmSeverity,int] | 五个严重级 |
| `flags` | map[AlarmFlag,bool] | 五类证据标记 |
| `object_count` | integer | 对象明细总数 |
| `objects` | list[AlarmObjectSummary] | 最多 100 个对象 |
| `objects_truncated` | boolean | 对象明细是否截断 |
| `source_refs` | list[SourceRef] | 最多 100 个来源引用 |

### AlarmObjectSummary

与类型汇总额度相同，但键为单一对象；不包含嵌套 `objects`。`lifecycle_count` 为对象内生命周期数，`rapid_recurrence` 与 `short_alarm` 在对象级独立计算。

### 排序

Finding 风险顺序：

1. 未清除且 `repeat_reporting` 或 `rapid_recurrence`
2. 未清除且存在其它风险标记
3. 已清除但存在 `multi_lifecycle`、`repeat_reporting`、`short_alarm` 或 `rapid_recurrence`
4. 仅 `reset_cleared` 或未知严重级等质量风险

同级按严重级、原始重复合计、生命周期数降序，最后按 `type_key` 升序。

## 5. 状态与验证

| 条件 | active_state | recurrence |
| --- | --- | --- |
| 无匹配文件 | `skip` | `skip` |
| 文件全部不可解析/无有效记录 | `skip` | `skip` |
| Critical/HIGH 活动 | `fail` | 视标记 |
| 仅 MEDIUM/LOW/UNKNOWN 活动 | `warn` | 视标记 |
| 无活动且无质量降级 | `pass` | 依据反复标记 |
| 失败文件或质量降级且无更高风险 | 至少 `warn` | 至少 `warn` |

所有输出时间字段以 `_at` 结尾；状态/严重级 distribution 使用归一化键；未知原始值只出现在 quality map。

## 6. 截断与预算

- 32 MiB/文件：超限文件 `budget_exceeded`，继续处理其它文件。
- 100,000 行/文件、250,000 行/任务：达到上限即停止新增记录并设置 `budget_exceeded`。
- 每组记录、对象、来源引用最多展示 100 条；类型组最多展示 100 个，Finding 最多 100 条。
- `totals.details_truncated`、`totals.findings_truncated`、`objects_truncated` 必须说明截断。
- 所有汇总数字基于截断前完整有效数据。
