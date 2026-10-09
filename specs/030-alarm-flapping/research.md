# 阶段 0 研究：告警生命周期与闪断检测

**功能**：030-alarm-flapping ｜ **日期**：2026-10-09 ｜ **输入**：[spec.md](spec.md)

本阶段只解决 spec 中"属于实现方案"的开放项：规则实现形态、解析与分组、状态判定的算法规格、元数据与契约边界、参数声明方式、展示路径、样例包构造、性能与容错。所有结论已在下文定稿，进入阶段 1 设计。

## R1. 规则形态：新增自包含规则，不引入 prepare

- **决定**：新增 `app/inspectors/alarm/flapping.py`，注册 `alarm.flapping`（P1、告警类），声明 `source_refs: ["alarm_all"]`，`rule_version` 初始 `1.0.0`，`severity` 为 `HIGH`。不声明私有 prepare。
- **理由**：宪法与 AGENTS.md 要求规则只声明 `source_patterns`（或经扫描组解析的 `source_refs`）直读匹配文件；本规则与 `alarm.stat` 读取同一批告警文件、独立解析，无跨文件中间产物需求，prepare 只会增加缓存与生命周期复杂度（FR-002、FR-021）。
- **备选**：(a) 扩展 `alarm.stat` —— 被否，FR-003 要求保持其语义与 `rule_version` 不变；(b) 用 prepare 预聚合 —— 被否，规则私有 prepare 不能解决任何额外问题，且违反"prepare 只服务私有数据"的保守取向。

## R2. 数据覆盖窗口的定义

- **决定**：数据覆盖起止时间由**全部有效、去重后记录**推导：`coverage_start = min(created_time)`；`coverage_end` 取「已清除记录贡献 `cleared_time`、未清除记录贡献 `created_time`」的最大值。即未清除记录只贡献它的出现时间，已清除记录贡献它的清除时间。
- **理由**：包内没有独立的"数据覆盖声明"文件，观测窗口必须从事实自身推导；用"已清除时刻的最大值"才能表达"最后一条告警何时被清掉"，从而计算稳定观察窗（FR-010、FR-005）。
- **保守补充（CR-005）**：分组的观察窗以**该组最晚一次清除/出现**为参照，而不是只看"最后一次清除"：任一已清除记录距覆盖结束不足观察窗，或仍存在未清除记录，该分组都携带 `observation_insufficient`。在覆盖期内反复出现的分组若以首现为参照会得到"稳定"的错误结论，保守取最晚事实可避免假稳定（SC-001、SC-003）。FR-010 的"最后一次清除后观察窗充足"仍是判稳的必要条件之一，本补充只收紧、不放松。
- **备选**：把 `coverage_end` 取为所有告警的 `created_time` 最大值 —— 被否，会把"某条告警长时间未清除"误算进观测窗，制造虚假的稳定结论。

## R3. 解析、去重与分组

- **决定**：
  - CSV：`csv.DictReader` + 统一解码入口（UTF-8 → GB18030 兜底），字段名 `strip().lower()` 后匹配，容忍大小写与首尾空白（FR-019）。
  - 必填字段：`alarm_code`、`created_time`；可选字段：`cleared_time`、`severity`、`status`、`object`、`description`、`alarm_id`。
  - TXT 文本行沿用 `alarm.stat` 既有词法：`ALARM <日期> <时间> <code> ... <severity> <status>`，`object` 视为空；这类行没有清除时间，按未清除处理并在元数据中标注来源格式。
  - 排序键：`created_time, alarm_code, object, source_file, line_no`，保证跨文件合并结果确定（FR-017、幂等原则）。
  - 去重键：`alarm_id + created_time + alarm_code + object` 四项全同（Clarifications）；重复行计数进元数据，不参与任何统计。
  - 分组键：`(alarm_code, object)`；`object` 为空归入空键分组并在展示层显示"对象未知"（FR-004）。
  - 时间解析：`datetime.fromisoformat` 兼容 `Z` 后缀与 `+08:00`；无时区记录按"包内同一本地时区"解释（统一附加假定偏移量或使用 naive 统一比较），仅为相对时长/间隔服务（FR-017）。
  - 记录级排除：`created_time` 不可解析、`cleared_time` 存在但不可解析、`cleared_time < created_time`（时钟倒挂）的行计入 `excluded_rows`，不进入判定；单文件失败只计入 `failed_files` 并继续（FR-016）。
- **理由**：与既有 `alarm.stat` 的容错口径一致，避免同一份数据在两条规则下出现"一个能读、一个读不了"的差异；四项去重键是澄清阶段确认的最小可判定口径。
- **备选**：仅按 `alarm_id` 去重 —— 被否，真实导出中同一 `alarm_id` 可能在不同时间/对象下重复出现，会误删记录。

## R4. 闪断与状态判定算法

按分组在排序后的记录序列上**单次遍历**完成以下计算：

1. **窗口内复发（repeated，FR-008）**：以出现时间为轴做滑动窗口，若存在任意 `length = repeat_window_sec` 的窗口包含 ≥ `min_repeat_count` 次出现，则 `repeated = true`；同时记录触发窗口的起止时间与命中次数，作为 Finding 证据。
2. **闪断事件（FR-009）**：从第一次出现开始，若下一条出现的 `created_time` 距上一条清除时间的间隔 ≤ `flap_gap_sec`，则并入同一闪断事件（事件持续 = 事件内首次出现 → 最后一次清除）；若时间上一条**未清除**，后续出现一律并入同一事件（原事件尚未恢复）。间隔超过阈值则开启新事件。事件列表是"清除后是否真正恢复"的直接证据。
3. **单次持续时长（FR-007）**：`cleared_time - created_time`，对未清除记录记为待定；`is_short` = 全部记录已清除且最长单次持续 ≤ `short_alarm_sec`。
4. **观察窗（FR-010）**：`observation_gap_sec = coverage_end - 分组最晚一次清除时间`（无已清除记录时为 `null`）；`observation_insufficient` = 存在未清除记录 或 `observation_gap_sec < stable_observation_sec`。
5. **主状态（FR-006）**，互斥、优先级从高到低：

| 序号 | 状态值 | 判定条件 |
| --- | --- | --- |
| 1 | `uncleared_repeated` | 存在未清除记录 且 `repeated` |
| 2 | `uncleared_single` | 存在未清除记录 且 非 `repeated` |
| 3 | `cleared_repeated` | 全部已清除 且 `repeated` |
| 4 | `cleared_short` | 全部已清除 且 `is_short`（先于观察窗判定，不论观察窗是否充足） |
| 5 | `observation_insufficient` | 全部已清除、非反复、非短告警 且 观察窗不足 |
| 6 | `cleared_stable` | 全部已清除 且 观察窗充足（其余情况） |

- `observation_insufficient` 标记是**独立布尔值**，除稳定分支外的所有分组都携带（FR-006 后半句）；它不改变主状态。
- `out_of_window_reappear` 与 `unrecovered_after_window` 都以「存在窗口内出现记录」为前提：只有先命中操作窗、之后在窗口外再现或窗口结束时仍未恢复，才置为 true；纯窗口外的普通出现不触发这两个标记。
- **理由**：状态机把"未恢复"放在最高优先级，确保 `status=已处理` 但无清除时间的记录不会掩盖问题（FR-011）；观察窗充足才允许出现 `stable`，杜绝"刚清除就判稳"（SC-001、SC-003）。
- **备选**：用"最后一次出现 + 固定观察窗"代替覆盖结束时间 —— 被否，忽略了数据窗本身过短的场景。

## R5. Finding 与规则状态映射

- **决定**（沿用澄清结论）：

| 主状态 | Finding | 严重级 |
| --- | --- | --- |
| `uncleared_repeated` | 生成 | CRITICAL |
| `cleared_repeated` | 生成 | HIGH |
| `cleared_short` | 生成 | MEDIUM |
| 其他状态 | 不生成 | — |

- **规则状态**（FR-014）：存在 `uncleared_repeated` 或 `cleared_repeated` → `fail`；仅存在短告警、未清除单发或观察窗不足 → `warn`；其余 → `pass`。skip 条件为无匹配文件或全部记录时间不可解析（FR-015）。
- **Finding 数量**：按状态优先级（`uncleared_repeated` → `cleared_repeated` → `cleared_short`）+ `recent_seen_at` 倒序，最多输出前 20 条 Finding；`summary` 与元数据始终给出完整计数，Finding 截断时在元数据里记录 `findings_truncated` 与实际数量。避免大包下 Finding 列表爆炸。
- **理由**：Finding 是值班人员第一时间看到的列表，必须按风险排序且可控；完整证据保留在 `metadata.groups[]`（FR-013、FR-020）。
- **备选**：每个分组都生成 Finding —— 被否，大包下会淹没顶部告警。

## R6. 参数声明

- **决定**：沿用既有 `Inspector.params` 声明式契约（`list[dict[str, str]]`），定义以下键并给出默认值；算法从模块级常量读取默认值，规则元数据与计算共享同一份默认表，避免"声明值与实际值脱节"：

| key | 默认值 | 单位 | 标签 |
| --- | --- | --- | --- |
| `short_alarm_sec` | 300 | 秒 | 短告警阈值 |
| `repeat_window_sec` | 3600 | 秒 | 复发窗口 |
| `min_repeat_count` | 3 | 次 | 最小复发次数 |
| `flap_gap_sec` | 1800 | 秒 | 闪断间隔阈值 |
| `stable_observation_sec` | 1800 | 秒 | 稳定观察窗 |
| `operation_window` | `00:00-02:00` | — | 操作窗（本地时间） |
| `operation_window_enabled` | `true` | — | 操作窗开关 |

- **理由**：spec 要求阈值可配置、可解释；项目现有参数是"声明 + 默认值"形式，没有站点级覆盖层，本版不新增配置面（符合澄清"不得引入站点级覆盖或配置文件开关"）。参数变更只改参数表，不因参数变化升级 `rule_version`（FR-018）。
- **备选**：新增规则参数配置文件 —— 被否，超出本版范围且与宪法"轻量默认"冲突。

## R7. 操作窗语义

- **决定**：以每条记录**所在自然日**的本地时间判定窗口归属（FR-022）。对分组输出 `in_window_occurrences` / `out_of_window_occurrences`，并在证据中标记 `out_of_window_reappear`（窗口内首现后、窗口外仍有出现）与 `unrecovered_after_window`（窗口结束后仍存在未清除记录）。窗口可关闭；关闭时两个计数都记 0、不产生窗口标记。
- **理由**：用户明确"夜间操作会出现告警是正常的，重点是平时告警不能放过"，因此窗口只作证据标注，不做降噪（FR-024）。
- **备选**：窗口内告警折叠/降级 —— 被否，明确列入范围外；白名单式降噪会掩盖真实故障。

## R8. 元数据与展示契约

- **决定**：完整分组明细放入 `RuleResult.metadata.alarm_flapping`（结构见 [contracts/alarm-flapping-result.md](contracts/alarm-flapping-result.md)），指标使用英文小写下划线键、中文标签；**不新增 API、不改 OpenAPI、不改 `RuleResult` 字段语义**。前端在 `RuleDetailPage` 增加条件渲染的分组面板（读取 `metadata.alarm_flapping.groups`），HTML 报表现有"发现"区块已覆盖 Finding 展示；如需新增展示维度才考虑契约变更。
- **理由**：宪法要求"新增巡检能力必须增加指标键或元数据，而非重定义既有字段"；澄清阶段已确认不新增接口。
- **备选**：新增 `/api/v2/.../flapping-groups` 接口 —— 被否，超出本版范围并触发 OpenAPI 变更。

## R9. 样例包构造

- **决定**：只扩充 `tests/fixtures/make_real_package.py`，在既有 `alarm_history_202609010101137101.zip` 内新增 `ALARM_CSV_003`（文件名 `alarm_history_202609010101137101_003.csv`，9 行），既有 13 行语义与时间保持不变（只增不减）；固定字面量、无随机、无 `now()`，保持幂等（FR-025）。扩充后覆盖窗为 2026-09-01 10:00:01 → 2026-09-02 12:05:30，共 22 行 / 17 个分组。

| 分组 | 场景 | 期望结论 |
| --- | --- | --- |
| `SCTP_LINK_DOWN / umf-node-01`（既有行不动，alarm_id 1002：10:00:04 出现、10:00:30 清除，持续 26 秒） | 单次短告警 + 观察窗充足（约 26 小时） | `cleared_short`（`is_short` 先于观察窗判定），`observation_gap_sec = 93900`，规则 `warn` |
| `AUTH_FAILURE_BURST / umf-node-01`、`SERVICE_UNAVAILABLE / csp-node-01`、`CONTAINER_RESTART / pod-csp-1`、`FILE_HANDLE_HIGH / pod-csp-2`（4 个既有分组）与 `1050 / pod-umf-9` | 已清除且观察窗充足、无复发 | `cleared_stable`，不产生 Finding，不判"未清除"；样例包稳定组共 5 个 |
| `1050 / pod-umf-9`（00:30 出现、00:45 清除；02:30 再现、02:40 清除） | 操作窗跨界的窗口外再现 | 非反复（两行跨度 7200 秒 > 3600 秒）；`out_of_window_occurrences ≥ 1` 且 `out_of_window_reappear = true`；主状态 `cleared_stable`，不因窗口降级 |
| `1051 / pod-umf-9`（00:10、00:40、01:00 出现，未清除） | 未清除且 60 分钟内 3 次（00:10–01:00 恰好 50 分钟） | `uncleared_repeated`，规则 `fail`，Finding 为 CRITICAL |
| `1052 / pod-umf-9`（11:00 出现、11:10 清除；11:30 再现、11:40 清除；11:50 再现、12:00 清除） | 已清除、60 分钟内 3 次且每次清除后 30 分钟内再现 | `cleared_repeated`，`min_repeat_gap_sec = 600`，Finding 为 HIGH |
| `1053 / pod-umf-9`（09-02 12:00 出现、12:05:30 清除） | 已清除但观察窗为零（恰好是覆盖窗末端） | 持续 330 秒，观察窗 0 秒 < 1800 秒 → 主状态 `observation_insufficient`，不判稳定、不出 Finding，规则 `warn` |

- 次级覆盖由单元测试内联数据补充：重复行、时钟倒挂、部分/全部时间不可解析、`object` 缺失、TXT 与 CSV 混合、单个 CSV 解析失败、跨毫秒的观察窗边界、阈值参数变化后的重跑。
- 样例包覆盖全部六种主状态：`uncleared_single`（8 个既有未清除分组）、`uncleared_repeated`（1051）、`cleared_repeated`（1052）、`cleared_short`（`SCTP_LINK_DOWN / umf-node-01`）、`observation_insufficient`（1053）、`cleared_stable`（4 个既有已清除分组 + 1050）。
- **分组键写法**：分组键是 `alarm_code + object`，本文件与 plan/quickstart 中的 `1050 / pod-umf-9`、`SCTP_LINK_DOWN / umf-node-01` 即分组键本身。既有样例行的 `alarm_code` 是符号名（`1002`/`1008`/`1009` 是它们的 `alarm_id`），新增样例行的 `alarm_code` 使用数字告警码 `1050`–`1053`；`ALARM_CSV_003` 的 9 行顺序为 1050×2（行 2–3）、1051×3（行 4–6）、1052×3（行 7–9）、1053×1（行 10），Finding 证据行号按此口径。
- **理由**：宪法 2.9.0 要求功能数据样例进入代表性样例包并覆盖正常路径与关键边界；样例"只增不减"意味着保留既有 13 条告警语义，新增集中在 `ALARM_CSV_003`，对既有断言的改动限于条数与分布。
- **备选**：只写内联单测 —— 被否，宪法明确禁止。

## R10. 性能与容错

- **决定**：实现只用标准库（`csv`、`datetime`、`collections`、`statistics` 等），单次遍历 + 分组聚合；CSV 逐行读取、不构造 DataFrame（FR-021）。分组数增长按 O(n log n)（排序）处理，不引入索引或二次扫描。
- **理由**：单包大任务的主要成本在日志与 KPI 阶段，告警文件量级相对小；用零依赖实现可保证 4 进程并行阶段不被新规则显著拖慢。
- **备选**：引入 pandas —— 被否，收益不足且与"轻量默认"冲突。

## R11. 时间解析的时区处理

- **决定**：带时区记录统一转换为 UTC 参与计算；无时区记录按模块常量 `ASSUMED_LOCAL_TZ`（默认 `+08:00`，与 `TZ=Asia/Shanghai` 部署一致）解释。输出时间一律 ISO-8601 带偏移（UTC 或原始偏移均按同一规则序列化），满足宪法"UTC 存储"要求（元数据内保留原始本地时间的展示副本供证据阅读）。
- **理由**：宪法要求 UTC 存储、`*_at` 命名；但闪断统计依赖相对时长，必须先把混用格式归一。
- **备选**：全部当 naive 时间直接相减 —— 被否，跨时区/带时区数据会产生错误间隔。

## R12. 单规则重跑一致性

- **决定**：规则只依赖 `ctx.resolved_files()` 与自身参数，无 prepare、无缓存，因此 `python build.py verify-one --rule alarm.flapping` 与全量执行共享同一实现，结果逐字段一致（除时间戳与耗时字段）。
- **理由**：FR-018、SC-006；项目既有 `run_rule_with_deps` 已保证解压先行与规则粒度重跑。
- **备选**：为拆分组结果单独落盘 —— 被否，破坏"结果按规则粒度持久化"的契约。
