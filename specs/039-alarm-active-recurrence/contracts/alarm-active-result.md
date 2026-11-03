# 规则结果契约：alarm.active_state

**规则代码**：`alarm.active_state`  
**分类/优先级/版本**：`alarm` / `P1` / `1.0.0`  
**扫描组**：`alarm_all` → `^alarm/[^/]+\.csv$`  
**公共契约**：继续使用既有 `RuleResult`；本文件只定义 `metadata.alarm_active`。

## 1. 规则身份

| 字段 | 值 |
| --- | --- |
| `name` | 未清除告警巡检 |
| `category` | `alarm` |
| `priority` | `P1` |
| `severity` | `high` |
| `rule_version` | `1.0.0` |

规则状态：

- 存在 `CRITICAL`/`HIGH` 活动记录 → `fail`
- 仅 `MEDIUM`/`LOW`/`UNKNOWN` 活动记录 → `warn`
- 无活动但存在有效记录且无质量降级 → `pass`
- 无匹配文件/无有效记录 → `skip`
- 失败文件、预算降级或影响判定的质量缺陷且无更高状态 → 至少 `warn`

## 2. 声明指标

在 `pass/warn/fail` 时 metrics 必须完整且键/单位完全一致：

| key | label | unit |
| --- | --- | --- |
| `active_alarm_records` | 活动告警记录数 | 个 |
| `active_alarm_groups` | 活动告警分组数 | 个 |
| `critical_active` | 紧急活动告警数 | 个 |
| `high_active` | 严重活动告警数 | 个 |
| `medium_active` | 重要活动告警数 | 个 |
| `low_active` | 次要活动告警数 | 个 |
| `unknown_active` | 未知严重级活动告警数 | 个 |
| `active_repeat_times_total` | 活动原始重复次数合计 | 次 |
| `max_single_repeat_times` | 单条最大原始重复次数 | 次 |
| `active_estimated_reports_total` | 活动估算上报总数 | 次 |

## 3. metadata.alarm_active

```json
{
  "schema_version": 1,
  "scope": {
    "source_patterns": ["^alarm/[^/]+\\.csv$"],
    "direct_alarm_csv_only": true,
    "operation_log_used": false,
    "cross_task_data_used": false
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
    "failed_files": 1,
    "raw_rows": 27,
    "valid_records": 24,
    "excluded_records": 2,
    "duplicate_records": 1,
    "active_records": 5,
    "active_groups": 4,
    "repeat_totals_complete": true,
    "estimated_report_totals_complete": true,
    "details_truncated": false,
    "findings_truncated": false
  },
  "status_counts": {
    "Not Cleared": 5,
    "Normal Cleared": 18,
    "Reset Cleared": 1,
    "Unknown": 0
  },
  "active_severity_counts": {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 1,
    "LOW": 1,
    "UNKNOWN": 0
  },
  "active_summary": {
    "highest_severity": "CRITICAL",
    "raw_repeat_times_total": 9,
    "max_single_repeat_times": 5,
    "estimated_report_total": 14,
    "estimated_total_is_estimate": true
  },
  "groups": [
    {
      "group_key": "a3f...",
      "app_name": "CSP核心服务",
      "alarm_id": "1001",
      "alarm_name": "数据库连接池耗尽",
      "object": "paas-192.168.2.2",
      "severity": "CRITICAL",
      "first_raised_at": "2026-09-01T02:00:01+00:00",
      "last_raised_at": "2026-09-01T02:00:01+00:00",
      "duration_sec": 1864,
      "lifecycle_count": 1,
      "raw_repeat_times_total": 5,
      "max_single_repeat_times": 5,
      "estimated_report_total": 6,
      "repeat_totals_complete": true,
      "source_refs": [{"source_file": "alarm/alarm_history_001.csv", "line_no": 2}]
    }
  ],
  "records": [
    {
      "app_name": "CSP核心服务",
      "alarm_id": "1001",
      "alarm_name": "数据库连接池耗尽",
      "object": "paas-192.168.2.2",
      "severity": "CRITICAL",
      "state": "Not Cleared",
      "raised_at": "2026-09-01T02:00:01+00:00",
      "cleared_at": null,
      "duration_sec": 1864,
      "repeat_times": 5,
      "estimated_report_count": 6,
      "source_file": "alarm/alarm_history_001.csv",
      "line_no": 2
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
    "活动状态唯一判据为 Whether Cleared=Not Cleared",
    "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
    "Reset Cleared 不代表稳定恢复"
  ]
}
```

## 4. 排序与 Finding

- `groups`：严重级 rank 升序 → `raw_repeat_times_total` 降序 → `duration_sec` 降序 → `group_key` 升序。
- `records`：severity rank → `repeat_times` 降序 → `duration_sec` 降序 → source file/line 升序。
- 每个活动 group 一个 Finding；Finding `severity` 映射：CRITICAL→critical、HIGH→high、MEDIUM→medium、LOW→low、UNKNOWN→medium。
- `finding_id = "alarm.active_state:" + sha256(group_key)[:16]`，稳定唯一。
- `source_file` 使用首个来源相对路径；`evidence` 包含 `line_no`、告警名、应用、对象、严重级、持续秒数、原始重复次数、估算上报次数。
- Finding 最多 100 条；`findings_truncated=true` 表示仍有活动 group 未生成 Finding，但 metrics/totals 仍完整。

## 5. skip 与失败隔离

- 无匹配文件：`skip_reason="未发现 alarm/ 直属 CSV 告警文件"`。
- 文件均缺少必要表头或无可分析记录：skip 原因区分 `告警 CSV 格式不适用` 与 `告警 CSV 无可分析记录`。
- 任一文件损坏/编码失败/预算超限：该文件进入 `files`，`failed_files` 增加；其它文件继续。
- 失败文件存在时，规则摘要必须包含失败文件数；没有更高风险时状态至少 `warn`。
- 所有错误信息只包含任务内相对路径，不输出绝对路径、原始行内容或堆栈。

## 6. 兼容性

- 不读取/写入 `alarm.flapping`、`alarm.stat`、`metadata.alarm_flapping`。
- 不使用 prepare，不读取其他规则结果。
- 不新增 API，不修改公共 Schema。
