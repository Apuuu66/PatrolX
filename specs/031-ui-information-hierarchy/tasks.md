---
description: "主界面信息层级重构（巡检控制台方向） — 实现任务清单"
---

# 任务：主界面信息层级重构（巡检控制台方向）

**输入**：来自 `specs/031-ui-information-hierarchy/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/ui-baseline.md、quickstart.md

**测试**：本清单包含测试任务；每个用户故事先写失败测试，再补实现（TDD）。前端新功能必须包含覆盖完整入口到关键结果的 E2E。

**组织方式**：按用户故事分组，每个故事可独立实现与验证。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1/US2/US3/US4）
- 描述中包含精确的文件路径

## 路径约定

仓库根目录：`web/`、`docs/`、`specs/`。规划产物已在 `main` 主工作区完成并提交；实现与测试全部在实现分支 worktree `.worktrees/feature/031-ui-information-hierarchy` 内完成，不得在主工作区改实现文件。

---

## 阶段 1：设置（实现环境与共享脚手架）

**目的**：建立实现 worktree，并落地视觉基线的单一来源

- [X] T001 从已提交规划产物的 `main` 创建实现分支 `feature/031-ui-information-hierarchy` 与 worktree `.worktrees/feature/031-ui-information-hierarchy`；执行 `git worktree list` 与 `git branch --show-current` 前置检查并在回合报告记录结果（阻塞全部后续任务；AGENTS.md 实现前置检查）
- [X] T002 [P] 在 `web/src/theme.css` 建立基线语义变量层（字号层级、区块间距、状态软色），间距沿用既有 `--space-1..5` 与 `--radius-round`；不新增依赖（R1、contracts/ui-baseline §1）
- [X] T003 [P] 在 `web/src/App.tsx` 的 `ConfigProvider` 补齐 token（字号层级、次要边框色），保持 `colorPrimary: #1677ff`、`borderRadius: 8`、`colorBgLayout: #f5f5f5` 不变（R1、FR-001）
- [X] T004 [P] 新增 `web/src/components/PageHeader.tsx`：统一页头（16px/600 标题 + 12px 说明 + 状态区 slot + 操作区 slot，最多 1 个主操作）（FR-001、FR-004、contracts/ui-baseline §1/§3）

**检查点**：基线变量与 `PageHeader` 可用，既有页面样式无回归。

---

## 阶段 2：基础层（阻塞全部用户故事）

**目的**：结论推导与状态摘要成为可单测的共享能力，避免列表与详情各写一份

- [X] T005 [P] 先写失败单测 `web/src/utils/taskConclusion.test.ts`：覆盖任务失败 / 排队中 / 执行中 / fail+error / 仅 warn / 全通过 / 空 stats 七个分支（R4、data-model §2）
- [X] T006 实现 `web/src/utils/taskConclusion.ts` 的 `deriveTaskConclusion`（推导优先级严格按 data-model §2；只消费既有字段，不得解析后端文案）（依赖 T005）
- [X] T007 [P] 先写失败单测 `web/src/components/StatusDistribution.test.tsx`：0 值不渲染、五态全 0 渲染空态、`percent` 计算（FR-003、FR-009、data-model 校验规则）
- [X] T008 实现 `web/src/components/StatusDistribution.tsx`：分段条 + 非零计数，紧凑/完整两形态，复用 `getHealthBarSegments` 与 `RESULT_STATUS_META`；五态文字标签必须与非零状态一同呈现，不得只依赖颜色（FR-002、FR-003、依赖 T007）
- [X] T009 [P] 新增 `web/src/components/MetadataList.tsx`：轻量键值元数据（label 次要色 + value 主色，4px 间距，不产生彩色 Tag 噪音）；复用 `getTaskMetadataTags` 输出（DESIGN.md Metadata Tag）

**检查点**：`deriveTaskConclusion`、`StatusDistribution`、`MetadataList` 单测通过；四个用户故事可以开始。

---

## 阶段 3：用户故事 1 - 任务列表异常置顶（优先级：P1）🎯 MVP

**目标**：任务列表变成单一表行式列表，失败/异常任务置顶且行内可见原因摘要，正常任务只保留非零状态信息。

**独立测试**：`cd web && npx playwright test e2e/task-home.spec.ts e2e/task-actions.spec.ts e2e/task-delete-confirm.spec.ts`；Unit：`npm run test`。

- [X] T010 [P] [US1] 在 `web/e2e/task-home.spec.ts` 中先写新断言：行式表格形态、失败任务第一行、行内失败原因摘要、状态摘要无彩色 0 值、首屏可见概览条与 4 条种子任务、从失败任务行到失败规则详情不超过 3 次点击（SC-001、SC-003、SC-004、FR-006~FR-009）
- [X] T011 [US1] 在 `web/src/pages/TaskListPage.tsx` 用 AntD `Table` 重写列表容器：列顺序「任务（名称+状态+ID+失败原因摘要）→ 状态摘要 → 元数据 → 时间与耗时 → 操作」，保留状态筛选、搜索、分页默认 10、轮询与上传表单（FR-006、FR-013、FR-026）
- [X] T012 [US1] 在 `web/src/utils/taskListSort.ts` 实现默认排序纯函数并接入列表：`failed → running → pending → completed`，`completed` 且 `fail + error > 0` 视为异常提前；同优先级按 `created_at` 倒序；不新增排序控件（FR-007、Clarifications）
- [X] T013 [US1] 在 `web/src/pages/TaskListPage.tsx` 用 `StatusDistribution` + `MetadataList` 渲染状态摘要与元数据，失败任务行直接渲染原因摘要（复用 `taskFailure` 展示工具）；空状态保留"上传数据包"主入口（FR-008、FR-009、边界情况）
- [X] T014 [US1] 在 `web/src/pages/TaskListPage.tsx` 实现操作分层：行主操作"详情"；次要操作"报告""失败日志"；重跑 / 增量重建 / 全量重建 / 删除收进 `⋯` 菜单，删除与全量重建保持二次确认；删除失败错误改为行内/展开区表达，保留 `TaskDeleteError` 语义（FR-012、FR-004）
- [X] T015 [US1] 在 `web/src/pages/TaskListPage.tsx` 实现行展开区：数据准备状态、问题文件摘要与重试入口、失败日志入口（FR-011）
- [X] T016 [US1] 在 `web/src/pages/TaskListPage.tsx` 实现顶部概览条（任务总量 + 状态分布 + 注册规则 / 规则结果 / 发现数），替换等权数字组（含注册规则 / 规则结果 / 发现问题数；FR-010、边界情况："全部正常"不得出现高权重提示）
- [X] T017 [P] [US1] 补充单测 `web/src/utils/taskListSort.test.ts` 与 `web/src/pages/TaskListPage.test.tsx`：异常置顶、同状态倒序、0 值不渲染、分页默认 10（T012/T013 完成后）
- [X] T018 [US1] 等价迁移既有 E2E：`web/e2e/task-actions.spec.ts`、`web/e2e/task-delete-confirm.spec.ts`，更新选择器但保留全部行为覆盖（FR-030）

**检查点**：任务列表行式化且异常置顶；删除二次确认、重建、筛选、搜索、分页、轮询行为与迁移前等价。

---

## 阶段 4：用户故事 2 - 任务详情首屏结论（优先级：P1）

**目标**：打开任务详情首屏就知道"有没有问题、下一步做什么"，删除重复表达。

**独立测试**：`cd web && npx playwright test e2e/task-detail.spec.ts e2e/task-detail-states.spec.ts e2e/task-detail-tabs.spec.ts e2e/task-detail-filter.spec.ts e2e/task-detail-rule-browser.spec.ts e2e/task-detail-rule-rerun.spec.ts`。

- [X] T019 [P] [US2] 迁移并扩展 `web/e2e/task-detail.spec.ts`、`web/e2e/task-detail-states.spec.ts`：结论 Hero 首屏元素（标签 / 一句话 / 状态计数 / 主操作 / 关键元数据）、全通过任务、解压失败任务（SC-002、SC-005、FR-014~FR-019）
- [X] T020 [US2] 新增 `web/src/components/ConclusionHero.tsx`：渲染 `deriveTaskConclusion` 结论 + 状态计数 + 主操作 + 关键元数据；任务失败时展示失败原因与阶段并给失败日志入口；执行中禁用报告并说明原因（依赖 T006；FR-014、FR-015、FR-019、SC-002）
- [X] T021 [US2] 重构 `web/src/pages/TaskDetailPage.tsx` 顶层顺序：面包屑 → 结论 Hero → 重点关注 → 全部规则 → 既有 Tab（执行日志 / 设备台账 / 报告预览）→ 折叠执行与技术信息（展开后可查看完整字段并复制，FR-005、FR-016~FR-018、R5）
- [X] T022 [US2] 调整 `web/src/components/task-detail/TaskHealthPanel.tsx`：删除与"重点关注"重复的 Alert 提示条，改为可点选状态计数块（保留状态筛选联动）；`web/src/components/SummaryCards.tsx` 在详情页改为概览条形态，不得出现第二组等权大数字（FR-016、SC-005、R5）
- [X] T023 [US2] 在 `web/src/pages/TaskDetailPage.tsx` 实现"重点关注"列表：fail → warn 排序、最多 5 条 + 其余折叠、每条可跳规则详情（FR-016、data-model §4）
- [X] T024 [US2] 在 `web/src/pages/TaskDetailPage.tsx` 将全部规则按类别分组折叠，默认展开含异常的分组；保留搜索、排序、类别筛选与单规则重跑（FR-017、FR-026）
- [X] T025 [US2] 主包解压失败任务在 `web/src/pages/TaskDetailPage.tsx` 不渲染空规则表格，改为失败阶段 + 原因 + 日志入口；`skip` 规则必须可见原因（边界情况、FR-019）
- [X] T026 [P] [US2] 补充单测 `web/src/components/ConclusionHero.test.tsx` 与 `web/src/pages/TaskDetailPage.test.tsx`：Hero 渲染、解压失败无规则表、详情页不出现重复提示条（T020~T025 完成后）
- [X] T027 [US2] 等价迁移既有 E2E：`web/e2e/task-detail-tabs.spec.ts`、`web/e2e/task-detail-filter.spec.ts`、`web/e2e/task-detail-rule-browser.spec.ts`、`web/e2e/task-detail-rule-rerun.spec.ts`（FR-030）

**检查点**：详情首屏结论完整；同一事实不重复表达；筛选、排序、单规则重跑、设备编辑、重建保持可用。

---

## 阶段 5：用户故事 3 - 规则详情"结论 → 证据 → 建议"（优先级：P2）

**目标**：规则详情首屏直接回答"结论是什么、要不要处理"，证据向下展开。

**独立测试**：`cd web && npx playwright test e2e/alarm-flapping-rule-detail.spec.ts`。

- [ ] T028 [P] [US3] 迁移并扩展 `web/e2e/alarm-flapping-rule-detail.spec.ts`：结论与建议首屏可见、证据顺序、"显示全部列"切换、skip 原因可见（FR-020~FR-023）
- [ ] T029 [US3] 重构 `web/src/pages/RuleDetailPage.tsx` 顺序：结论 + 建议 → 源文件匹配 → 发现 → 证据面板（`MetricPanel` / `MeasurementInspectionPanel` / `AlarmFlappingPanel` 按条件渲染）→ 折叠技术信息（展开后可查看完整字段并复制，FR-005、FR-020、R6）
- [ ] T030 [US3] 在 `web/src/pages/RuleDetailPage.tsx` 保证 `skip` 必显 `skip_reason`（为空时给兜底文案），不得静默通过（FR-021、边界情况）
- [ ] T031 [US3] 在 `web/src/pages/RuleDetailPage.tsx` 将指标表默认精简列并保留"显示全部列"切换；不改面板内部判定与数据来源（FR-022、R6）
- [ ] T032 [US3] 在 `web/src/pages/RuleDetailPage.tsx` 把单规则重跑入口上移到首屏，保持进行中状态可见与完成仅刷新本页结果（FR-023）
- [ ] T033 [P] [US3] 补充单测 `web/src/pages/RuleDetailPage.test.tsx`：区块顺序、skip 原因渲染、精简列默认值（T029~T032 完成后）

**检查点**：规则详情顺序符合契约；skip 原因可见；重跑入口首屏可及。

---

## 阶段 6：用户故事 4 - 其余主页面统一基线（优先级：P3）

**目标**：其余页面套用统一视觉基线，不改信息架构与功能语义。

**独立测试**：`cd web && npx playwright test e2e/inventory.spec.ts e2e/page-states.spec.ts`；逐页对照 `contracts/ui-baseline.md` 走查。

- [ ] T034 [US4] `web/src/pages/InventoryPage.tsx` 与 `web/src/pages/InventoryDevicePage.tsx` 套用 `PageHeader` 与统一卡片/状态标签，并把默认分页 20 → 10（FR-024、宪法"数据分页默认"）
- [ ] T035 [P] [US4] `web/src/pages/MeasurementUnitsPage.tsx`、`web/src/pages/InspectorsPage.tsx`、`web/src/pages/DictsPage.tsx` 套用基线（页头、操作分层、状态标签），不重排信息架构（FR-024、FR-025）
- [ ] T036 [P] [US4] `web/src/pages/ReportPage.tsx`、`web/src/pages/LogsPage.tsx` 套用基线，保留报告与日志既有能力（FR-024、FR-025）
- [ ] T037 [P] [US4] `web/src/pages/UsersPage.tsx` 套用基线，保持分页默认 10（FR-024）
- [ ] T038 [US4] 统一空 / 加载 / 错误态：复用 `web/src/components/PageState.tsx`，页面级用骨架屏、局部刷新用轻量 loading，错误态提供统一重试入口；列表为空时必须给出下一步动作（FR-024、contracts/ui-baseline §5）
- [ ] T039 [P] [US4] 补充单测：`web/src/pages/InventoryPage.test.tsx` 与 `web/src/pages/InventoryDevicePage.test.tsx` 断言默认分页 10（T034 完成后）
- [ ] T040 [P] [US4] 在 `web/e2e/inventory.spec.ts`、`web/e2e/page-states.spec.ts` 增加基线断言（页头结构、状态标签、空 / 加载 / 错误态至少 1 页自动化）（SC-006）

**检查点**：其余 7 个页面逐页走查通过基线清单，至少 1 页有自动化断言。

---

## 阶段 7：收尾与横切关注点

- [ ] T041 回写 `docs/design/DESIGN.md`：字号与间距刻度、结论区规范、状态分布 0 值规则、操作分层、行式任务列表模式与四类页面模式（FR-001、R9）
- [ ] T042 [P] 运行 `python build.py web-build`，修复类型/构建错误（均须在 worktree 内）
- [ ] T043 [P] 运行 `python build.py lint` 与 `python build.py test`，全绿
- [ ] T044 运行 `python build.py e2e` 全量通过（自动起 8010/5183，加载种子任务）
- [ ] T045 归档 1440×900 截图到 `web/e2e/screenshots/`：任务列表 / 任务详情 / 规则详情 / 1 个基线页面（本地证据，不提交；在实现回合报告中列出截图清单与对应 SC，如需长期保留由用户另行决定是否加入 `.gitignore`）（SC-007、quickstart §4）
- [ ] T046 运行 `python build.py verify` 用真实样例包复现同一界面结论，并核对 `output/<task_id>/` 报告一致性（SC-007、quickstart §4）
- [ ] T047 逐页走查并记录 SC-001~SC-006 复现结果（首屏可见性、异常置顶、点击次数、无重复表达、基线清单），并在 1280px 与 1920px 视口确认无横向滚动、内容不被无限拉伸（FR-028）
- [ ] T048 越界与洁净度检查：`git status` 与 `git diff --stat` 确认未改 `docs/api/openapi.yaml`、未改后端、未新增依赖与路由；未暂存 `web/.tmp-show-detail.mjs`、`web/.tmp-show-updates.mjs` 与 `web/e2e/screenshots/`（FR-027、FR-029、AGENTS.md 推送约定）

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：需要实现 worktree 已创建（T001 阻塞全部）
- **基础层（阶段 2）**：依赖 T002~T004；阻塞全部用户故事
- **用户故事（阶段 3~6）**：均依赖基础层完成，可并行推进或按 P1 → P2 → P3 顺序执行
- **收尾（阶段 7）**：依赖所有纳入本轮的阶段完成

### 用户故事依赖

- **US1（P1，MVP）**：依赖基础层，不依赖其他故事（列表概览条在 T016 完成后闭环）
- **US2（P1）**：依赖基础层与 US1 的 `StatusDistribution`（T008），但可独立测试
- **US3（P2）**：依赖基础层，可独立测试
- **US4（P3）**：依赖基础层，可独立测试

### 每个用户故事内部

- 测试先于实现（TDD）：T005→T006、T007→T008、T010→T011~T016
- 共享组件先于页面：T020 先于 T021；T029 先于 T030~T032
- 单文件内的任务（如 `TaskListPage.tsx`）按编号顺序串行执行

### 并行机会

- 阶段 1 的 T002~T004 可并行
- 阶段 2 的 T005/T007/T009 可并行
- 基础层完成后 US1/US3/US4 可并行；US2 与 US1 共享 `StatusDistribution` 但无写冲突
- 阶段 6 的 T035~T037 可并行（不同页面文件）
- 收尾的 T042/T043 可并行

---

## 并行示例：用户故事 4

```bash
# 并行推进三个不同页面的基线统一：
Task: "在 web/src/pages/MeasurementUnitsPage.tsx / InspectorsPage.tsx / DictsPage.tsx 套用基线（T035）"
Task: "在 web/src/pages/ReportPage.tsx / LogsPage.tsx 套用基线（T036）"
Task: "在 web/src/pages/UsersPage.tsx 套用基线（T037）"
```

---

## 实现策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：设置（含 worktree 前置检查）
2. 完成阶段 2：基础层（阻塞全部故事）
3. 完成阶段 3：US1
4. **停止并验证**：`npx playwright test e2e/task-home.spec.ts e2e/task-actions.spec.ts e2e/task-delete-confirm.spec.ts`
5. 演示/截图任务列表新形态

### 增量交付

1. 设置 + 基础层 → 基线就绪
2. US1 → 独立测试 → 演示（MVP）
3. US2 → 独立测试 → 演示
4. US3 → 独立测试 → 演示
5. US4 → 逐页走查 → 演示
6. 收尾：DESIGN.md 回写 + 全量门禁 + 截图证据

### 质量门禁（每个用户故事完成后）

```bash
python build.py web-build
python build.py lint
python build.py test
python build.py e2e
```

任一门禁失败不得进入下一故事；前端结构变化只允许等价替换测试断言，不得删除既有覆盖。
