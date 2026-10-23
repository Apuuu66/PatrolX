---
description: "设备台账版本以 LST ME 执行时间为准 — 实现任务清单"
---

# 任务：设备台账版本以 LST ME 执行时间为准

**输入**：来自 `specs/035-lst-me-execution-time/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/api-delta.md、quickstart.md

**测试**：本清单包含测试任务。按 AGENTS.md 与 Superpowers 要求先写失败测试（TDD）再补实现；前端新增能力包含覆盖完整入口到关键结果的 E2E。

**组织方式**：按用户故事分组，每个故事可独立实现、独立测试、独立演示。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1~US3）
- 描述中包含精确的文件路径与对应 FR / SC / R 编号

## 路径约定

仓库根目录：`app/`、`web/`、`tests/`、`docs/`、`specs/`。规划产物已在 `main` 主工作区完成；实现与测试全部在实现分支 worktree `.worktrees/feature-035-lst-me-execution-time` 内完成，不得在主工作区改实现文件。

本轮不改巡检规则判定逻辑与执行编排（EXTRACT → PREPARE → INSPECT），不改 `rule_version`，不新增依赖，不改 KPI 与任务自身时间字段。

---

## 阶段 1：设置（实现环境与契约先行）

**目的**：完成实现前置检查，先落契约与文档口径，再动实现

- [ ] T001 从已提交规划产物的 `main` 创建实现分支 `feature-035-lst-me-execution-time` 与 worktree `.worktrees/feature-035-lst-me-execution-time`；执行 `git worktree list` 与 `git branch --show-current` 并确认：当前目录是实现 worktree、检出分支正确、Speckit 产物已在 `main` 提交、已有 worktree 时复用；在回合报告记录检查结果（阻塞全部后续任务；AGENTS.md 实现前置检查）
- [ ] T002 [P] 更新 `docs/api/openapi.yaml`：`InventoryObservation` 增 `time_source`（enum `lst_me`/`task`，必填）与 `time_source_reason`（enum `header_time_missing`/`header_time_invalid`/`time_in_future`，可空）；`InventoryVersionPoint` 增 `time_source`；`TaskInventory` 增可空 `execution_time` 及新 schema `TaskInventoryExecutionTime` / `TaskInventoryExecutionTimeEntry`；为 `observed_at`、`current_version_observed_at`、`first_seen_at`、`last_seen_at`、`InventoryQualityIssue.detected_at` 补执行时间口径 `description`（FR-004、FR-006、FR-010；contracts/api-delta.md）
- [ ] T003 [P] 更新 `docs/data-model.md` §12 局点设备台账：记录观测时间取执行时间的口径、`time_source` / `time_source_reason` 两列、证据 `execution_time` 段与 `schema_version=3`（FR-001、FR-002、FR-012）；更新 `docs/example/real-package-structure.md`：`LST ME.txt` 头部行尾执行时间示例与解析说明（R1、R2）
- [ ] T004 执行 `python build.py gen-web-api` 重新生成 `web/src/api/`，确认 diff 仅包含新增字段，未手写任何前端 API 调用（依赖 T002；AGENTS.md 契约约定）

**检查点**：前置检查四条全部满足、契约与文档口径已落、前端客户端已再生成。

---

## 阶段 2：基础层（阻塞全部用户故事）

**目的**：解析、落库、投影三处口径先行，作为全部故事的共享基础设施

- [ ] T005 [P] 在 `tests/fixtures/inventory/builder.py` 为 `lst_me_content` 与 `multi_device_lst_me_content` 增加可选头部执行时间参数（不传时输出与现状完全一致），并提供"无时间 / 非法日期 / 未来时间"样例构造能力（quickstart §1；既有测试断言不受影响）
- [ ] T006 [P] 在 `app/models/db.py` 新增 `_ensure_inventory_observation_columns`：为 `inventory_observations` 幂等增量列 `time_source`（`VARCHAR(16) NOT NULL DEFAULT 'task'`）与 `time_source_reason`（`VARCHAR(32)`，可空），并在 `init_db` 接入迁移顺序；旧行为 `task` + `NULL`（data-model §1.2、R4）
- [ ] T007 [P] 在 `app/models/schemas.py` 增加 `InventoryTimeSource` / `InventoryTimeSourceReason` 枚举、`InventoryObservation.time_source`（必填）与 `time_source_reason`（可空）、`InventoryVersionPoint.time_source`、`TaskInventoryExecutionTime` / `TaskInventoryExecutionTimeEntry` 与 `TaskInventory.execution_time: ... | None`（FR-004、FR-010、contracts/api-delta.md §1、§2、§5）
- [ ] T008 先写失败测试：在 `tests/test_inventory_parser.py` 覆盖头部行尾时间解析（`+++    CSP/*xx*/     2025-05-26  14:40:36` → `2025-05-26T06:40:36+00:00`，与既有 `datetime.isoformat()` 约定一致）、首行噪声后第二行命中、多空格/制表符、无时间、非法日期、晚于任务完成时间 5 分钟以上、多设备共用文件时间、多来源文件各自独立，以及 `execution_time.per_file` 结构与 `schema_version`/`parser_version`（依赖 T005；FR-001~FR-003、FR-009、FR-012、R1~R3）
- [ ] T009 在 `app/services/inventory/parser.py` 实现：头部区域（首个设备记录行之前，匹配即停止）行尾时间解析、固定 UTC+8 转 UTC、可信性校验与回退原因、`execution_time` 证据段、`SCHEMA_VERSION` 2→3、`PARSER_VERSION` 3→4；命中行不参与键值字段解析（依赖 T005、T008；R1~R3、R5）
- [ ] T010 先写失败测试：在 `tests/test_inventory_ledger.py` 覆盖 `observed_at` 取设备来源文件中可用的最近执行时间、无法解析时回退任务完成时间并写 `time_source=task` 与原因、重跑覆盖刷新时间字段、历史证据（无 `execution_time`）读取按兜底语义不报错（依赖 T005；FR-003~FR-005、FR-011、R5、R8）
- [ ] T011 在 `app/services/inventory/ledger.py::_observation_values` 接入执行时间：按设备 `source_files` 取可用最近执行时间，写入 `observed_at` / `time_source` / `time_source_reason`；重跑与重建沿用覆盖语义（依赖 T006、T009、T010；FR-003、FR-004、FR-011）
- [ ] T012 在 `app/services/inventory/queries.py` 投影新增字段：`_observation_model` 输出 `time_source` / `time_source_reason`，`_version_history_points` 输出 `time_source`；确认 `_device_model`、`list_observations`、`get_version_history`、`list_quality_issues` 排序口径统一为 `observed_at` 并带 `task_id` 稳定次序（依赖 T007、T011；FR-004、FR-006、R6）
- [ ] T013 在 `tests/test_contract.py` 补契约断言（新增字段存在性与可空性、`execution_time` schema、`parser_version=4` / `schema_version=3`），执行 `python build.py contract` 直至通过（依赖 T002、T007；AGENTS.md 契约门禁）

**检查点**：基础层就绪——解析、落库、投影三处口径一致，契约校验通过；三个用户故事可以开始。

---

## 阶段 3：用户故事 1 - 补传/乱序上传不再篡改设备当前版本（优先级：P1）🎯 MVP

**目标**：设备当前版本与最近观测由执行时间裁决，补传旧包或乱序上传后不回退。

**独立测试**：同一设备两个包，执行时间 A 晚于 B；先上传 A 再上传 B，设备当前版本仍为 A 的版本，最近观测不回退，B 进入版本历史。

### 用户故事 1 的测试（先写测试并确认失败）

- [ ] T014 [P] [US1] 在 `tests/test_inventory_ledger.py` 增加乱序与等价场景：先归档执行时间较晚的任务、再归档较早任务后 `current_version_raw` / `current_version_observed_at` / `last_seen_at` 不变；执行时间相同时按 `task_id` 稳定裁决且重复调用结果一致；较新的无版本观测不清空当前版本；同一任务内同名设备多版本值仍判 `conflict`、不进入当前版本裁决（用 `multi_device_lst_me_content` 构造同一设备两个版本值）(FR-005、FR-006、FR-007、SC-001、R6）
- [ ] T015 [P] [US1] 在 `tests/test_inventory_api.py` 增加接口断言：设备列表与详情返回的 `current_version` / `current_version_observed_at` / `last_seen_at` 反映执行时间，观测列表 `observed_at` 与 `time_source` 一致（FR-005、FR-006、SC-001、SC-002）
- [ ] T016 [US1] 修正测试暴露的查询/重算不一致：`app/services/inventory/ledger.py::_recalculate_device` 的排序与有效版本选取、`app/services/inventory/queries.py::list_observations` 的稳定次序；仅修排序/裁决，新增字段输出归 T012，保持"最新有效版本"语义（依赖 T014、T015；FR-005、R6）
- [ ] T017 [US1] 在 `tests/fixtures/make_real_package.py` 为 `Basic Information/LST ME.txt` 增加**固定时间戳**的头部执行时间行（既有样例只增不减、生成保持幂等），使代表性样例包覆盖正常路径（FR-001、FR-002；AGENTS.md 样例包约束）
- [ ] T018 [US1] 在 `web/e2e/start-backend.sh` 播种包中给 `LST ME.txt` 带上真实执行时间（沿用 T005 的构造参数），新增 `web/e2e/inventory-execution-time.spec.ts`：先上传执行时间较晚的包、再上传较早的包，断言设备列表"当前版本"与"最近观测"不回退（依赖 T005、T009；SC-001）

**检查点**：US1 独立可用——乱序/补传场景下当前版本结论稳定。

---

## 阶段 4：用户故事 2 - 界面上的时间能区分来源（优先级：P2）

**目标**：设备列表、设备详情、任务详情展示的时间都能区分"设备执行时间"与"任务完成时间兜底"，兜底时给出原因。

**独立测试**：分别用带头部时间与无头部时间的包完成任务，检查设备列表/详情的时间来源标识与任务详情台账面板执行时间。

- [ ] T019 [P] [US2] 在 `web/src/components/task-detail/TaskInventoryPanel.tsx` 增加执行时间与来源展示（含回退原因文案），并补 `web/src/components/task-detail/TaskInventoryPanel.test.tsx`（FR-010、SC-004）
- [ ] T020 [P] [US2] 在 `web/src/pages/InventoryPage.tsx` 为"最近观测"列增加时间来源标识，并补 `web/src/pages/InventoryPage.test.tsx`（FR-010、SC-004）
- [ ] T021 [P] [US2] 在 `web/src/pages/InventoryDevicePage.tsx` 为"最近观测""观测时间"列与版本历史增加时间来源标识，并补 `web/src/pages/InventoryDevicePage.test.tsx`（FR-010、SC-004）
- [ ] T022 [US2] 在 `web/e2e/inventory-execution-time.spec.ts` 增加来源标识与兜底场景断言：带时间包显示设备执行时间、无时间包显示兜底时间并标注原因（依赖 T018；SC-004）

**检查点**：US2 独立可用——任意页面时间来源可解释。

---

## 阶段 5：用户故事 3 - 版本历史按执行时间呈现升降（优先级：P3）

**目标**：版本历史的顺序、方向与缺口标记以执行时间为准，不受上传顺序影响。

**独立测试**：三个观测按执行时间乱序入库后，版本历史仍按执行时间升序呈现方向与缺口。

- [ ] T023 [P] [US3] 在 `tests/test_inventory_queries.py`（不存在则新建）覆盖版本历史升序、`upgrade`/`downgrade`/`unchanged` 判定、中间无版本时的 `has_gap`、以及 `time_source` 回传（FR-008、FR-006、SC-005）
- [ ] T024 [US3] 按测试结论修正 `app/services/inventory/queries.py::_version_history_points` 与 `get_version_history` 的排序/分页口径，保持字符串序方向判定不变（依赖 T023；FR-008、R7）

**检查点**：US3 独立可用——版本演进轨迹与执行时间一致。

---

## 阶段 6：收尾与验证

- [ ] T025 [P] 更新 `docs/roadmap.md` 记录本特性的落地状态与后续接口（FR-001~FR-012 汇总）
- [ ] T026 执行 `python build.py lint`、`python build.py test`、`python build.py contract`，修复全部失败直至通过（AGENTS.md 合入门禁）
- [ ] T027 执行 `python build.py e2e`（含新增用例）与 `python build.py web-build`，记录通过数量与基线对比（SC-001、SC-004）
- [ ] T028 按主题拆分提交（中文提交信息），在实现 worktree 内完成提交；合入与推送等待用户"推送"指令，合入后清理 worktree（AGENTS.md Git 约定）

---

## 依赖与执行顺序

- T001 阻塞全部：未确认实现 worktree 前不得改实现文件。
- T002 → T004 → T007/T013（契约先行链）。
- T005 阻塞 T008/T009/T010/T018（样例与测试构造依赖）。
- T006/T007 → T011 → T012（落库到投影链）。
- T009 → T011（解析到归档链）。
- US1（T014~T018）依赖基础层完成；US2（T019~T022）依赖 T011、T012、T004；US3（T023~T024）依赖 T012。
- 收尾任务 T025~T028 依赖全部用户故事完成。

## 并行执行示例

- 基础层并行组：T005、T006、T007（三个不同文件，互不依赖）。
- US2 并行组：T019、T020、T021（三个前端文件）。
- 收尾并行组：T025 可与其他实现任务并行，T026/T027 必须串行执行并各自记录证据。

## 实现策略

1. **MVP 优先**：先做基础层 + US1，即"补传/乱序不再篡改当前版本"，这是本轮运维痛点。
2. **逐个增量**：US2 只加展示与标识，US3 只补排序与方向断言，两个故事都不引入新数据源。
3. **契约先行**：任何接口字段改动先落 `docs/api/openapi.yaml`，再改 Pydantic 与前端生成客户端。
4. **证据留痕**：每个测试任务在提交信息或回合报告中记录对应 FR / SC；E2E 与单测输出数量与基线对比写入最终报告。
