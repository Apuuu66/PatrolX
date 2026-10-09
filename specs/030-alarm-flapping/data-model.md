# 阶段 1 数据模型：告警生命周期与闪断检测

**功能**：030-alarm-flapping ｜ **日期**：2026-10-09 ｜ **上游**：[research.md](research.md)

本文件定义规则内部实体、字段、校验规则与状态迁移。所有实体都不是新的公开 API 模型：`AlarmRecord` / `AlarmGroup` / `FlapEvent` 只存在于规则实现内部，对外只通过既有 `RuleResult.metrics`、`RuleResult.findings`、`RuleResult.metadata` 暴露（契约见 [contracts/alarm-flapping-result.md](contracts/alarm-flapping-result.md)）。

## 1. 实体总览

```text
AlarmFile ──(1..n)──▶ AlarmRecord ──(group by alarm_code + object)──▶ AlarmGroup
                                                                          │
                                                          (ordered by created_at)
                                                                          ▼
                                                                     FlapEvent

FlappingPolicy ── 提供给 ──▶ AlarmGroup 的全部判定计算
CoverageWindow ── 提供给 ──▶ AlarmGroup 的观察窗与稳定判定
OperationWindow ── 提供给 ──▶ AlarmGroup 的窗口内/外证据标注
```

## 2. AlarmRecord（告警记录，内部）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `alarm_id` | `str` | 否 | 去重键组成部分；缺失时以空串参与去重键 |
| `created_at` | `datetime`（带偏移） | 是 | 出现时间；无时区输入按 `ASSUMED_LOCAL_TZ` 解释 |
| `cleared_at` | `datetime`（带偏移） | 否 | 清除时间；缺失表示未清除 |
| `alarm_code` | `str` | 是 | 告警码，参与分组键 |
| `object` | `str` | 否 | 对象名，参与分组键；空值归入空键分组 |
| `severity` | `str` | 否 | 原样保留用于展示，不参与判定 |
| `status` | `str` | 否 | 人工状态字段；**只展示、绝不作为恢复证据**（FR-011） |
| `description` | `str` | 否 | 描述原文 |
| `source_file` | `str` | 是 | 任务内 POSIX 相对路径，用于 Finding 溯源 |
| `line_no` | `int` | 是 | 文件内行号（含表头偏移），用于 Finding 溯源 |
| `source_format` | `str` | 是 | `csv` 或 `text`；文本行没有清除时间，按未清除处理 |

**校验规则**

- `created_at` 必须可解析且非空，否则整行排除，`excluded_rows` +1。
- `cleared_at` 若存在必须可解析且 `>= created_at`；否则整行排除，`excluded_rows` +1（时钟倒挂、非法清除时间）。
- 去重发生在解析后、分组前，键为 `alarm_id + created_at + alarm_code + object` 四元组；重复行 `duplicate_rows` +1 且不进入任何下游统计。
- 无法解析的字段名不视为错误；缺失 `alarm_code` 的行计入 `excluded_rows` 并在日志中给出原因（不静默丢弃）。

## 3. CoverageWindow（数据覆盖窗口，内部）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `start_at` | `datetime` | 全部有效记录 `min(created_at)` |
| `end_at` | `datetime` | 全部有效记录中「已清除记录取 `cleared_at`、未清除记录取 `created_at`」的最大值 |
| `span_sec` | `int` | `end_at - start_at` 的秒数 |
| `observation_gap_reference` | `str` | 固定 `last_fact`：分组观察窗以该组最晚清除/出现为参照（CR-005 保守口径） |

- 覆盖窗口为空（无有效记录）时规则返回 `skip`。
- `end_at` 的定义保证"最后一条告警被清掉之后还剩多少可观测时间"可被计算，而不是被未清除记录的出现时间拉长（[research.md](research.md) R2）。

## 4. FlappingPolicy（判定策略）

| 字段 | 默认值 | 对应参数键 | 说明 |
| --- | --- | --- | --- |
| `short_alarm_sec` | 300 | `short_alarm_sec` | 单次持续 ≤ 此值算短告警 |
| `repeat_window_sec` | 3600 | `repeat_window_sec` | 复发滑动窗口长度 |
| `min_repeat_count` | 3 | `min_repeat_count` | 窗口内判反复的最小出现次数 |
| `flap_gap_sec` | 1800 | `flap_gap_sec` | 前次清除到下次出现 ≤ 此值并入同一闪断事件 |
| `stable_observation_sec` | 1800 | `stable_observation_sec` | 判定稳定恢复所需的最短观察时长 |
| `operation_window` | `00:00-02:00` | `operation_window` | 本地时间操作窗 |
| `operation_window_enabled` | `true` | `operation_window_enabled` | 是否标注操作窗证据 |

**校验规则**

- 全部时长/次数必须为正整数；`min_repeat_count >= 2`。
- 参数只影响判定结果、不改变 `rule_version`（FR-018）；`rule_version` 仅在判定逻辑变化时递增。
- 参数变更通过修改规则参数表后单规则重跑生效，本版不引入站点级覆盖或运行时配置面（[research.md](research.md) R6）。

## 5. FlapEvent（闪断事件，内部）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `started_at` | `datetime` | 事件内第一次出现时间 |
| `last_seen_at` | `datetime` | 事件内最后一次出现时间 |
| `ended_at` | `datetime \| None` | 事件内最后一次清除时间；`None` 表示事件未结束 |
| `occurrences` | `int` | 事件内出现次数 |
| `duration_sec` | `int \| None` | 事件覆盖的总时长（首现 → 末次清除）；未结束为 `None` |
| `gaps_sec` | `list[int]` | 事件内相邻"清除 → 再现"间隔，用于 Finding 证据 |
| `is_flap` | `bool` | 事件出现次数 ≥ 2 且（事件未结束/含未清除记录，或至少一次"清除 → 再现"间隔 ≤ `flap_gap_sec`） |

同一事件内若前一条记录**未清除**，后续出现一律并入该事件（原事件尚未恢复），不再重复应用间隔阈值。

## 6. AlarmGroup（告警分组，内部 + 对外明细）

| 字段 | 类型 | 计算规则 |
| --- | --- | --- |
| `alarm_code` | `str` | 分组键（缺失已在记录级排除） |
| `object` | `str` | 分组键；空值为"对象未知" |
| `state` | `enum` | 见 §7 状态机 |
| `occurrence_count` | `int` | 去重后记录数 |
| `cleared_count` | `int` | `cleared_at` 非空的记录数 |
| `uncleared_count` | `int` | `cleared_at` 为空的记录数 |
| `first_seen_at` | `datetime` | 最早出现时间 |
| `recent_seen_at` | `datetime` | 最晚出现时间 |
| `recent_cleared_at` | `datetime \| None` | 最晚一次清除时间；无已清除记录为 `None`；Finding 的"最近清除时间"证据来源 |
| `max_duration_sec` | `int` | 已清除记录 `cleared_at - created_at` 的最大值 |
| `total_duration_sec` | `int` | 全部已清除记录持续时长之和 |
| `min_repeat_gap_sec` | `int \| None` | 相邻"清除 → 再现"间隔的最小值 |
| `repeated` | `bool` | 见 [research.md](research.md) R4 |
| `is_short` | `bool` | 全部已清除且 `max_duration_sec <= short_alarm_sec` |
| `observation_insufficient` | `bool` | `uncleared_count > 0` 或 `observation_gap_sec < stable_observation_sec`；即「分组最后一条事实（最晚清除/出现）距 `coverage_end` 不足稳定观察窗」（CR-005 保守口径） |
| `observation_gap_sec` | `int \| None` | `coverage_end - 分组最晚一次清除时间`；无已清除记录为 `None` |
| `in_window_occurrences` | `int` | 出现时间落在所在自然日操作窗内的记录数 |
| `out_of_window_occurrences` | `int` | 出现时间落在所在自然日操作窗外的记录数 |
| `out_of_window_reappear` | `bool` | 存在窗口内出现记录，且其后窗口外仍有出现 |
| `unrecovered_after_window` | `bool` | 存在窗口内出现记录，且当日操作窗结束后仍有未清除记录 |
| `flap_event_count` | `int` | `is_flap` 为真的事件数 |
| `flap_events` | `FlapEvent[]` | 按 `flap_gap_sec` 串联后出现次数 ≥ 2 的事件；单发事件不在对外明细中展开 |
| `evidence_records` | `RecordRef[]` | 该分组命中的来源引用（文件 + 行号），供 Finding 与明细溯源 |

**截图例外**：`state` 为 `cleared_stable` 的分组仍会输出明细（计数与时间点），但不出 Finding；这与"不产生 Finding"不矛盾（SC-003）。

## 7. 状态机

```text
                    ┌─ 存在未清除记录 ──▶ repeated ? ─┬─ 是 ─▶ uncleared_repeated
规则执行 ──▶ 分组 ──┤                                  └─ 否 ─▶ uncleared_single
                    └─ 全部已清除 ─────▶ repeated ? ─┬─ 是 ─▶ cleared_repeated
                                                     └─ 否 ─▶ is_short ?
                                                              ├─ 是 ─▶ cleared_short
                                                              └─ 否 ─▶ 观察窗不足 ?
                                                                       ├─ 是 ─▶ observation_insufficient
                                                                       └─ 否 ─▶ cleared_stable
```

- `repeated` 定义：存在长度 ≤ `repeat_window_sec` 的窗口包含 ≥ `min_repeat_count` 次出现（FR-008）。
- `is_short` 判定先于观察窗：全部已清除且最长单次持续 ≤ `short_alarm_sec` 即为 `cleared_short`，不论观察窗是否充足；观察窗不足只作为独立标记保留（因此 `cleared_short` 的 `observation_insufficient` 可能为 true）。
- `uncleared_repeated` 与 `uncleared_single` **一定**携带 `observation_insufficient = true`（未恢复本来就没有观察窗），这属于事实描述而非降级。
- `out_of_window_reappear` 仅在「存在窗口内出现记录 且 窗口外仍有出现」时为 true；`unrecovered_after_window` 仅在「存在窗口内出现记录 且 窗口结束时仍有未清除记录」时为 true。
- 状态互斥且优先级固定，不出现"既是短告警又是闪断"的双主状态：反复优先于短告警。

## 8. 规则结果映射

| 规则状态 | 触发条件 |
| --- | --- |
| `skip` | 无匹配告警文件；或全部记录时间不可解析（`excluded_rows == total_rows`） |
| `fail` | 存在 `uncleared_repeated` 或 `cleared_repeated` 分组 |
| `warn` | 无 fail 时，存在 `cleared_short`、`uncleared_single` 或 `observation_insufficient` 分组 |
| `pass` | 其余（含全部 `cleared_stable`、存在文件但仅有重复行） |

Finding 输出顺序：`uncleared_repeated` → `cleared_repeated` → `cleared_short`，同状态按 `recent_seen_at` 倒序；最多 20 条，截断信息写入元数据。

## 9. 指标契约

| 指标键 | 标签 | 单位 | 说明 |
| --- | --- | --- | --- |
| `alarm_groups` | 告警分组数 | 个 | 去重后有效分组数 |
| `flapping_groups` | 闪断分组数 | 个 | `cleared_repeated` + `uncleared_repeated` |
| `uncleared_repeated_groups` | 未清除反复分组数 | 个 | 最高风险分组 |
| `short_alarm_groups` | 短告警分组数 | 个 | `cleared_short` |
| `stable_groups` | 稳定分组数 | 个 | `cleared_stable` |
| `observation_insufficient_groups` | 观察窗不足分组数 | 个 | 携带标记的分组数 |
| `out_of_window_groups` | 窗口外再现分组数 | 个 | `out_of_window_reappear == true` |
| `unrecovered_after_window_groups` | 窗口后仍未恢复分组数 | 个 | `unrecovered_after_window == true` |
| `excluded_rows` | 被排除行数 | 行 | 时间不可解析 / 时钟倒挂 / 关键字段缺失 |
| `duplicate_rows` | 重复行数 | 行 | 去重键命中的行 |
| `failed_files` | 解析失败文件数 | 个 | 单文件级失败，不影响其他文件 |

## 10. 与既有模型的兼容性

- 不新增 Pydantic 模型、不改 `RuleResult` / `Metric` / `Finding` 字段语义；`metadata` 内新增命名空间 `alarm_flapping`。
- `alarm.stat` 的模型、字段与 `rule_version` 完全不动（FR-003）。
- 元数据结构为**只读展示契约**，由前端与报告消费；后续若需要跨包闪断历史，必须新建规则/服务，不得扩展本元数据的既有字段含义（宪法"契约驱动"）。
