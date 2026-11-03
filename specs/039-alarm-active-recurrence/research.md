# 阶段 0 研究：未清除告警与反复上报巡检

**日期**：2026-11-04 | **规格**：[spec.md](./spec.md) | **计划**：[plan.md](./plan.md)

## R1. 规则边界与解析模块复用

**决策**：新增 `app/inspectors/alarm/common.py`，只提供映射、CSV 读取、时间/状态/严重级规范化、对象解析、去重和质量统计。`active_state.py` 与 `recurrence.py` 都依赖 common，但彼此不导入、不调用、不读取对方 JSON，也不使用 prepare。

**理由**：两条规则面对完全相同的告警导出格式；复制映射会产生中英文口径漂移。公共模块不是注册规则，不改变“普通规则只匹配自己的 source_patterns”约束。

**未采用**：让 recurrence 复用 active_state 的中间结果会建立规则依赖；让 common 写 prepared 会把纯解析能力错误提升为跨规则基础设施。

## R2. 扫描范围

**决策**：`alarm_all.source_patterns = [r"^alarm/[^/]+\.csv$"]`，两条规则使用 `source_refs=["alarm_all"]`。

**理由**：完整匹配 `alarm/` 直属文件，排除嵌套目录、操作日志、配置、其他扩展名和跨任务数据。扫描组让路径口径只有一个稳定来源。

**未采用**：`^alarm/.*\.csv$` 会误收嵌套 CSV；按文件名前缀匹配会漏掉不同导出命名。

## R3. 状态与严重级

**决策**：

- 状态 canonical 值仅 `Not Cleared`、`Normal Cleared`、`Reset Cleared`、`Unknown`。
- 状态只读 `Whether Cleared`/`清除类型` 等显式字段；空白或未知值整行排除并计数，不由 `Cleared Time` 推断。
- 严重级 canonical 值 `CRITICAL`、`HIGH`、`MEDIUM`、`LOW`、`UNKNOWN`。未知严重级记录保留，计入分布与质量；活动规则至少 `warn`，Finding 使用 `MEDIUM` 展示严重度。
- 映射大小写不敏感、去首尾空白；未知原始值按计数审计。

**理由**：满足“不猜测”同时保留可审计记录。未知严重级不能算活动，也不能当作无风险消失。

## R4. 时间、覆盖与持续时长

**决策**：带偏移时间用 `datetime.fromisoformat` 后转 UTC；无偏移时间附加 `timezone(timedelta(hours=8))` 后转 UTC。支持 `YYYY-MM-DD HH:MM:SS` 与 ISO `T`。覆盖起点取有效 Raised 最小值，覆盖末刻取全部有效 Raised/Cleared 最大值。

- 已清除记录持续时长：`Cleared - Raised`，早于 Raised 时标记不可用。
- 未清除记录持续时长：`coverage_end - Raised`。
- 最短相邻间隔：有效 Raised 排序后的最小时间差。
- 结果说明明确 `coverage_end` 是告警数据末刻，不是任务执行或真实恢复时刻。

**理由**：统一 UTC 存储并保持现场解释可复现；不允许根据“后面没有记录”推断恢复。

## R5. 重复次数口径

**决策**：

- `raw_repeat_times_total = Σ Repeat Times`，只对有效非负整数求和。
- `estimated_report_total = Σ(1 + Repeat Times)`，明确标记“估算”。
- 单条无效/缺失不丢弃生命周期，但该记录重复字段为 `null`；聚合输出 `repeat_totals_complete=false`，并计数无效/缺失值。

**理由**：两类证据不能混用。缺少 Repeat Times 时不能猜测 0，也不能因质量缺陷隐藏整条生命周期。

## R6. 去重与记录身份

**决策**：有效记录按规范化业务字段元组去重，包括应用、告警 ID/名称、严重级、状态、原始时间值、重复次数、序列号、定位和附加信息；不含来源文件/行号。完全重复只保留首条并计数。

**理由**：跨文件重复导出常见；生命周期时间或重复次数不同代表不同证据，不能合并。规范化后中英文同值记录也可去重。

## R7. 对象解析

**决策**：集中从直接列、`Location Info`、`Additional Information` 的 `key=value` 段中查找对象字段，优先级固定为：

1. `Pod Name`
2. `Located Device`
3. `Service Name`
4. `Alarm Source`

所有已知中英文别名在进入优先级链前归一化。找不到时使用稳定占位 `对象未识别`，保留来源文件/行号并计数；禁止把整段可变描述作为对象键。

**理由**：对象应先具体后宽泛；稳定占位避免同一条未知记录被拆成大量伪对象。

## R8. 活动告警分组与排序

**决策**：活动记录按 `(App Name, Alarm ID, normalized object)` 分组。记录明细和分组明细按严重级（CRITICAL→HIGH→MEDIUM→LOW→UNKNOWN）、原始重复合计、持续时长降序。活动 Finding 每个分组一条。

**理由**：记录明细满足逐行追溯，分组明细满足当前风险排序。单条超长重复记录和零重复活动记录都能正确区分。

## R9. 反复上报识别

**决策**：

- `multi_lifecycle`：生命周期数 > 1。
- `repeat_reporting`：有效原始重复合计 > 0。
- `short_alarm`：任一条已清除生命周期满足 `0 <= duration <= short_alarm_sec`。
- `rapid_recurrence`：按 Raised 排序，在长度 `rapid_recurrence_window_sec` 的窗口内出现至少 `rapid_recurrence_min_count` 条记录。
- `reset_cleared`：任一条状态为 Reset Cleared。
- 默认参数 300、3600、3，并在 metadata 回显。

**理由**：生命周期数量和单条重复次数是正交证据；快速复发基于可复核的时间窗口，不把时间窗称为“非操作时间”。

## R10. 规则状态与 Finding 顺序

**决策**：

- active：Critical/Major 活动 `fail`；仅 Minor/LOW/未知活动 `warn`；无活动 `pass`；无文件或无可分析记录 `skip`；失败文件/质量降级无活动时至少 `warn`。
- recurrence：未清除且 `repeat_reporting` 或 `rapid_recurrence` → `fail`；存在其它风险标记 → `warn`；无风险 → `pass`；无文件或无可分析记录 → `skip`；失败文件/质量降级无风险时至少 `warn`。
- Finding id 使用规则代码 + 规范化业务键的 SHA-256 前缀，稳定且不包含执行时间。
- Finding 证据包含首个可追溯来源文件和行号，以及完整汇总数值。

**理由**：活动风险优先，同时保持“已清除但反复”“短告警”“Reset”可审计，不宣称稳定恢复。

## R11. 安全预算与截断

**决策**：

- 单文件 > 32 MiB：文件失败，不读取正文。
- 单文件 > 100,000 数据行或任务累计 > 250,000 数据行：受控结束解析并标记预算失败；其它已完成文件的有效记录仍可供规则判定，规则至少 `warn`。
- 分组/记录/对象展示最多 100 条；汇总基于完整有效数据。
- metadata 始终输出 `details_truncated`、`findings_truncated` 和对应总数。

**理由**：当前数据远低于预算；明确上限防止超大导出耗尽 worker。截断只影响展示，不影响用户看到真实总数。

## R12. 前端和报告

**决策**：两个新组件直接消费 metadata，不增加 API 调用。`RuleDetailPage` 按命名空间选择组件；HTML 报告读取活动规则 metadata。两者都同时展示原始重复合计与估算上报总数。

**未采用**：新增专用 API 或改变 RuleResult Schema；这会违反契约驱动要求且无必要。

## R13. 真实数据验收

**决策**：真实 CSV 只读执行两条规则，记录输入 SHA-256 和文件大小，验收后复核未变化。输出写入隔离临时/任务结果目录，不生成可提交工件。

**预算**：单规则目标 ≤2 秒；合成 5,000 行解析守护测试用于发现明显退化。实际耗时作为验收报告记录，不作为跨机器硬阈值以外的 CI 断言。

## R14. 未采用方案

- 恢复 `alarm.stat`/`alarm.flapping`：违反 037 历史只读边界，且会冲突旧 metadata。
- 依据操作日志推断非操作时间：超出仅分析告警文件的范围。
- 以 `Cleared Time` 是否为空推导状态：导出口径不可靠，违反显式状态要求。
- 只按生命周期或只按 Repeat Times 判断反复：两种误判均已被真实基线证明。
- 保留完整原始 CSV/行在 metadata：泄露和体积风险高；来源引用与 Top-N 足够追责。
