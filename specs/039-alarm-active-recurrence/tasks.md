---
description: "未清除告警与反复上报巡检实现任务"
---

# 任务：未清除告警与反复上报巡检

**输入**：`specs/039-alarm-active-recurrence/spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`

**测试策略**：测试先行。每条规则的契约、判定和展示测试必须先确认失败，再实现对应能力。

**组织方式**：公共解析与扫描范围作为阻塞基础；US1 与 US2 均为 P1，基础完成后可独立推进和验收。

## 阶段 1：设置

**目的**：在规划审查和提交完成后建立隔离实现现场，保护主工作区中的其他未提交改动。

- [ ] T001 确认 039 规划已提交到 `main` 后，在 `.worktrees/feature-039-alarm-active-recurrence` 创建或复用 `feature/039-alarm-active-recurrence` worktree，并执行 `git worktree list`、`git branch --show-current`、`pwd` 记录前置检查结果；不得带入主工作区未提交的 KPI 改动

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：建立两条规则共享的扫描口径、合成数据和中英文解析能力。

**⚠️ 关键**：本阶段完成前不得开始任何用户故事实现。

- [ ] T002 [P] 在 `tests/test_scan_config_registry.py` 增加测试，断言 `alarm_all.source_patterns=["^alarm/[^/]+\\.csv$"]`、直接告警 CSV 边界以及两条告警规则使用 `source_refs=["alarm_all"]`
- [ ] T003 [P] 在 `tests/test_alarm_common.py` 编写表头大小写/空白、UTF-8 BOM、中英文状态与严重级、未知值审计、UTC+8 无时区转换、带偏移转 UTC、对象优先级和稳定占位测试
- [ ] T004 [P] 在 `tests/test_alarm_common.py` 编写跨文件完全重复去重、生命周期差异保留、坏时间/重复次数质量统计、单文件失败隔离、32 MiB/文件/100,000 行文件/250,000 行任务预算及 5,000 行性能守护测试
- [ ] T005 [P] 扩展 `tests/fixtures/make_real_package.py`，增加固定时间戳、可幂等重复生成的纯英文、纯中文、混合同任务及重复/坏记录/坏文件告警样例，并保留既有样例
- [ ] T006 [P] 在 `deploy/config/scan_rules.yaml` 新增 `alarm_all` 扫描组，描述为告警目录直属 CSV，并仅配置 `^alarm/[^/]+\\.csv$`
- [ ] T007 实现 `app/inspectors/alarm/common.py` 的集中映射、规范化记录、对象解析、去重、覆盖、质量、文件隔离、预算和 Top-N 所需纯解析能力，不让公共模块产生 `RuleResult` 或 prepared 数据
- [ ] T008 [P] 创建 `app/inspectors/alarm/__init__.py`，按现有规则自动发现机制导出 `alarm.active_state` 与 `alarm.recurrence`，不得导出历史 `alarm.flapping`/`alarm.stat`
- [ ] T009 运行 `tests/test_alarm_common.py`、`tests/test_scan_config_registry.py` 和合成包幂等性测试，确认基础层通过且 `tests/fixtures/make_real_package.py` 连续两次生成 SHA-256 一致

**检查点**：扫描组、中英文解析器和合成样例可用；US1 与 US2 可并行开始但不得相互读取结果。

---

## 阶段 3：用户故事 1 - 先看到仍未清除的告警和风险排序（优先级：P1）🎯 MVP

**目标**：只依据 `Whether Cleared=Not Cleared` 输出活动告警，按严重级、原始重复次数、持续时长排序，并在规则详情和报告中突出当前风险。

**独立测试**：执行 `alarm.active_state`，验证 3 条活动告警只包含 Not Cleared、Critical/Major/Minor 排序、原始重复合计 7、估算上报 10、最大单条重复 5；删除活动记录后规则为 `pass`，无文件和坏文件场景符合 `skip`/降级契约。

### 用户故事 1 的测试

> **注意：先写测试并确认失败，再实现规则和展示。**

- [ ] T010 [P] [US1] 在 `tests/test_alarm_active_state.py` 编写规则契约测试，覆盖完整元数据/10 个固定 metrics、活动筛选、状态与严重级分布、覆盖末刻持续时长、排序、Finding ID/来源、估算口径、pass/skip、质量降级、截断不改变汇总和中英文结果一致性
- [ ] T011 [P] [US1] 在 `web/src/components/AlarmActiveStatePanel.test.tsx` 编写活动面板测试，覆盖最高严重级、两种上报口径、状态分布、分组/记录列、来源行、截断提示和全部列模式
- [ ] T012 [P] [US1] 在 `tests/test_alarm_recurrence_report.py` 编写报告测试，断言 HTML 显示活动告警数、最高严重级、原始重复合计、估算上报总数、优先分组和建议，并明确估算及观察末刻口径

### 用户故事 1 的实现

- [ ] T013 [US1] 在 `app/inspectors/alarm/active_state.py` 实现 `alarm.active_state@1.0.0`，声明完整规则身份、`alarm_all` 扫描组、10 个指标、稳定 Finding、状态阈值、Top-100 截断和 `metadata.alarm_active` 契约
- [ ] T014 [US1] 在 `web/src/components/AlarmActiveStatePanel.tsx` 实现活动告警面板，同时呈现活动记录/分组、最高严重级、状态/严重级分布、原始 Repeat Times、估算上报总数、持续时长和来源追溯
- [ ] T015 [US1] 在 `web/src/pages/RuleDetailPage.tsx` 按 `metadata.alarm_active` 命名空间接入活动面板，并更新当前规则库提示文案；保持 `metadata.alarm_flapping` 历史只读渲染不变，在 `web/src/pages/RuleDetailPage.test.tsx` 补充对应覆盖
- [ ] T016 [US1] 在 `app/reports/templates/report.html.j2` 实现“告警优先处置”区块，读取 `alarm.active_state` metadata 展示关键活动统计、优先分组和建议，不把 `Reset Cleared` 描述为稳定恢复
- [ ] T017 [US1] 运行活动规则、前端面板和报告聚焦测试，确认 US1 在当前合成样例上可独立通过且不依赖 `alarm.recurrence` 的 JSON 或 prepared 数据

**检查点**：US1 可独立交付；活动告警详情、排序、Finding、页面和报告均可用。

---

## 阶段 4：用户故事 2 - 识别反复发生并核对累计上报次数（优先级：P1）

**目标**：按 `App Name + Alarm ID` 汇总全部状态生命周期，保留对象明细，分别输出生命周期、原始重复、估算上报、短告警、快速复发和 `Reset Cleared` 证据。

**独立测试**：执行 `alarm.recurrence`，验证 3 条生命周期且 Repeat Times 为 0/1/4 时得到生命周期 3、原始重复 5、估算上报 8、最大单条 4；单条高重复和多次零重复均不被漏判；60 分钟 3 次与 300 秒短告警同时命中；多对象不丢失类型总数。

### 用户故事 2 的测试

> **注意：先写测试并确认失败，再实现规则和展示。**

- [ ] T018 [P] [US2] 在 `tests/test_alarm_recurrence.py` 编写规则契约测试，覆盖完整元数据/11 个固定 metrics、五类 flags、对象聚合、相邻间隔、参数回显、Finding 优先级、pass/warn/fail/skip、质量降级、重复次数不完整、截断和 Reset 文案边界
- [ ] T019 [P] [US2] 在 `web/src/components/AlarmRecurrencePanel.test.tsx` 编写反复面板测试，覆盖两种累计口径、生命周期、最大单条重复、首次/最近时间、五类标记、对象展开、状态/严重级分布和截断提示
- [ ] T020 [P] [US2] 在 `web/e2e/alarm-active-recurrence.spec.ts` 编写完整入口到结果的 E2E，验证规则详情一屏可区分活动风险与反复风险，并同时看到原始 Repeat Times 与估算上报总数

### 用户故事 2 的实现

- [ ] T021 [US2] 在 `app/inspectors/alarm/recurrence.py` 实现 `alarm.recurrence@1.0.0`，声明完整规则身份、`alarm_all` 扫描组、11 个指标、默认参数、五类标记、稳定 Finding、Top-100 类型/对象/来源和 `metadata.alarm_recurrence` 契约
- [ ] T022 [US2] 在 `web/src/components/AlarmRecurrencePanel.tsx` 实现反复上报面板，区分未清除重复风险、历史反复、短告警、快速复发和仅 Reset 证据，并明确不推断稳定恢复
- [ ] T023 [US2] 在 `web/src/pages/RuleDetailPage.tsx` 按 `metadata.alarm_recurrence` 命名空间接入反复面板，在 `web/src/pages/RuleDetailPage.test.tsx` 覆盖两个新命名空间互斥选择和历史面板回归
- [ ] T024 [US2] 运行反复规则、前端面板和 E2E 聚焦测试，确认 US2 不依赖 `alarm.active_state` 的 JSON、调用或 prepared 数据

**检查点**：两条 P1 规则均可独立执行；US1 与 US2 同时存在时互不改变判定语义。

---

## 阶段 5：收尾与横切关注点

**目的**：完成规则库契约、代表性样例、跨执行模式、文档、真实数据只读验收和交付门禁。

- [ ] T025 [P] 更新 `tests/test_kpi_only_rule_library.py` 与 `tests/test_scan_config_registry.py` 的活动规则集合断言，期望普通规则为 `kpi.measurement_units`、`alarm.active_state`、`alarm.recurrence`，隐藏规则仍仅为两个 `pkg.extract.*`
- [ ] T026 [P] 更新 `tests/test_scan_refs.py`，验证 `alarm_all` 只匹配 `alarm/` 直属 `.csv`，排除嵌套目录、非 CSV 与 `alarm/` 外文件，并验证两条规则不互相导入或依赖 prepared
- [ ] T027 [P] 更新 `tests/test_real_package.py`，在代表性合成包中验证两条规则均被调度、关键 metadata/面板所需字段存在、KPI 规则行为不变、生成包固定时间戳且幂等
- [ ] T028 [P] 新增 `tests/test_alarm_rule_integration.py`，验证本地 CLI、在线 API、全量巡检和分别 `verify-one` 的核心状态、metrics、Finding 语义、metadata 一致，且无关文件变化不影响结果
- [ ] T029 修复 `tests/test_alarm_rule_integration.py`、`tests/test_real_package.py` 和扫描注册测试暴露的集成问题，确保规则自动发现、单规则重跑和任务摘要均不要求修改核心调度器业务逻辑
- [ ] T030 [P] 更新 `docs/architecture.md`，记录 `alarm_all`、公共纯解析模块、两条规则独立性和执行/展示数据流
- [ ] T031 [P] 更新 `docs/design/mechanisms.md` 与 `docs/example/real-package-structure.md`，记录告警 metadata、双计数口径、中英文映射扩展点、合成样例结构及历史 `alarm.flapping` 边界
- [ ] T032 对只读输入 `output/task-all_20261031173253/alarm/alarm_history_20261031173253717.csv` 和 `alarm_history_20261031173255511.csv` 在运行前后核对 SHA-256、大小和 mtime，记录两条规则耗时并确认未复制、移动、修改或提交真实数据
- [ ] T033 使用只读真实告警验收 `alarm.active_state`，核对活动记录 16（Critical 1、Major 11、Minor 4）、活动原始重复 41,776、活动估算上报 41,792、最大单条重复 41,695、失败文件 0、覆盖末刻 `2026-10-31T09:15:23+00:00`
- [ ] T034 使用同一只读真实告警验收 `alarm.recurrence`，核对生命周期 2,209、类型 44、应用 2、状态 Not Cleared 16/Normal Cleared 2,179/Reset Cleared 14、重复大于 0 的 584 条、原始重复 43,762、估算上报 45,971，以及 `137611`、`135203` 和未清除安全类告警基线
- [ ] T035 执行 `.venv/bin/python build.py lint` 与 `.venv/bin/python build.py test`，确认后端规则、报告、扫描、CLI/API 和代表性样例全部通过
- [ ] T036 执行 `.venv/bin/python build.py verify`、`.venv/bin/python build.py web-build`、`cd web && npm test` 和 `cd web && npx playwright test e2e/alarm-active-recurrence.spec.ts`，确认全流程与页面闭环
- [ ] T037 检查本功能不修改 `docs/api/openapi.yaml` 或公共 `RuleResult`/`Metric`/`Finding` Schema；若实现阶段出现 API 契约变化，立即停止并回到规划，按 OpenAPI 优先流程执行 `contract` 与 `gen-web-api`
- [ ] T038 执行 `git status --short`、`git diff --check`、`git diff --cached --name-status`，仅暂存本功能明确文件，确认候选不包含 `uploads/`、`output/`、真实包、日志、报告、截图、临时验收产物或主工作区 KPI 改动

---

## 依赖与执行顺序

### 阶段依赖

- **设置 T001**：必须先于所有源码和测试修改。
- **基础层 T002-T009**：依赖 T001；完成前不得开始 US1/US2。
- **US1 T010-T017**：依赖 T009；可独立于 US2 交付。
- **US2 T018-T024**：依赖 T009；可独立于 US1 实现和验证。
- **收尾 T025-T038**：依赖所需用户故事；T032-T034 依赖两条规则均完成；T035-T038 依赖所有代码和文档完成。

### 用户故事依赖

- **US1（P1）**：仅依赖公共解析器、`alarm_all` 和自身规则/UI/报告，不依赖 `alarm.recurrence`。
- **US2（P1）**：仅依赖公共解析器、`alarm_all` 和自身规则/UI，不依赖 `alarm.active_state`。
- 两条规则不得互相导入、调用、读取对方 JSON 或消费 prepared 数据。

### 并行机会

- T002、T003、T004、T005、T006 可由不同成员并行，文件集合互不重叠。
- 基础上线后，US1 与 US2 可由不同成员并行；各自测试任务 T010-T012 与 T018-T020 可先并行编写。
- 收尾中的 T025、T026、T027、T028、T030、T031 可在对应实现稳定后并行。
- 同一文件任务必须串行：`RuleDetailPage.tsx` 的 T015/T023，规则自动发现的 T007/T008，报告模板的 T012/T016。

## 并行示例：用户故事 1

```text
任务 A：编写 tests/test_alarm_active_state.py
任务 B：编写 web/src/components/AlarmActiveStatePanel.test.tsx
任务 C：编写 tests/test_alarm_recurrence_report.py
```

## 并行示例：用户故事 2

```text
任务 A：编写 tests/test_alarm_recurrence.py
任务 B：编写 web/src/components/AlarmRecurrencePanel.test.tsx
任务 C：编写 web/e2e/alarm-active-recurrence.spec.ts
```

## 实现策略

### MVP 优先

1. 完成 T001-T009 的隔离现场、扫描组、中英文解析和合成样例。
2. 完成 T010-T017 的 US1。
3. 停止并独立验证活动告警规则、详情面板和报告。
4. 再完成 US2 和两条规则的全流程验收。

### 增量交付

1. 基础层完成 → 解析器与扫描范围稳定。
2. US1 完成 → 值班人员先获得“当前未清除风险”闭环。
3. US2 完成 → 补齐“生命周期反复 + 单条重复上报”闭环。
4. 收尾完成 → 注册、样例、报告、文档、真实数据与质量门禁全部有证据。
