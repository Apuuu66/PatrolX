# 契约：`alarm.flapping` 规则结果

**功能**：030-alarm-flapping ｜ **日期**：2026-10-09 ｜ **类型**：规则结果契约（内部展示边界，非 HTTP 接口）

本文件固化 030 的对外可观察结构：`RuleResult.metadata.alarm_flapping`、指标键与 Finding 文案要素。**本版不新增接口、不改 `docs/api/openapi.yaml`、不改 `RuleResult` / `Metric` / `Finding` 字段语义**；如果实现阶段确实需要新增对外字段，必须先更新 OpenAPI 再实现（宪法"契约驱动"）。

## 1. 规则元数据

```json
{
  "code": "alarm.flapping",
  "category": "alarm",
  "priority": "P1",
  "severity": "high",
  "rule_version": "1.0.0",
  "source_refs": ["alarm_all"],
  "limits": {
    "findings_max": 20,
    "groups_max": 500
  }
}
```

- `groups_max` 是明细截断上限；超过时元数据保留按状态优先级、`recent_seen_at` 排序后的前 N 个分组，并在 `truncated` 中标注真实总数。
- `rule_version` 初始 `1.0.0`；判定逻辑变化时递增，纯参数取值变化不递增。

## 2. `metadata.alarm_flapping` 结构

```json
{
  "alarm_flapping": {
    "schema_version": 1,
    "policy": {
      "short_alarm_sec": 300,
      "repeat_window_sec": 3600,
      "min_repeat_count": 3,
      "flap_gap_sec": 1800,
      "stable_observation_sec": 1800,
      "operation_window": "00:00-02:00",
      "operation_window_enabled": true,
      "parameter_source": "inspector_default"
    },
    "coverage": {
      "start_at": "2026-09-01T10:00:01+08:00",
      "end_at": "2026-09-02T12:05:30+08:00",
      "span_sec": 93929
    },
    "totals": {
      "rows": 22,
      "valid_rows": 22,
      "groups": 17,
      "excluded_rows": 0,
      "duplicate_rows": 0,
      "failed_files": 0,
      "findings_truncated": false,
      "groups_truncated": false
    },
    "state_counts": {
      "uncleared_repeated": 1,
      "uncleared_single": 8,
      "cleared_repeated": 1,
      "cleared_short": 1,
      "observation_insufficient": 1,
      "cleared_stable": 5
    },
    "groups": [
      {
        "alarm_code": "1051",
        "object": "pod-umf-9",
        "state": "uncleared_repeated",
        "occurrence_count": 3,
        "cleared_count": 0,
        "uncleared_count": 3,
        "first_seen_at": "2026-09-02T00:10:00+08:00",
        "recent_seen_at": "2026-09-02T01:00:00+08:00",
        "recent_cleared_at": null,
        "max_duration_sec": 0,
        "total_duration_sec": 0,
        "min_repeat_gap_sec": null,
        "repeated": true,
        "is_short": false,
        "observation_insufficient": true,
        "observation_gap_sec": null,
        "in_window_occurrences": 3,
        "out_of_window_occurrences": 0,
        "out_of_window_reappear": false,
        "unrecovered_after_window": true,
        "flap_event_count": 1,
        "flap_events": [
          {
            "started_at": "2026-09-02T00:10:00+08:00",
            "last_seen_at": "2026-09-02T01:00:00+08:00",
            "ended_at": null,
            "occurrences": 3,
            "duration_sec": null,
            "gaps_sec": [],
            "is_flap": true
          }
        ],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_003.csv",
            "line_no": 4
          }
        ]
      },
      {
        "alarm_code": "SCTP_LINK_DOWN",
        "object": "csp-node-01",
        "state": "uncleared_single",
        "occurrence_count": 1,
        "cleared_count": 0,
        "uncleared_count": 1,
        "first_seen_at": "2026-09-01T10:09:12+08:00",
        "recent_seen_at": "2026-09-01T10:09:12+08:00",
        "recent_cleared_at": null,
        "max_duration_sec": 0,
        "total_duration_sec": 0,
        "min_repeat_gap_sec": null,
        "repeated": false,
        "is_short": false,
        "observation_insufficient": true,
        "observation_gap_sec": null,
        "in_window_occurrences": 0,
        "out_of_window_occurrences": 1,
        "out_of_window_reappear": false,
        "unrecovered_after_window": false,
        "flap_event_count": 0,
        "flap_events": [],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_002.csv",
            "line_no": 2
          }
        ]
      },
      {
        "alarm_code": "1052",
        "object": "pod-umf-9",
        "state": "cleared_repeated",
        "occurrence_count": 3,
        "cleared_count": 3,
        "uncleared_count": 0,
        "first_seen_at": "2026-09-02T11:00:00+08:00",
        "recent_seen_at": "2026-09-02T11:50:00+08:00",
        "recent_cleared_at": "2026-09-02T12:00:00+08:00",
        "max_duration_sec": 600,
        "total_duration_sec": 1800,
        "min_repeat_gap_sec": 600,
        "repeated": true,
        "is_short": false,
        "observation_insufficient": true,
        "observation_gap_sec": 330,
        "in_window_occurrences": 0,
        "out_of_window_occurrences": 3,
        "out_of_window_reappear": false,
        "unrecovered_after_window": false,
        "flap_event_count": 1,
        "flap_events": [
          {
            "started_at": "2026-09-02T11:00:00+08:00",
            "last_seen_at": "2026-09-02T11:50:00+08:00",
            "ended_at": "2026-09-02T12:00:00+08:00",
            "occurrences": 3,
            "duration_sec": 3600,
            "gaps_sec": [
              1200,
              600
            ],
            "is_flap": true
          }
        ],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_003.csv",
            "line_no": 7
          }
        ]
      },
      {
        "alarm_code": "SCTP_LINK_DOWN",
        "object": "umf-node-01",
        "state": "cleared_short",
        "occurrence_count": 1,
        "cleared_count": 1,
        "uncleared_count": 0,
        "first_seen_at": "2026-09-01T10:00:04+08:00",
        "recent_seen_at": "2026-09-01T10:00:04+08:00",
        "recent_cleared_at": "2026-09-01T10:00:30+08:00",
        "max_duration_sec": 26,
        "total_duration_sec": 26,
        "min_repeat_gap_sec": null,
        "repeated": false,
        "is_short": true,
        "observation_insufficient": false,
        "observation_gap_sec": 93900,
        "in_window_occurrences": 0,
        "out_of_window_occurrences": 1,
        "out_of_window_reappear": false,
        "unrecovered_after_window": false,
        "flap_event_count": 0,
        "flap_events": [],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_001.csv",
            "line_no": 3
          }
        ]
      },
      {
        "alarm_code": "1053",
        "object": "pod-umf-9",
        "state": "observation_insufficient",
        "occurrence_count": 1,
        "cleared_count": 1,
        "uncleared_count": 0,
        "first_seen_at": "2026-09-02T12:00:00+08:00",
        "recent_seen_at": "2026-09-02T12:00:00+08:00",
        "recent_cleared_at": "2026-09-02T12:05:30+08:00",
        "max_duration_sec": 330,
        "total_duration_sec": 330,
        "min_repeat_gap_sec": null,
        "repeated": false,
        "is_short": false,
        "observation_insufficient": true,
        "observation_gap_sec": 0,
        "in_window_occurrences": 0,
        "out_of_window_occurrences": 1,
        "out_of_window_reappear": false,
        "unrecovered_after_window": false,
        "flap_event_count": 0,
        "flap_events": [],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_003.csv",
            "line_no": 10
          }
        ]
      },
      {
        "alarm_code": "CONTAINER_RESTART",
        "object": "pod-csp-1",
        "state": "cleared_stable",
        "occurrence_count": 1,
        "cleared_count": 1,
        "uncleared_count": 0,
        "first_seen_at": "2026-09-01T10:11:33+08:00",
        "recent_seen_at": "2026-09-01T10:11:33+08:00",
        "recent_cleared_at": "2026-09-01T10:24:10+08:00",
        "max_duration_sec": 757,
        "total_duration_sec": 757,
        "min_repeat_gap_sec": null,
        "repeated": false,
        "is_short": false,
        "observation_insufficient": false,
        "observation_gap_sec": 92480,
        "in_window_occurrences": 0,
        "out_of_window_occurrences": 1,
        "out_of_window_reappear": false,
        "unrecovered_after_window": false,
        "flap_event_count": 0,
        "flap_events": [],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_002.csv",
            "line_no": 3
          }
        ]
      },
      {
        "alarm_code": "1050",
        "object": "pod-umf-9",
        "state": "cleared_stable",
        "occurrence_count": 2,
        "cleared_count": 2,
        "uncleared_count": 0,
        "first_seen_at": "2026-09-02T00:30:00+08:00",
        "recent_seen_at": "2026-09-02T02:30:00+08:00",
        "recent_cleared_at": "2026-09-02T02:40:00+08:00",
        "max_duration_sec": 900,
        "total_duration_sec": 1500,
        "min_repeat_gap_sec": 6300,
        "repeated": false,
        "is_short": false,
        "observation_insufficient": false,
        "observation_gap_sec": 33930,
        "in_window_occurrences": 1,
        "out_of_window_occurrences": 1,
        "out_of_window_reappear": true,
        "unrecovered_after_window": false,
        "flap_event_count": 0,
        "flap_events": [],
        "evidence_records": [
          {
            "source_file": "alarm/alarm_history_202609010101137101_003.csv",
            "line_no": 2
          }
        ]
      }
    ],
    "notes": [
      "本块为文档节选：groups 只列出覆盖六种主状态的 7 个分组（7/17），state_counts 与 totals 为样例包全部 17 个分组的真实计数；真实运行时 groups 输出全部分组，groups_truncated 仅在分组数超过 groups_max 时为 true",
      "1052 于 11:00/11:30/11:50 三次出现、三次清除（600 秒 / 600 秒 / 600 秒），11:50 的出现到 12:00 的清除跨度 3000 秒 ≤ 3600 秒，故 repeated=true；最后一次清除距覆盖末端仅 330 秒，故同时携带 observation_insufficient=true",
      "1053 于 12:00 出现、12:05:30 清除，持续 330 秒，观察窗为 0 秒，演示主状态=观察窗不足",
      "1050 于 00:30 出现（窗口内）、02:30 再现（窗口外），演示 out_of_window_reappear；主状态由复发与观察窗算法独立决定，为已清除且稳定",
      "未清除分组（1051、SCTP_LINK_DOWN/csp-node-01）没有最近清除时间，recent_cleared_at、min_repeat_gap_sec、observation_gap_sec 均为 null"
    ]
  }
}
```

### 字段约束

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 整数，本版固定 `1`；破坏性调整必须升版本 |
| `policy.*` | 与 `Inspector.params` 默认值同源；键名稳定，单位后缀固定 `_sec` / `_count` 语义见 [data-model.md](../data-model.md) §4 |
| `state_counts` | 六个键必须全部出现（无分组时为 0） |
| `groups[].state` | 取值只能是 §3 六个枚举之一 |
| `groups[].flap_events` | 仅包含 `occurrences >= 2` 的事件；单发事件不展开 |
| `groups[].recent_cleared_at` | 该分组最晚一次清除时间；无已清除记录为 `null`（Finding 的"最近清除时间"证据来源） |
| `groups[].evidence_records` | 至少一条；`source_file` 为任务内 POSIX 相对路径 |
| 时间字段 | ISO-8601 带偏移；跨时区输入统一为同一偏移序列化 |
| 计数/时长 | 非负整数；`*_sec` 为整数秒；未知用 `null`，不得用 -1 表示 |
| `recent_cleared_at` / `min_repeat_gap_sec` / `observation_gap_sec` | 无已清除记录时为 `null`；`observation_gap_sec` 仅在存在已清除记录时取值 |

## 3. 状态枚举

| 值 | 中文标签 | 规则状态贡献 | Finding |
| --- | --- | --- | --- |
| `uncleared_repeated` | 未清除且反复 | fail | CRITICAL |
| `uncleared_single` | 未清除未反复 | warn | 无 |
| `cleared_repeated` | 已清除但反复 | fail | HIGH |
| `cleared_short` | 已清除但短告警 | warn | MEDIUM |
| `observation_insufficient` | 观察窗不足 | warn | 无 |
| `cleared_stable` | 已清除且稳定 | pass | 无 |

## 4. 指标键（`RuleResult.metrics[]`）

| key | label | unit |
| --- | --- | --- |
| `alarm_groups` | 告警分组数 | 个 |
| `flapping_groups` | 闪断分组数 | 个 |
| `uncleared_repeated_groups` | 未清除反复分组数 | 个 |
| `short_alarm_groups` | 短告警分组数 | 个 |
| `stable_groups` | 稳定分组数 | 个 |
| `observation_insufficient_groups` | 观察窗不足分组数 | 个 |
| `out_of_window_groups` | 窗口外再现分组数 | 个 |
| `unrecovered_after_window_groups` | 窗口后仍未恢复分组数 | 个 |
| `excluded_rows` | 被排除行数 | 行 |
| `duplicate_rows` | 重复行数 | 行 |
| `failed_files` | 解析失败文件数 | 个 |

## 5. Finding 文案要素

三条 Finding 均必须包含（FR-013）：

- 分组键：`alarm_code / object`（空对象显示"对象未知"）；
- 出现次数与已清除/未清除分布；
- 首次出现、最近出现、最近清除时间；
- 复发间隔（`min_repeat_gap_sec`）与触发窗口；
- 本次使用的阈值（短告警阈值、复发窗口与次数、闪断间隔、稳定观察窗）；
- 操作窗证据（窗口内/外出现次数、窗口外再现或窗口后仍未恢复标记，命中时才出现）；
- 来源文件与行号。

`finding_id` 命名：`alarm.flapping-{state}-{alarm_code}-{object}`，对 `object` 为空使用 `unknown` 占位，保证同一任务内唯一且稳定（幂等）。

## 6. `skip` 契约

| 场景 | 状态 | `skip_reason` 要求 |
| --- | --- | --- |
| 无匹配告警文件 | `skip` | 说明未匹配到 `alarm_all` 组文件 |
| 全部记录时间不可解析 | `skip` | 说明被排除行数与原因分类 |

`skip` 不得伪装为 `pass`；任务整体仍为成功（单规则跳过不影响任务状态）。

## 7. 兼容性声明

- 本契约只描述**新增**的元数据命名空间与新增指标键，不修改任何既有字段含义（宪法"契约驱动"）。
- `alarm.stat` 的输出（含 `severity_distribution`）保持零变化。
- 后续 031 设备时间轴若需要消费闪断结论，必须通过既有 `RuleResult` 读取或新建任务级服务，不得让其他普通规则直接消费本规则产物。
