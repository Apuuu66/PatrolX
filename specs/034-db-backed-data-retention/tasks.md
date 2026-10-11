---
description: "任务数据长期留存与磁盘现场治理 — 实现任务清单"
---

# 任务：任务数据长期留存与磁盘现场治理

**输入**：来自 `specs/034-db-backed-data-retention/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/api-delta.md、quickstart.md

**测试**：本清单包含测试任务。按 AGENTS.md 与 Superpowers 要求先写失败测试（TDD）再补实现；前端新增能力包含覆盖完整入口到关键结果的 E2E。

**组织方式**：按用户故事分组，每个故事可独立实现、独立测试、独立演示。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1~US4）
- 描述中包含精确的文件路径与对应 FR / SC / R 编号，数据模型约束逐字引用

## 路径约定

仓库根目录：`app/`、`web/`、`tests/`、`docs/`、`specs/`。规划产物已在 `main` 主工作区完成；实现与测试全部在实现分支 worktree `.worktrees/feature-034-db-backed-data-retention` 内完成，不得在主工作区改实现文件。

本轮不改巡检规则判定逻辑与执行编排（EXTRACT → PREPARE → INSPECT），不改 `rule_version`，不新增依赖。

**样例包判定**：本特性不新增巡检数据语义，代表性样例包内容不变，**不扩充** `tests/fixtures/make_real_package.py`；展示效果由"代表性样例包派生多任务 + 51 任务清理场景"的 E2E 种子复现（与 033 同一判定口径，R10 / SC-002）。

---

## 阶段 1：设置（实现环境与契约先行）

**目的**：完成实现前置检查，先落契约与治理修正，再动实现

- [ ] T001 从已提交规划产物的 `main` 创建实现分支 `feature/034-db-backed-data-retention` 与 worktree `.worktrees/feature-034-db-backed-data-retention`；执行 `git worktree list` 与 `git branch --show-current` 并确认：当前目录是实现 worktree、检出分支正确、Speckit 产物已在 `main` 提交、未与其他 worktree 分支冲突；在回合报告记录检查结果（阻塞全部后续任务；AGENTS.md 实现前置检查）
- [ ] T002 更新 `docs/api/openapi.yaml`：`InspectionTask` / `TaskSummary` 增可选 `last_run_at`（string(date-time) | null）与 `duration_ms`（integer | null，`>= 0`）；新增错误码 `scene_cleaned`（410）与 `device_not_found`（400）；补 `GET /api/v2/tasks/{task_id}/report`、`GET /api/v2/tasks/{task_id}/logs`、`POST /api/v2/tasks/{task_id}/rerun`、`POST /api/v2/tasks/{task_id}/rebuild` 的 410 响应描述；补 `POST /api/v3/tasks` 同名恢复语义（FR-008、FR-009、FR-011、FR-013、contracts/api-delta.md）
- [ ] T003 [P] 修正 `.specify/memory/constitution.md` §存储与运行时数据，版本 2.9.0 → 2.10.0（MINOR）：磁盘现场按留存策略保留（最近 50 个任务 ∪ 执行中任务）、界面展示数据长期保留在 SQLite、删除任务仍级联删除 `uploads/<task_id>/` 与 `output/<task_id>/`（FR-002、FR-004；plan.md 门禁条件，实现合入前必须完成）
- [ ] T004 执行 `python build.py gen-web-api` 重新生成 `web/src/api/`，确认 diff 仅包含新增字段与错误描述，未手写任何前端 API 调用（依赖 T002；AGENTS.md 契约约定）

**检查点**：前置检查四条全部满足、契约与治理修正已落、前端客户端已再生成，后续任务方可开始。

---

## 阶段 2：基础层（阻塞全部用户故事）

**目的**：迁移、新表与两个新服务先行，作为全部故事共享的基础设施

- [ ] T005 在 `app/models/db.py` 为 `tasks` 表增量新增 `last_run_at`（DateTime(timezone)，可空）、`duration_ms`（Integer，可空）、`package_checksum`（String(64)，可空）、`preparation`（JSON，可空）四列，沿用既有 `_ensure_task_columns` 的 `ALTER TABLE ADD COLUMN` 模式；旧行新列全部为 NULL（data-model §2、R3）
- [ ] T006 在 `app/models/db.py` 新增 `task_rule_results` 表：`task_id`（索引）、`rule_code`、`priority`、`execution_order`、`status`（索引）、`severity`、`executed_at`、`finding_count`（默认 0）、`result`（完整 `RuleResult` 契约 JSON）、`updated_at`（UTC）；约束 `UNIQUE(task_id, rule_code)`（data-model §3、R1）
- [ ] T007 在 `app/models/db.py` 新增 `task_kpi_points` 表：`task_id`、`rule_code`、`measurement_unit_id`、`metric_resource_id`、`object_key`、`period_minutes`、`measured_at`、`value`、`source_file`、`line_number`，字段与 `output/<task_id>/kpi/history/index.jsonl` 一一对应，缺失字段以 NULL 保留记录；`task_id` / `measurement_unit_id` / `metric_resource_id` / `object_key` / `measured_at` 建索引（data-model §4、R2）
- [ ] T008 在 `app/models/schemas.py` 为 `InspectionTask` 增可选 `last_run_at: datetime | None` 与 `duration_ms: int | None`（`>= 0`），`TaskSummary` 继承可见；时间 UTC、`*_at` 命名（FR-008、FR-009、contracts/api-delta.md）
- [ ] T009 新增 `app/services/task_db.py` 作为 DB 读写唯一入口：`publish_snapshot`（单事务内整批替换本任务 `task_rule_results` 与 `task_kpi_points`，先删后插）、`get_task_summary` / `list_tasks` / `get_rule_result` / `list_rule_results` / 概览聚合查询、`save_run_start` / `save_run_end` 运行字段写入（data-model §2~§5、R1、R2、R5）
- [ ] T010 在 `app/services/task_db.py` 实现启动幂等回填：扫描 `output/*/task.json`，`tasks` 表中已存在的 task_id 直接跳过；未入库任务导入任务行、`rules/*.json` → `task_rule_results`、`kpi/history/index.jsonl` → `task_kpi_points`；单个损坏文件跳过并记录 structlog 日志，不中断启动（data-model §7、R4）
- [ ] T011 新增 `app/services/retention.py`：保留集合 = 按 `COALESCE(last_run_at, created_at)` 倒序前 50 个任务 ∪ 所有 `pending`/`running` 任务；清理 `uploads/` 与 `output/` 下不在保留集合的 `<task_id>` 目录、以及 `uploads/` 根目录中可派生已知 task_id 的散包（未消费散包不删除）；只删磁盘不碰 DB；删除失败记录日志供下次任务结束时重试（FR-004、FR-005、FR-006、data-model §6、R6）
- [ ] T012 在 `app/models/db.py::init_db` 接入固定顺序：建表与增量列迁移 → 启动回填 →（此后才允许留存清理），保证"回填必须先于任何清理"（data-model §7、R4）
- [ ] T013 在 `tests/test_contract.py` 补充契约断言（`last_run_at` / `duration_ms` 可空性、`scene_cleaned` 410、`device_not_found` 400、`package_checksum_conflict` 409），并执行 `python build.py contract` 校验 OpenAPI 与 Pydantic 一致（依赖 T002、T008），修复任何字段/描述差异直至通过

**检查点**：基础层就绪——迁移与新表可重复执行、回填幂等、契约校验通过；四个用户故事可以开始。

---

## 阶段 3：用户故事 1 - 磁盘清理后仍能完整回溯历史任务（优先级：P1）🎯 MVP

**目标**：界面展示数据全部以 SQLite 为唯一来源；规则结果、发现与 KPI 数据长期保留；规则结果以最新一次执行为准、无版本历史。

**独立测试**：构造一个磁盘现场与原始压缩包都已被清理的任务，打开任务列表、任务详情、规则详情与 KPI 视图，逐项核对与清理前一致（执行日志与报告文件除外）。

### 用户故事 1 的测试（先写测试并确认失败）

- [ ] T014 [P] [US1] 新增 `tests/test_task_db.py`：快照发布单事务、整批替换"最新为准"（重跑后同 `(task_id, rule_code)` 仅一行）、损坏规则 JSON 跳过且其余规则正常发布、读取结果与 `rules/*.json` 契约 JSON 逐字段一致（FR-002、FR-007、data-model §3、R1）
- [ ] T015 [P] [US1] 新增 `tests/test_task_db_backfill.py`：已入库任务跳过、未入库任务完整导入（任务行 + 规则结果 + KPI 点）、损坏文件跳过不中断、重复执行结果幂等（FR-001、FR-002、data-model §7、R4）
- [ ] T016 [P] [US1] 新增 `tests/test_kpi_history_db.py`：`task_kpi_points` 入库字段与 `index.jsonl` 一一对应，历史/趋势/版本对比读取走 DB，现场文件删除后查询结果不变（FR-002、SC-003、data-model §4、R2）

### 用户故事 1 的实现

- [ ] T017 [US1] 在 `app/services/tasks.py::_publish_terminal` 接入 `task_db.publish_snapshot`：父进程在终态发布时写入任务行 + 规则结果 + KPI 点 + `preparation` 摘要（单事务），之后才写 `task.json` / `system.json` / 报告（data-model §5、R1）
- [ ] T018 [US1] 在 `app/cli.py::_publish_terminal` 接入同一发布路径，保证本地模式与在线模式写库一致（FR-001、AGENTS.md 双模式一致）
- [ ] T019 [US1] 改造 `app/services/tasks.py`：`list_tasks` / `get` / 规则详情 / `system` 结果改从 `task_db` 读取（摘要化 `system.rules` 与 `exclude_records` / `exclude_details` 语义不变），不再以 `output/` 文件为主源（FR-001、data-model §8、R5）
- [ ] T020 [US1] 改造 `app/services/overview.py` 为 DB 聚合，字段与口径不变，不扫 `output/`（FR-001、data-model §8、R5）
- [ ] T021 [US1] 改造 `app/services/kpi_history.py` 历史索引读取为 DB（`output/<task_id>/kpi/history/index.jsonl` 仅作为回填输入），趋势与版本对比响应契约不变（FR-002、SC-003、R2）
- [ ] T022 [US1] 改造 `app/services/preparation.py`：任务详情的准备摘要读 `tasks.preparation` 列，保留既有计算函数供执行期使用（data-model §2、R5）
- [ ] T023 [US1] 在 `app/services/tasks.py::delete` 级联删除 `task_rule_results` 与 `task_kpi_points`，保持"文件成功删除后才删记录"的既有顺序（data-model §5、contracts/api-delta.md）

**检查点**：删除 `output/<task_id>` 与 `uploads/<task_id>` 后，列表、详情、规则详情、KPI 趋势仍与清理前一致——US1 可独立验证，MVP 可交付。

---

## 阶段 4：用户故事 2 - 磁盘文件按策略自动受控（优先级：P1）

**目标**：任务结束后自动清理，`uploads/` 与 `output/` 各只保留最近 50 个任务现场；现场缺失时给出明确提示；重传同名且校验和一致的包可恢复现场。

**独立测试**：构造超过 50 个任务（运行时间不同），完成留存清理后核对磁盘仅保留最近 50 个任务对应的文件，且被清理任务的界面数据完整；对被清理任务发起报告/日志/重跑/重建得到明确提示；重传同名同 checksum 包恢复现场、改一字节被拒绝。

### 用户故事 2 的测试（先写测试并确认失败）

- [ ] T024 [P] [US2] 新增 `tests/test_retention.py`：51 个任务清理后仅留最近 50（按 `COALESCE(last_run_at, created_at)` 倒序）、恰好 50 个不清理、`pending`/`running` 全程豁免、从未运行任务按创建时间参与排序、删除失败不影响任务终态并记录日志（FR-004、FR-005、FR-006、SC-002、data-model §6）
- [ ] T025 [P] [US2] 新增 `tests/test_task_restore.py`：现场已清理 + 同名同 `package_checksum` 重传 → 写回 `uploads/<task_id>/<package_file>` 且返回 202 + Location、不重跑、不改历史数据；checksum 不一致 → 409 `package_checksum_conflict`；库中无 checksum 且无可读历史包 → 409 且消息说明无法校验（FR-013、SC-007、contracts/api-delta.md）
- [ ] T026 [P] [US2] 新增 `tests/test_tasks_scene_missing.py`：现场缺失时报告 → 410 `scene_cleaned`、日志 → 410 `scene_cleaned`、rerun / rebuild → 410 `scene_cleaned` 且不进入队列；任务不存在仍是 404 `not_found`；输出目录存在但包缺失保持 409 `package_missing`（FR-011、FR-012、SC-006、R8）

### 用户故事 2 的实现

- [ ] T027 [US2] 在 `app/services/tasks.py` 与 `app/cli.py` 的终态收尾（完成/失败/重跑/重建/单规则重跑）调用 `retention.cleanup`；清理失败只记日志、不改变任务终态、不阻塞发布（FR-004、FR-006、data-model §6、R6）
- [ ] T028 [US2] 改造 `app/api/router.py`：报告与日志接口现场缺失返回 410 `scene_cleaned`（消息区分报告已随现场清理 / 执行日志不入库）；rerun / rebuild 前置校验现场目录，缺失时 410 并提示"重新上传同名且校验和一致的原始包恢复现场"（FR-011、FR-012、R8）
- [ ] T029 [US2] 改造 `app/api/router.py::create_task_v3` 同名分支为恢复矩阵：现场包存在 → 与现场文件比对（现状）；现场包缺失 → 与 `tasks.package_checksum` 比对，一致则写回 `uploads/<task_id>/<package_file>` 并返回 202 + Location（不重跑、不改历史数据、不触发清理），不一致 409；库中无 checksum 但有可读历史包 → 以历史包 checksum 为准并回填库；均无 → 409 并说明无法校验（FR-013、R7、R8）
- [ ] T030 [US2] 在 `app/api/router.py::_receive_upload` 与 `app/cli.py` 本地任务执行路径写入首次接收的 `package_checksum`（`sha256_file`），作为恢复与冲突判定的唯一依据（data-model §2、R7）
- [ ] T031 [US2] 前端现场缺失提示：`web/src/components/task-detail/TaskReportPanel.tsx`、`web/src/components/task-detail/TaskLogsPanel.tsx` 在 410 `scene_cleaned` 时展示服务端消息与后续建议（核心数据仍可查）；`web/src/components/task-detail/TaskActionModals.tsx` 在 rerun / rebuild 410 时展示恢复建议；不静默失败、不展示空白（FR-011、SC-006、R10）
- [ ] T032 [US2] 新增 `web/e2e/retention.spec.ts` 与种子脚本 `web/e2e/seed_retention.py`（由 `tests/fixtures/make_real_package.py` 派生 51 个任务）：覆盖 51 任务清理后磁盘仅留最近 50、清理后任务详情/规则/KPI 可查、重传恢复现场、410 提示文案（SC-001、SC-002、SC-006、SC-007、R10；不扩充代表性样例包生成器）

**检查点**：US1 与 US2 均可独立验证；磁盘占用受控且历史数据不丢。

---

## 阶段 5：用户故事 3 - 任务元数据补充最后运行时间与时长（优先级：P2）

**目标**：任务列表与详情展示最后一次运行时间与该次执行耗时；未运行与运行中不出现误导性时长。

**独立测试**：对已完成、重跑过、从未运行三类任务，核对列表与详情中最后运行时间与任务时长展示。

### 用户故事 3 的测试（先写测试并确认失败）

- [ ] T033 [P] [US3] 新增 `tests/test_task_run_fields.py`：运行开始写 `last_run_at` 且清空 `duration_ms`、终态写 `duration_ms = completed_at − last_run_at`（`>= 0`）、重跑覆盖为最近一次、`created_at` 始终不变、从未运行两列均为 NULL（FR-008、data-model §2、R3）
- [ ] T034 [P] [US3] 扩展 `web/src/pages/TaskListPage.test.tsx`：已运行任务展示最后运行时间与时长、从未运行展示占位、运行中不显示时长（FR-009、SC-004）

### 用户故事 3 的实现

- [ ] T035 [US3] 在 `app/services/tasks.py` 与 `app/cli.py` 的任务运行生命周期写运行字段：任务开始（含重跑/重建/单规则重跑）写 `last_run_at` = 开始时刻、`duration_ms` = NULL；进入终态写入 `duration_ms`（FR-008、data-model §2、§5）
- [ ] T036 [US3] 在 `web/src/pages/TaskListPage.tsx` 新增"最后运行时间"与"任务时长"列：UTC → 本地时区展示、未运行占位、运行中显示"运行中"且不显示时长、时长格式统一（FR-009、SC-004）
- [ ] T037 [US3] 在 `web/src/components/task-detail/TaskMetaPanel.tsx` 同步展示两字段并扩展 `web/src/components/task-detail/TaskMetaPanel.test.tsx`（FR-009）
- [ ] T038 [US3] 扩展 `web/e2e/task-home.spec.ts`：列表与详情可见最后运行时间与时长，从未运行任务显示占位（SC-004）

**检查点**：US3 可独立验证，列表无需进入详情即可发现耗时异常。

---

## 阶段 6：用户故事 4 - 手动指定设备 ID 必须存在于设备台账（优先级：P2）

**目标**：手动指定的设备 ID 必须在 `inventory_devices` 中存在，否则拒绝且不落库；空值不触发校验。

**独立测试**：分别输入台账中存在 / 不存在的设备 ID，验证接受与拒绝（含提示，且拒绝时不创建、不修改任务）。

### 用户故事 4 的测试（先写测试并确认失败）

- [ ] T039 [P] [US4] 新增 `tests/test_task_device_id.py`：`PATCH /api/v2/tasks/{task_id}/device-id` 指定存在的设备 → 200 且任务记录更新；指定不存在 ID → 400 `device_not_found` 且任务记录不变；创建流程 `reserve` 手动指定不存在 ID → 拒绝且不创建任务；空值清空绑定不触发校验（FR-010、SC-005、R9）

### 用户故事 4 的实现

- [ ] T040 [US4] 在 `app/services/tasks.py::update_device_id` 与 `reserve` 写入前校验非空 `device_id` 存在于 `inventory_devices`，不存在则抛业务错误，不写文件、不写库（FR-010、R9）
- [ ] T041 [US4] 在 `app/api/router.py` 将上述校验错误映射为 400 `device_not_found`（统一 `{code, message, detail}`，消息明确"设备 ID 不存在于设备台账"）（FR-010、contracts/api-delta.md）
- [ ] T042 [US4] 前端设备 ID 手动输入入口（`web/src/hooks/useTaskActions.ts` 与上传弹窗设备字段）展示服务端拒绝消息且保持任务原值不变（FR-010、SC-005）
- [ ] T043 [US4] 扩展 `web/e2e/task-actions.spec.ts`：不存在设备 ID 被拒绝并提示、存在设备 ID 保存成功（SC-005）

**检查点**：US4 可独立验证；不存在于台账的设备 ID 进入任务记录的条数为 0。

---

## 阶段 7：收尾与横切关注点

**目的**：文档回写、全量门禁与质量证据

- [ ] T044 [P] 回写 `docs/architecture.md`：DB 为界面展示唯一数据来源、`output/` 为执行期现场、留存清理生命周期与两模式一致（R11）
- [ ] T045 [P] 回写 `docs/data-model.md`：任务/规则结果/KPI 的 DB 与文件角色、`tasks` 新列、两张新表（R11）
- [ ] T046 [P] 回写 `docs/roadmap.md`："数据层统一与刷新策略""任务保留与磁盘治理"落地状态（R11）
- [ ] T047 执行 `python build.py contract` 与 `python build.py gen-web-api`，确认契约与生成客户端与实现一致、无手写 API 调用（AGENTS.md 契约约定）
- [ ] T048 执行 `python build.py lint` 与 `python build.py test`（全量单元与契约测试）
- [ ] T049 执行 `python build.py verify`（本地全流程：解压、执行器、报告、CLI/API 双模式一致性）
- [ ] T050 执行 `python build.py web-build` 与 `python build.py e2e`（前端构建与端到端）
- [ ] T051 按 `quickstart.md` 走查 6 组场景并留存证据：入库快照、清理后追溯、重传恢复/冲突、51 任务留存、设备校验、本地 CLI 双模式；核对列表/详情 1 万任务量级 P95 < 300ms 性能目标（plan.md 性能目标、SC-001~SC-007）
- [ ] T052 逐条核对本清单复选框与实际完成状态一致，确认无遗漏 FR / SC 后再准备合并报告

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 1（设置）**：T001 阻塞全部；T002 → T004；T003 与 T002 可并行
- **阶段 2（基础层）**：依赖 T002；阻塞全部用户故事；T013 依赖 T002 + T008
- **阶段 3（US1，P1）**：依赖阶段 2；MVP
- **阶段 4（US2，P1）**：依赖阶段 2；与 US1 无文件冲突（除 `app/services/tasks.py` 收尾钩子，见并行说明）
- **阶段 5（US3，P2）**：依赖阶段 2 与 T017/T018 的发布路径
- **阶段 6（US4，P2）**：依赖阶段 2；与 US1~US3 无文件冲突
- **阶段 7（收尾）**：依赖全部所需故事完成

### 用户故事依赖

- **US1** 完成后即可交付 MVP（清理后仍可完整回溯）
- **US2** 独立可用；其"清理后提示/恢复"与 US1 的读取切换共同构成完整留存语义
- **US3 / US4** 相互独立，可在阶段 2 后并行推进

### 并行机会

- T003 与 T002 可并行（不同文件）
- T005 → T006 → T007 串行（同一文件 `app/models/db.py`，不同表定义）
- T011 依赖 T005（新列）与 T009（查询入口），在两者之后执行
- 各故事内标记 [P] 的测试任务可并行编写
- US1 的 T019~T023 涉及不同文件可并行；`app/services/tasks.py` 的 T017 / T023 与 US2 的 T027 同文件，需串行
- 收尾 T044~T046 可并行

---

## 并行示例：用户故事 1

```bash
# 三个测试文件并行编写（TDD 红灯）：
Task: "新增 tests/test_task_db.py（T014）"
Task: "新增 tests/test_task_db_backfill.py（T015）"
Task: "新增 tests/test_kpi_history_db.py（T016）"

# 读取切换按文件并行：
Task: "改造 app/services/overview.py（T020）"
Task: "改造 app/services/kpi_history.py（T021）"
```

---

## 实现策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：设置（含 worktree 前置检查、契约先行）
2. 完成阶段 2：基础层（阻塞全部故事）
3. 完成阶段 3：US1
4. **停止并验证**：删除某任务的 `output/` 与 `uploads/` 现场后，列表 / 详情 / 规则 / KPI 仍与清理前一致
5. 演示 / 留证

### 增量交付

1. 设置 + 基础层 → 迁移、新表、回填、留清服务就绪
2. US1 → 独立测试 → 演示（MVP）
3. US2 → 独立测试 → 演示
4. US3 → 独立测试 → 演示
5. US4 → 独立测试 → 演示
6. 收尾：文档回写 + 全量门禁 + quickstart 走查证据

### 质量门禁（每个用户故事完成后）

```bash
python build.py lint
python build.py test
```

涉及契约时追加 `python build.py contract` 与 `python build.py gen-web-api`；涉及全流程时追加 `python build.py verify`；前端故事追加 `python build.py web-build` 与 `python build.py e2e`。

### 反模式提醒

- 不得让 worker 进程直接写 SQLite；父进程是发布与清理的唯一写入者
- 不得在清理触发后再做回填；回填必须先于任何清理（T012）
- 不得让报告、执行日志出现在数据库读取路径；它们随现场清理消失
- 不得引入规则结果版本历史、自动重试或断点续跑
- 不得为通过测试而修改规则判定逻辑或 `rule_version`
- 不得手写与 OpenAPI 不一致的前端 API 调用
- 不得提交 `web/e2e/screenshots/` 等本地证据目录
