---
description: "告警生命周期与闪断检测 — 实现任务清单"
---

# 任务：告警生命周期与闪断检测

**输入**：来自 `specs/030-alarm-flapping/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/alarm-flapping-result.md、quickstart.md

**测试**：本清单包含测试任务；每个用户故事先写失败测试，再补实现（TDD）。

**组织方式**：按用户故事分组，每个故事可独立实现与验证。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1/US2/US3/US4）
- 描述中包含精确的文件路径

## 路径约定

仓库根目录：`app/`、`web/`、`tests/`、`docs/`、`specs/`。规划产物在 `main` 主工作区完成；实现与测试在实现分支 worktree `.worktrees/feature/030-alarm-flapping` 内完成，不得在主工作区改实现文件。

---

## 阶段 0：设置（样例包与测试脚手架）

**目的**：按宪法 2.9.0 扩充代表性样例包，并准备可复现的测试脚手架

- [x] T001 在 `tests/fixtures/make_real_package.py` 中新增 `ALARM_CSV_003` 常量（9 行固定字面量、无随机、无 `now()`），写入既有 `alarm_history_202609010101137101.zip`，成员名 `alarm_history_202609010101137101_003.csv`；行序固定为 1050×2（文件行 2–3）、1051×3（行 4–6）、1052×3（行 7–9）、1053×1（行 10）；既有 13 行语义与时间逐字不变（FR-025、research R9、quickstart 第 2 节）
- [x] T002 在 `tests/fixtures/make_real_package.py` 中新增模块 `__main__` 入口，支持 `.venv/bin/python tests/fixtures/make_real_package.py <目录>`，保留 `build_real_package()` 供测试调用，且重复生成内容稳定（依赖 T001）
- [x] T003 [P] 在 `tests/test_alarm_flapping.py` 中搭建测试脚手架：临时任务目录、`RuleContext`（`files` 为 `output/<task_id>/` 下 POSIX 相对路径）、内联 CSV/TXT 告警构造工厂、`params` 覆盖 helper；文件当前必须能被 pytest 收集
- [x] T004 [P] 在 `tests/test_real_package.py` 中更新 `alarm.stat` 断言为总量 22、未处理 11、`severity_distribution` = `CRITICAL 6 / HIGH 8 / MEDIUM 6 / LOW 2`，并把 `alarm/alarm_history_202609010101137101_003.csv` 加入 ctx 文件清单（依赖 T001；FR-003）
- [x] T005 [P] 在 `tests/test_sample_guard.py` 中断言真实样例包执行结果包含 `alarm.flapping` 且状态非 `skip`，`EXPECTED_SKIPS` 保持 `{"kpi.measurement_units", "traffic.stat"}` 不变（依赖 T001；FR-025）

**检查点**：样例包可生成且幂等；新测试文件可被 pytest 收集；规则相关断言当前失败，`alarm.stat` 新断言通过。

---

## 阶段 1：基础层（阻塞全部用户故事）

**目的**：规则可注册、可解析、可分组、可返回 skip，且契约结构可被测试断言

- [x] T006 在 `tests/test_alarm_flapping.py` 中先写基础层失败测试：规则存在于注册表且元数据为 `code=alarm.flapping`、`category=alarm`、`priority=P1`、`severity=high`、`rule_version=1.0.0`、`source_refs=["alarm_all"]`；`params` 含七个参数键与契约默认值；无匹配告警文件时返回 `skip` + 非空 `skip_reason`（FR-001、FR-015、契约 §1/§6）；并断言规则只依赖自身 `source_patterns`：静态检查 `flapping.py` 不 import 其他巡检规则模块，运行期不读取其他规则结果 JSON 与 `output/<task_id>/prepared/` 下任何目录（FR-002）
- [x] T007 在 `app/inspectors/alarm/flapping.py` 中新增规则模块：注册 `Inspector` 元数据（`name`、`description`、`recommendation`、`outputs_metrics` 11 个指标键、`params`）与 `FlappingPolicy` dataclass（`slots=True`，参数 `short_alarm_sec=300`、`repeat_window_sec=3600`、`min_repeat_count=3`、`flap_gap_sec=1800`、`stable_observation_sec=1800`、`operation_window=00:00-02:00`、`operation_window_enabled=true`），`inspector.params` 由同一默认表生成（FR-001、FR-012、FR-018、契约 §1/§4）；模块只 import 标准库与公共契约层（`app.core`/`app.models`），不得导入其他巡检规则实现、不得读取其他规则结果或 prepared 数据（FR-002）
- [x] T008 在 `app/inspectors/alarm/flapping.py` 中实现解析层：`ctx.resolved_files()` → 统一解码（UTF-8 / GB18030）→ 字段名小写与首尾空白归一 → `AlarmRecord`（`source_file` 为任务内 POSIX 相对路径、`line_no` 含表头偏移）；时间兼容 ISO-8601 与 `YYYY-MM-DD HH:MM:SS`，无时区按 `ASSUMED_LOCAL_TZ`（`+08:00`）解释；文本行没有清除时间，按未清除处理（FR-016、FR-017、FR-019、data-model §2）
- [x] T009 在 `app/inspectors/alarm/flapping.py` 中实现行级校验、去重与覆盖窗口：`created_at` 不可解析、`cleared_at` 存在但不可解析、`cleared_at < created_at`、`alarm_code` 缺失的行计入 `excluded_rows` 并在日志给出原因分类；去重键为 `alarm_id + created_at + alarm_code + object` 四元组，命中计入 `duplicate_rows` 且不进入下游统计；`CoverageWindow.start_at = min(created_at)`、`end_at = max(cleared_at ?? created_at)`、`span_sec` 为整数秒（FR-016、data-model §2/§3）
- [x] T010 在 `app/inspectors/alarm/flapping.py` 中实现分组与 skip 契约：按 `(alarm_code, object)` 分组（`object` 为空归入"对象未知"分组，不得丢弃），组内记录按出现时间排序；无有效记录（全部行时间不可解析）时返回 `skip` + `skip_reason`（说明被排除行数与原因分类）；单个文件解析失败只计入 `failed_files` 并继续处理其他文件（FR-004、FR-015、FR-016、data-model §8）

**检查点**：基础层测试通过；规则可在全量任务与单规则重跑中注册并返回契约化 `skip`。

---

## 阶段 2：用户故事 1 - 值班人员看清"已清除但会反复"的告警（优先级：P1）🎯 MVP

**目标**：规则输出的分组状态、Finding 与指标与契约样例逐字段一致，并在规则详情页可见。

**独立测试**：用构造数据分别覆盖"60 分钟内 3 次且清除后 30 分钟内再现""单次 26 秒短告警""清除后 30 分钟无复发"三类，检查状态、Finding 与指标，无需其他规则参与。

### 用户故事 1 的测试

- [x] T011 [US1] 在 `tests/test_alarm_flapping.py` 中写失败测试：60 分钟内 3 次且每次清除后 30 分钟内再现 → `cleared_repeated` + HIGH Finding（含 `min_repeat_gap_sec` 证据）；单次持续 26 秒且已清除 → `cleared_short` + MEDIUM Finding；已清除且清除后 30 分钟无复发 → `cleared_stable` 且零 Finding（FR-006–FR-010、FR-013、SC-002、SC-003）；追加操作窗用例：跨自然日数据按每条记录所在自然日归属，`00:30 出现 / 02:30 再现` 的分组 `in_window_occurrences=1`、`out_of_window_occurrences=1`、`out_of_window_reappear=true` 且主状态仍为 `cleared_stable`（FR-022、FR-023、FR-024、SC-007）
- [x] T012 [US1] 在 `tests/test_alarm_flapping.py` 中写失败测试：Finding 上限 20 条；`finding_id` 命名 `alarm.flapping-{state}-{alarm_code}-{object}`（`object` 为空用 `unknown`）；输出顺序 `uncleared_repeated → cleared_repeated → cleared_short`，同状态按 `recent_seen_at` 倒序；`groups` 超过 `groups_max=500` 时截断并置 `groups_truncated`（契约 §2/§5、data-model §8）

### 用户故事 1 的实现

- [x] T013 [US1] 在 `app/inspectors/alarm/flapping.py` 中实现分组生命周期字段：`occurrence_count`、`cleared_count`、`uncleared_count`、`first_seen_at`、`recent_seen_at`、`recent_cleared_at`（无已清除记录为 `None`）、`max_duration_sec`、`total_duration_sec`、`min_repeat_gap_sec`（相邻"清除 → 再现"间隔最小值，无则为 `None`）、`repeated`（存在跨度 ≤ `repeat_window_sec` 的连续出现区间且出现次数 ≥ `min_repeat_count`）、`is_short`（全部已清除且 `max_duration_sec <= short_alarm_sec`）、`observation_gap_sec = coverage_end - 最晚一次清除时间`、`observation_insufficient`（存在未清除记录或 `observation_gap_sec < stable_observation_sec`）（FR-005、FR-007、FR-008、FR-010、data-model §6）
- [x] T014 [US1] 在 `app/inspectors/alarm/flapping.py` 中实现主状态机与闪断事件：状态优先级 `uncleared_repeated > uncleared_single > cleared_repeated > cleared_short > observation_insufficient > cleared_stable`，`is_short` 先于观察窗判定；事件串联按"前次清除到下次出现 ≤ `flap_gap_sec`"（前次未清除则后续出现一律并入），`is_flap` = 出现次数 ≥ 2 且（事件未结束/含未清除记录，或至少一次间隔 ≤ `flap_gap_sec`）（FR-006、FR-009、FR-024、data-model §5/§7）；操作窗命中只影响证据字段，绝不参与主状态判定或排序（`1050` 主状态保持 `cleared_stable`）
- [x] T015 [US1] 在 `app/inspectors/alarm/flapping.py` 中实现 Finding 与指标：三类 Finding（`uncleared_repeated`→CRITICAL、`cleared_repeated`→HIGH、`cleared_short`→MEDIUM）文案必须含分组键（对象空显示"对象未知"）、出现次数与已清除/未清除分布、首次/最近出现、最近清除、复发间隔与触发窗口、窗口内/外出现次数与 `out_of_window_reappear` / `unrecovered_after_window` 标记、本次生效阈值、来源文件与行号（FR-023）；11 个指标键写入 `RuleResult.metrics`；规则状态映射为存在两类反复 → `fail`、仅短告警/未清除未反复/观察窗不足 → `warn`、其余 → `pass`（FR-012–FR-014、契约 §4/§5）
- [x] T016 [US1] 在 `app/inspectors/alarm/flapping.py` 中实现 `metadata.alarm_flapping`：`schema_version=1`、`policy`（含 `parameter_source="inspector_default"`）、`coverage`（`start_at`/`end_at`/`span_sec`）、`totals`（`rows`/`valid_rows`/`groups`/`excluded_rows`/`duplicate_rows`/`failed_files`/`findings_truncated`/`groups_truncated`）、`state_counts`（六键必须全部出现）、`groups[]`（契约 §2 全字段，时间 ISO-8601 带偏移、未知用 `null`）、`notes`（FR-020、契约 §2/§3）；操作窗按每条记录所在自然日的本地时间判定 `in_window_occurrences` / `out_of_window_occurrences`，`operation_window_enabled=false` 时两个计数记 0 且 `out_of_window_reappear` / `unrecovered_after_window` 均为 false（FR-022、FR-023）
- [x] T017 [US1] 在 `web/src/pages/RuleDetailPage.tsx` 中新增条件渲染的"告警生命周期分组"卡片：仅当 `result.metadata.alarm_flapping` 存在时渲染，按状态优先级排序，展示状态、出现次数、首次/最近出现、最短复发间隔、观察窗与操作窗标记；不新增接口、不改 OpenAPI 与生成客户端（FR-020、SC-005、research R8）
- [x] T018 [US1] 在 `web/e2e/` 中新增 E2E：真实样例包执行后，规则详情页可见分组卡片，可区分"反复闪断 / 单次短告警 / 仍未恢复 / 稳定恢复"四类结论，且 CRITICAL/HIGH/MEDIUM 三条 Finding 可见（SC-005、SC-008）

**检查点**：US1 独立可用——契约样例的 7 个分组结论在规则 JSON、规则详情页与 HTML 报告一致，稳定分组零 Finding。

---

## 阶段 3：用户故事 2 - "未清除"和"反复"不能被状态字段掩盖（优先级：P1）

**目标**：缺清除时间但 `status=已处理/处理中` 的记录不被当作已恢复，未清除且反复的分组优先输出。

**独立测试**：构造缺失 `cleared_time` 且状态为"已处理"的记录并多次出现，检查分组状态、排序与 Finding。

- [x] T019 [US2] 在 `tests/test_alarm_flapping.py` 中写失败测试：`cleared_time` 缺失且 `status=已处理` 的记录不计入 `cleared_count`、其分组不得判为稳定；同一分组未清除且在 60 分钟窗口内出现 ≥3 次 → `uncleared_repeated`、排在输出最前、携带 CRITICAL Finding，且 `recent_cleared_at`、`min_repeat_gap_sec`、`observation_gap_sec` 均为 `null`、`observation_insufficient=true`、`unrecovered_after_window=true`（FR-004、FR-006、FR-011、spec 用户故事 2）
- [x] T020 [US2] 在 `app/inspectors/alarm/flapping.py` 中实现未清除分支：`status` 字段只做展示、绝不作为恢复证据（`已处理`/`处理中` 一律视为未恢复）；未清除分组固定 `observation_insufficient=true` 且 `observation_gap_sec=null`；`uncleared_repeated` 排序最前（FR-006、FR-011、data-model §7）

**检查点**：US2 独立可用——"已处理但没有清除时间"的告警不再落入通过或稳定结论。

---

## 阶段 4：用户故事 3 - 数据不足时显式标出，不放行也不误报（优先级：P1）

**目标**：时间异常、重复、缺字段、文件失败都被显式统计，观察窗不足不得判稳。

**独立测试**：分别构造"全部行时间不可解析""部分行时间不可解析""清除时间早于出现时间"三类数据，检查规则状态、`skip_reason` 与元数据计数。

- [x] T021 [US3] 在 `tests/test_alarm_flapping.py` 中写失败测试：部分行时间不可解析与时钟倒挂 → `excluded_rows > 0`、其余分组正常判定、任务不失败；同一去重键重复行 → `duplicate_rows > 0` 且只计一次；单个 CSV 解析失败 → `failed_files > 0` 且其他文件不受影响；`object` 缺失 → 归入空对象分组并保留记录；TXT 与 CSV 混合 → 合并排序后统一判定（FR-015、FR-016、spec 边界情况）
- [x] T022 [US3] 在 `tests/test_alarm_flapping.py` 中写失败测试：某分组最后一次清除距覆盖末端 < `stable_observation_sec` → 主状态 `observation_insufficient`，不得判稳定；已清除且观察窗充足、无复发 → `cleared_stable`；全部记录时间不可解析 → `skip` + `skip_reason` 说明被排除行数与原因分类（FR-010、FR-015、SC-004、spec 用户故事 3 验收场景 1–3）
- [x] T023 [US3] 在 `app/inspectors/alarm/flapping.py` 中补齐容错与观察窗实现：确保 `excluded_rows`、`duplicate_rows`、`failed_files`、`skip_reason` 全部显式输出且不静默丢弃；观察窗不足只作为独立标记与兜底主状态，不掩盖更高优先级状态（FR-006、FR-012、FR-016）

**检查点**：US3 独立可用——数据不足场景全部显式标注，无一例落入 `pass`。

---

## 阶段 5：用户故事 4 - 阈值可配置、结论可解释、可单规则重跑（优先级：P2）

**目标**：阈值改默认值后单规则重跑即可复现结论变化，Finding 能读到本次阈值。

**独立测试**：修改规则参数后执行 `verify-one`，对比同一份数据的判定结果与 Finding 证据文本。

- [x] T024 [US4] 在 `tests/test_alarm_flapping.py` 中写失败测试：把 `FlappingPolicy.min_repeat_count` 改为 4 后重跑同一份数据，`1051` 与 `1052` 均因出现 3 次低于阈值而离开反复状态（`uncleared_single`、`observation_insufficient`），规则状态 `fail → warn`、Finding 由 3 条降到 1 条；恢复默认值后结论回到契约基线；`rule_version` 不因参数变化递增（FR-018、SC-006、quickstart 第 5 节）；追加 `operation_window_enabled=false` 用例：窗口计数归零、窗口标记全 false，且各分组主状态与开启时逐组一致（FR-022、FR-024）
- [x] T025 [US4] 在 `app/inspectors/alarm/flapping.py` 中确保参数只在 `FlappingPolicy` 默认表声明、Finding 与元数据携带本次生效阈值；`python build.py verify-one --rule alarm.flapping` 与全量任务结果逐字段一致（`executed_at`、`duration_ms` 除外）（FR-013、FR-018、SC-006、research R12）

**检查点**：US4 独立可用——阈值变化可解释、可追溯，单规则重跑与全量一致。

---

## 阶段 6：收尾与横切关注点

**目的**：样例包看护、文档同步、门禁与性能证据

- [x] T026 在 `tests/test_real_package.py` 或 `tests/test_alarm_flapping.py` 中增加真实样例包契约快照断言：`totals.rows=22`、`totals.groups=17`、`state_counts` 六键、8 项状态指标（`alarm_groups=17`、`flapping_groups=2`、`uncleared_repeated_groups=1`、`short_alarm_groups=1`、`stable_groups=5`、`observation_insufficient_groups=11`、`out_of_window_groups=1`、`unrecovered_after_window_groups=1`）、3 条 Finding、`coverage.span_sec=93929`、`excluded_rows=duplicate_rows=failed_files=0`、`1002` 为 `cleared_short`、`1053` 为 `observation_insufficient`、`1050` 证据含窗口外再现（契约 §2/§4、SC-001、SC-007、SC-008）
- [x] T027 [P] 更新 `docs/architecture.md` 与 `docs/design/mechanisms.md`：登记 `alarm.flapping` 规则、六态定义、观察窗与操作窗证据口径
- [x] T028 [P] 更新 `docs/example/real-package-structure.md`：告警压缩包内新增 `alarm_history_202609010101137101_003.csv`，并说明 `alarm.flapping` 与 `alarm.stat` 共用该批文件
- [x] T029 按 `specs/030-alarm-flapping/quickstart.md` 全流程执行（生成样例包、`python build.py verify`、核对结果 JSON、`verify-one`、阈值变更重跑、展示核对），把实测偏差回写 quickstart
- [x] T030 执行交付门禁：`python build.py lint`、`python build.py test`、`python build.py verify`、`python build.py web-build` 全部通过；确认本功能未改 `docs/api/openapi.yaml`，无需 `python build.py contract` / `gen-web-api`（AGENTS.md 测试与交付门槛）
- [x] T031 在 `tests/test_alarm_flapping.py` 中增加性能看护断言并使用放大的临时 fixture 验证线性：真实样例包内规则耗时 < 100ms（阈值留出抖动余量），实现为单次遍历 + 分组聚合、无 pandas、无二次扫描（FR-021、plan 性能目标）

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 0（设置）**：无依赖，可立即开始；T002 依赖 T001，T004/T005 依赖 T001
- **阶段 1（基础层）**：依赖阶段 0 的样例包与脚手架；阻塞全部用户故事
- **阶段 2–5（用户故事）**：均依赖基础层；US2/US3/US4 的测试依赖 US1 建立的 `flapping.py` 结构与元数据骨架
- **阶段 6（收尾）**：依赖全部用户故事完成

### 用户故事依赖

- **US1（P1）**：基础层完成后即可开始，不依赖其他故事
- **US2（P1）**：可与 US1 并行设计，但实现上复用 US1 的状态机入口
- **US3（P1）**：可与 US1/US2 并行，主要覆盖解析与观察窗边界
- **US4（P2）**：依赖 US1 的 Finding 与参数表落地后验证

### 每个用户故事内部

- 先写测试并确认失败，再补实现（TDD）
- 契约结构（元数据/指标/Finding）先于前端展示
- 每个故事完成后在检查点独立验证，再进入下一个优先级

### 并行机会

- 阶段 0：T003、T004、T005 可并行（不同文件）
- 阶段 6：T027、T028 可并行（不同文档）
- 同一故事内的测试与实现不得并行（同一文件或存在先后依赖）

---

## 并行示例：阶段 0

```bash
# T003、T004、T005 可同时进行（不同文件）：
Task: "在 tests/test_alarm_flapping.py 中搭建测试脚手架"
Task: "在 tests/test_real_package.py 中更新 alarm.stat 断言"
Task: "在 tests/test_sample_guard.py 中加入 alarm.flapping 非 skip 断言"
```

---

## 实现策略

### MVP 优先（基础层 + US1）

1. 完成阶段 0：样例包扩充与测试脚手架
2. 完成阶段 1：基础层（阻塞全部用户故事）
3. 完成阶段 2：US1（状态机、Finding、指标、元数据、详情页面板、E2E）
4. **停止并验证**：契约样例 7 个分组结论、`alarm.stat` 22/11 断言、规则详情页四类结论可见
5. 就绪后进入 US2–US4，最后跑快速验证与交付门禁

### 增量交付

1. 阶段 0 + 阶段 1 → 规则可注册、可解析、可返回 skip（尚不产出结论）
2. US1 → 反复/短告警/稳定三类结论 + 展示（MVP）
3. US2 → 未清除与反复不被状态字段掩盖
4. US3 → 数据不足显式标注
5. US4 → 阈值可配置与单规则重跑一致
6. 阶段 6 → 样例包看护、文档同步、门禁与性能证据

---

## 注意事项

- [P] 任务 = 不同文件、无未完成依赖
- 每个任务完成后提交，提交信息使用中文 + Conventional Commits 前缀
- 契约（`contracts/alarm-flapping-result.md`）是唯一事实来源；实现与文档冲突时先改契约再改实现
- 不得修改 `alarm.stat` 的语义与 `rule_version`；不得引入规则间依赖或 prepare
