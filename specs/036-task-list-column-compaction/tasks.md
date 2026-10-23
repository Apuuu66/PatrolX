---
description: "任务列表列宽压缩 — 实现任务清单"
---

# 任务：任务列表列宽压缩

**输入**：来自 `specs/036-task-list-column-compaction/` 的设计文档

**前置条件**：spec.md、plan.md、research.md、data-model.md、contracts/task-list-compaction.md、quickstart.md

**测试**：本清单包含测试任务。按 AGENTS.md 与 Superpowers 要求先写失败测试（TDD）再补实现；前端能力包含覆盖完整入口到关键结果的 E2E。

**组织方式**：按用户故事分组，每个故事可独立实现、独立测试、独立演示。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1~US3）
- 描述中包含精确的文件路径与对应 FR / SC / 契约编号

## 路径约定

仓库根目录：`app/`、`web/`、`tests/`、`docs/`、`specs/`。规划产物已在 `main` 主工作区完成；实现与测试全部在实现分支 worktree `.worktrees/feature-036-task-list-column-compaction` 内完成，不得在主工作区改实现文件。

本轮只改前端展示层与 `docs/design/DESIGN.md`，不改 OpenAPI、后端数据模型、执行编排与巡检规则，不新增依赖，不改分页 / 筛选 / 轮询 / 上传 / 操作语义。

---

## 阶段 1：设置（实现环境）

- [ ] T001 从已提交规划产物的 `main` 创建实现分支 `feature-036-task-list-column-compaction` 与 worktree `.worktrees/feature-036-task-list-column-compaction`；执行 `git worktree list` 与 `git branch --show-current` 并确认：当前目录是实现 worktree、检出分支正确、Speckit 产物已在 `main` 提交、已有 worktree 时复用；在回合报告记录检查结果（阻塞全部后续任务；AGENTS.md 实现前置检查）

**检查点**：前置检查四条全部满足。

---

## 阶段 2：基础层（无，纯展示层改动）

本功能不引入共享基础设施。列定义、时间格式化与元数据收纳均在 US1 / US3 内直接完成，US2 只补回归保护。

---

## 阶段 3：用户故事 1 - 一屏看全任务行（优先级：P1）🎯 MVP

**目标**：任务列表收敛为 6 列共 1160px，时间三列合一；1440×900 下不出现表格内部横向滚动，1280 / 1440 / 1920 页面级横向滚动为 0。

**独立测试**：1440 视口打开任务列表，断言 6 个列头与列顺序、`table.scrollWidth <= table.clientWidth`、时间三段同处 `task-time` 单元格且无完整时间戳文本；1280 / 1920 复用页面级滚动断言。

### 测试先行（必须先失败）

- [ ] T002 [P] [US1] 在 `web/src/pages/TaskListPage.test.tsx` 改写时间相关用例为"合并列"结构：断言 `data-testid="task-time"` 单元格同时包含 `task-duration` / `task-last-run` / `task-created-at`，断言不存在独立的"创建时间 / 最后运行 / 任务时长"列头，保留运行中与从未运行的既有取值覆盖（FR-006、FR-009、FR-010、SC-003；契约 §1、§2）
- [ ] T003 [P] [US1] 在 `web/e2e/task-home.spec.ts` 新增 1440×900 用例：任务列表列头为 6 个且顺序正确、`.task-table` 不出现内部横向滚动、页面级横向滚动为 0（FR-001、FR-002、FR-004、SC-001、SC-002）

### 实现

- [ ] T004 [US1] 在 `web/src/pages/TaskListPage.tsx` 合并「创建时间 / 最后运行 / 任务时长」三列为单个「时间」列（key `time`，width 160），单元格标记 `data-testid="task-time"`，内部按"耗时 → 最后运行时间 → 创建时间"顺序渲染并保留原有三个 testid（FR-006~FR-010；契约 §2）
- [ ] T005 [US1] 在 `web/src/pages/TaskListPage.tsx` 收敛其余列宽与 `scroll.x`：任务 240 / 状态摘要 160 / 数据准备 170 / 元数据 150 / 时间 160 / 操作 280，`scroll={{ x: 1160 }}`（FR-001、FR-002、FR-003；契约 §1）
- [ ] T006 [US1] 在 `web/src/theme.css` 为合并时间列与表格布局补样式：`.task-table table { table-layout: fixed; }`、`[data-testid="task-time"]` 内单列不换行、耗时主色、创建时间弱化色、整列等宽数字（FR-009；契约 §1、§2）
- [ ] T007 [US1] 运行 `cd web && npx vitest run src/pages/TaskListPage.test.tsx` 与 `npx playwright test e2e/task-home.spec.ts`，确认 1440 无内部滚动；若仍滚动，按 research R2 先降元数据平铺项或数据准备列宽，不得压缩操作列（SC-001）

**检查点**：US1 可独立演示——1440×900 一屏看全全部列与时间三段信息。

---

## 阶段 4：用户故事 2 - 关键操作始终可达（优先级：P1）

**目标**：列压缩后操作列仍固定右侧、280px、单行平铺，无"重跑"、无 `⋯` 菜单、二次确认保留。

**独立测试**：1280 与 1440 视口下断言操作列贴右、按钮数量与文案、无换行；沿用既有删除 / 重建确认用例。

- [ ] T008 [P] [US2] 在 `web/e2e/task-home.spec.ts` 补操作列回归断言：1280 视口横向滚动后仍能看到右侧固定操作列、按钮无换行、无"重跑"与 `⋯` 菜单（FR-015、FR-016、SC-004；契约 §4）
- [ ] T009 [US2] 在 `web/src/pages/TaskListPage.tsx` 复核并为操作列补显式约束（宽度 280、`fixed: "right"`、`white-space: nowrap`），确保列压缩与 `table-layout: fixed` 未影响 sticky 定位（FR-003、FR-015；契约 §1、§4）
- [ ] T010 [US2] 运行 `cd web && npx playwright test e2e/task-actions.spec.ts e2e/task-delete-confirm.spec.ts e2e/task-home.spec.ts`，确认操作入口、删除失败重试与二次确认未被列压缩破坏（FR-016、SC-005）

**检查点**：US1 + US2 同时可用——压缩与操作可达性不互相牺牲。

---

## 阶段 5：用户故事 3 - 元数据可收纳但不丢失（优先级：P2）

**目标**：任务列表元数据平铺 3 项，其余进入带项数的"更多元数据"Popover；空值不渲染、行高不变；详情页 Hero 仍为 4 项。

**独立测试**：含 5 项有值元数据的任务平铺 3 项 + "更多元数据（2）"，展开可读全部字段；元数据缺失任务不出现占位横线。

### 测试先行

- [ ] T011 [P] [US3] 在 `web/src/pages/TaskListPage.test.tsx` 新增用例：5 项元数据平铺 3 项、`metadata-more` 入口文案含 `2`、展开后剩余字段可见；全空元数据不渲染占位（FR-011~FR-013、SC-006）
- [ ] T012 [P] [US3] 在 `web/src/components/MetadataList.test.tsx`（不存在则新建）补组件默认值回归：不传 `maxVisible` 时仍平铺 4 项，锁定详情页行为不被列表压缩牵连（FR-014；契约 §3）

### 实现

- [ ] T013 [US3] 在 `web/src/pages/TaskListPage.tsx` 将元数据列 `MetadataList` 的 `maxVisible` 由 5 改为 3，并更新对应注释为当前契约（FR-011、FR-014；契约 §3）
- [ ] T014 [US3] 在 `web/e2e/task-home.spec.ts` 新增元数据收纳 E2E：平铺项数、更多入口展开后的字段可见性与可复制文案（FR-011、FR-012、SC-006）
- [ ] T015 [US3] 运行 `cd web && npx vitest run` 与 `npx playwright test e2e/task-home.spec.ts`，确认元数据收纳与行高稳定（FR-013、SC-006）

**检查点**：三个用户故事全部独立可用。

---

## 阶段 6：收尾与横切

- [ ] T016 更新 `docs/design/DESIGN.md`：Task List 章节改为 6 列与固定宽度预算（任务 240 / 状态摘要 160 / 数据准备 170 / 元数据 150 / 时间 160 / 操作 280）、时间列三段式层级、元数据任务列表平铺 3 项、1440 无内部横向滚动与 1280 允许内部滚动的口径；在 2026-10-23 修订记录中说明本次变更（FR-021；契约 §1~§3）
- [ ] T017 [P] 复核 `specs/031-ui-information-hierarchy/contracts/ui-baseline.md` §4.1 与 `specs/033-ui-refinement/contracts/ui-refinement.md` §3：以 036 契约为准的列定义处补注"036 修订了任务列表物理列与宽度，见 `specs/036-task-list-column-compaction/contracts/task-list-compaction.md`"，避免文档分叉（FR-021）
- [ ] T018 执行完整门禁：`.venv/bin/python build.py lint`、`.venv/bin/python build.py test`、`.venv/bin/python build.py web-build`、`.venv/bin/python build.py e2e`；在实现 worktree 内补 `specs/036-task-list-column-compaction/verification.md` 记录命令、结果与截图路径（SC-007、SC-008）

---

## 依赖与执行顺序

- **T001** 阻塞全部任务（AGENTS.md 实现前置检查）。
- US1（T002~T007）是 MVP，必须先完成；T004/T005/T006 同文件或紧邻样式，按顺序执行。
- US2（T008~T010）依赖 T005 的列宽落地；T009 只做约束复核，若实现已满足则不产生无效 diff。
- US3（T011~T015）与 US1 共用 `TaskListPage.tsx`，须在 T004/T005 后执行，避免同文件冲突。
- 收尾（T016~T018）依赖全部用户故事完成；T017 与 T018 中的文档改动在不同文件，可并行。

## 并行机会

- T002 与 T003 可并行（不同测试文件）。
- T011 与 T012 可并行（不同测试文件）。
- T016 与 T017 可并行（不同文档文件）。
- 实现类任务集中在 `TaskListPage.tsx` / `theme.css`，不做并行拆分。

## 实现策略

1. 先做 US1（T002→T007）并实测 1440 视口，确认无内部横向滚动后再继续。
2. 再做 US3（T011→T015）的元数据收纳，因为它与列宽预算互相影响；若 1440 出现滚动，优先在此处回调平铺项数。
3. US2（T008~T010）作为操作可达性回归保护，在列宽定稿后执行。
4. 最后跑 T016~T018 的文档回写与全量门禁。
