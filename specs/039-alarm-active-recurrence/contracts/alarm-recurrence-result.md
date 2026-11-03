# 规则结果契约：alarm.recurrence

**规则代码**：`alarm.recurrence`  
**分类/优先级/版本**：`alarm` / `P1` / `1.0.0`  
**扫描组**：`alarm_all` → `^alarm/[^/]+\.csv$`  
**公共契约**：继续使用既有 `RuleResult`；本文件只定义 `metadata.alarm_recurrence`。

## 1. 规则身份

| 字段 | 值 |
| --- | --- |
| `name` | 告警反复上报巡检 |
| `category` | `alarm` |
| `priority` | `P1` |
| `severity` | `medium` |
| `rule_version` | `1.0.0` |

规则状态：

- 存在未清除记录，且该类型命中 `repeat_reporting` 或 `rapid_recurrence` → `fail`
- 其它存在反复、短告警或 `Reset Cleared` 证据的情况 → `warn`
- 有有效记录、无风险证据且无质量降级 → `pass`
- 无匹配文件或没有可分析记录 → `skip`
- 失败文件、预算降级或影响判定的质量缺陷且无更高状态 → 至少 `warn`

## 2. 声明指标

以下 metrics 在 `pass/warn/fail` 时必须完整输出，键、顺序和单位固定：

| key | label | unit |
| --- | --- | --- |
| `matched_files` | 匹配告警文件数 | 个 |
| `valid_lifecycles` | 有效告警生命周期数 | 条 |
| `alarm_types` | 告警类型数 | 种 |
| `multi_lifecycle_types` | 多次发生告警类型数 | 种 |
| `repeat_reporting_types` | 重复上报告警类型数 | 种 |
| `short_alarm_types` | 短告警类型数 | 种 |
| `rapid_recurrence_types` | 快速复发告警类型数 | 种 |
| `reset_cleared_lifecycles` | 重置清除生命周期数 | 条 |
| `repeat_positive_lifecycles` | Repeat Times 大于 0 生命周期数 | 条 |
| `raw_repeat_times_total` | 原始重复次数合计 | 次 |
| `estimated_reports_total` | 估算上报总数 | 次 |

`skip` 时 metrics 可以为空；如果已解析出部分有效记录但被质量/预算规则升级为 `warn`，仍必须输出完整 metrics。

## 3. metadata.alarm_recurrence

```json
{
  "schema_version": 1,
  "scope": {
    "source_patterns": ["^alarm/[^/]+\\.csv$"],
    "direct_alarm_csv_only": true,
    "operation_log_used": false,
    "cross_task_data_used": false,
    "stable_recovery_inferred": false
  },
  "parameters": {
    "short_alarm_sec": 300,
    "rapid_recurrence_window_sec": 3600,
    "rapid_recurrence_min_count": 3,
    "parameter_source": "default"
  },
  "coverage": {
    "start_at": "2026-09-01T02:00:01+00:00",
    "end_at": "2026-09-01T02:31:05+00:00",
    "span_sec": 1864,
    "end_basis": "max_valid_alarm_timestamp",
    "timezone_policy": "naive_as_utc+08:00_then_utc",
    "observation_note": "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻"
  },
  "totals": {
    "source_files": 2,
    "failed_files": 0,
    "raw_rows": 27,
    "valid_records": 24,
    "excluded_records": 2,
    "duplicate_records": 1,
    "alarm_types": 3,
    "multi_lifecycle_types": 2,
    "repeat_reporting_types": 2,
    "short_alarm_types": 1,
    "rapid_recurrence_types": 1,
    "reset_cleared_records": 1,
    "repeat_positive_records": 5,
    "repeat_totals_complete": true,
    "estimated_report_totals_complete": true,
    "types_truncated": false,
    "details_truncated": false,
    "findings_truncated": false
  },
  "status_counts": {
    "Not Cleared": 5,
    "Normal Cleared": 18,
    "Reset Cleared": 1,
    "Unknown": 0
  },
  "severity_counts": {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 1,
    "UNKNOWN": 0
  },
  "types": [
    {
      "type_key": "d3f...",
      "app_name": "CSP核心服务",
      "alarm_id": "1001",
      "alarm_name": "数据库连接池耗尽",
      "lifecycle_count": 3,
      "not_cleared_count": 1,
      "raw_repeat_times_total": 7,
      "max_single_repeat_times": 5,
      "estimated_report_total": 10,
      "repeat_totals_complete": true,
      "first_raised_at": "2026-09-01T02:00:01+00:00",
      "last_raised_at": "2026-09-01T02:20:01+00:00",
      "max_duration_sec": 1864,
      "min_adjacent_gap_sec": 900,
      "status_counts": {
        "Not Cleared": 1,
        "Normal Cleared": 2,
        "Reset Cleared": 0,
        "Unknown": 0
      },
      "severity_counts": {
        "CRITICAL": 2,
        "HIGH": 1,
        "MEDIUM": 0,
        "LOW": 0,
        "UNKNOWN": 0
      },
      "flags": {
        "multi_lifecycle": true,
        "repeat_reporting": true,
        "short_alarm": false,
        "rapid_recurrence": true,
        "reset_cleared": false
      },
      "object_count": 2,
      "objects": [
        {
          "object": "pod-umf-1",
          "lifecycle_count": 2,
          "not_cleared_count": 1,
          "raw_repeat_times_total": 6,
          "max_single_repeat_times": 5,
          "estimated_report_total": 8,
          "repeat_totals_complete": true,
          "first_raised_at": "2026-09-01T02:00:01+00:00",
          "last_raised_at": "2026-09-01T02:15:01+00:00",
          "max_duration_sec": 1864,
          "min_adjacent_gap_sec": 900,
          "status_counts": {
            "Not Cleared": 1,
            "Normal Cleared": 1,
            "Reset Cleared": 0,
            "Unknown": 0
          },
          "severity_counts": {
            "CRITICAL": 2,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "UNKNOWN": 0
          },
          "flags": {
            "multi_lifecycle": true,
            "repeat_reporting": true,
            "short_alarm": false,
            "rapid_recurrence": true,
            "reset_cleared": false
          }
        }
      ],
      "objects_truncated": false,
      "source_refs": [
        {"source_file": "alarm/alarm_history_001.csv", "line_no": 2}
      ]
    }
  ],
  "quality": {
    "excluded_rows": 2,
    "invalid_status_rows": 1,
    "unknown_status_values": {"已恢复": 1},
    "unknown_severity_values": {"提示": 0},
    "unknown_headers": {"Custom Column": 1},
    "invalid_raised_time_rows": 1,
    "invalid_cleared_time_rows": 0,
    "missing_cleared_time_rows": 0,
    "cleared_before_raised_rows": 0,
    "invalid_repeat_times_rows": 0,
    "missing_repeat_times_rows": 0,
    "missing_app_name_rows": 0,
    "missing_alarm_id_rows": 0,
    "missing_alarm_name_rows": 0,
    "missing_object_rows": 1,
    "repeat_totals_complete": true,
    "estimated_report_totals_complete": true
  },
  "files": [
    {
      "source_file": "alarm/alarm_history_001.csv",
      "status": "matched",
      "rows": 20,
      "valid_rows": 19,
      "excluded_rows": 1,
      "duplicate_rows": 0,
      "error_code": null,
      "error_message": null
    }
  ],
  "notes": [
    "原始 Repeat Times 合计与估算上报总数是两个独立口径",
    "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
    "快速复发只陈述告警文件中的时间事实，不判断操作时间或计划内外",
    "Reset Cleared 不代表稳定恢复",
    "未根据观察窗末端之后没有记录推断恢复"
  ]
}
```

## 4. 类型、对象与标记约束

- `type_key = "alarm.recurrence:" + sha256(app_name + NUL + alarm_id)[:16]`，不得包含来源时间或运行标识。
- 类型键为 `App Name + Alarm ID`；对象只作为类型内的独立明细，不得从类型汇总中扣除。
- 类型和对象的 `status_counts` 必须始终包含四个状态键；`severity_counts` 必须始终包含五个严重级键。
- `flags` 必须始终包含五个布尔键：`multi_lifecycle`、`repeat_reporting`、`short_alarm`、`rapid_recurrence`、`reset_cleared`。
- `multi_lifecycle` 为 `lifecycle_count > 1`。
- `repeat_reporting` 为有效 `raw_repeat_times_total > 0`。
- `short_alarm` 为任一已清除生命周期满足 `0 <= duration_sec <= short_alarm_sec`。
- `rapid_recurrence` 为按 `raised_at` 排序后的任意时间窗内出现至少 `rapid_recurrence_min_count` 条生命周期；窗口跨度不超过 `rapid_recurrence_window_sec`。
- `reset_cleared` 为任一生命周期状态为 `Reset Cleared`。
- 已清除记录的持续时长由 `cleared_at - raised_at` 计算；未清除记录以 `coverage.end_at` 为终点。清除早于上报时该记录不贡献持续时长。
- 最短相邻间隔仅为排序后相邻 `raised_at` 差值；少于两条记录时为 `null`。
- 无效或缺失 `Repeat Times` 不猜 0：记录仍参与生命周期、状态、严重级、对象和风险标记，但对应重复汇总完整性为 `false`。

## 5. 排序与 Finding

类型数组排序优先级：

1. 未清除且 `repeat_reporting` 或 `rapid_recurrence`
2. 未清除且存在其它风险标记
3. 已清除但存在 `multi_lifecycle`、`repeat_reporting`、`short_alarm` 或 `rapid_recurrence`
4. 仅 `reset_cleared` 或未知严重级等质量风险

同级按最高严重级、原始重复次数合计、生命周期次数降序，最后按 `type_key` 升序。对象明细使用相同严重级、重复次数、生命周期排序规则。

Finding：

- 只为存在风险的告警类型生成，不为无证据的普通类型制造 Finding。
- `finding_id = "alarm.recurrence:" + sha256(type_key 对应的业务键)[:16]`；同一输入重跑保持稳定。
- `source_file` 使用该类型首个可追溯来源；`evidence` 至少包含来源行号、应用、告警 ID/名称、生命周期数、原始重复合计、估算上报数、最长持续与命中标记。
- 未命中风险标记、也无未知严重级/质量问题的类型不生成 Finding。
- Finding 最多 100 条；超出时 `totals.findings_truncated=true`，`types` 与 metrics 仍保留完整汇总。

## 6. skip 与失败隔离

- 无匹配文件：`skip_reason="未发现 alarm/ 直属 CSV 告警文件"`。
- 文件均格式不适用：`skip_reason` 明确说明缺少必要表头。
- 文件存在但无有效生命周期：`skip_reason` 明确说明无可分析记录，并保留质量与文件摘要。
- 单文件损坏、编码失败或超预算：进入 `files`；其他文件继续解析，规则在无更高风险时至少 `warn`。
- 行/任务预算降级时不得继续无限读取；已解析记录仍用于完整可见范围的汇总，并明确记录预算原因。

## 7. 截断、隐私与兼容性

- `types`、每个类型的 `objects`、每个类型的 `source_refs` 各最多 100 条；截断只影响展示。
- 所有 metrics 和 `totals` 基于截断前完整有效数据。
- 不输出绝对路径、原始整行、堆栈或跨任务内容。
- 不读取 `alarm.flapping`、`alarm.stat` 结果，不使用 prepare，不修改公共 Schema/OpenAPI。
