# 任务：KPI-only 规则库收缩

**输入**：`specs/037-kpi-only-rule-library/` 下的 spec、plan、research、data-model 与 contracts

**前置条件**：实现必须在 `feature/037-kpi-only-rule-library` 的独立 worktree 中执行；规划产物已提交到 `main`。

**测试策略**：规格明确要求自动化回归与展示效果证据，因此按下述顺序先写并确认失败测试，再实现。

## 格式

- `[P]`：不同文件、无未完成依赖，可并行执行。
- `[US1]` / `[US2]` / `[US3]`：对应用户故事。
- 所有实现动作均使用仓库相对路径。

---

## 阶段 1：设置

**目的**：建立实现现场与可重复验证基线。

- [X] T001 在实现 worktree 中执行 `git worktree list`、`git branch --show-current`、`git status --short`，确认分支为 `feature/037-kpi-only-rule-library`，且不存在真实包或台账等未确认变更。
- [ ] T002 运行 `.venv/bin/python build.py lint` 和 `.venv/bin/python build.py test` 记录实现前基线；若基线失败，先只读定位并在任务日志中记录，不得用功能改动掩盖既有失败。

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：先固定契约文字与代表性合成样例边界。

- [X] T003 在 `docs/api/openapi.yaml` 更新 `getRuleResultV2`、`rerunTaskV2`、`rebuildTaskV2`、`listInspectorsV2` 的说明文字，明确历史结果可读、活动目录 KPI-only、已删除规则不可重跑；不修改路径、参数、`operationId` 或响应 Schema。
- [X] T004 在 `tests/fixtures/make_real_package.py` 增加可重复生成的 KPI 缺失边界 fixture 能力，保留既有 `ZZapp01BCN_app_Problem_scene_333.zip` 默认字节和固定时间戳不变，供 KPI `skip` 与“非 KPI 文件保留但不触发规则”用例共用。

**检查点**：OpenAPI 描述与合成样例边界已固定；以下用户故事可开始。

---

## 阶段 3：用户故事 1 - 只执行 KPI 巡检（优先级：P1）🎯 MVP

**目标**：活动普通规则严格只剩 `kpi.measurement_units`，旧规则模块被硬删除。

**独立测试**：注册表、`/api/v2/inspectors`、新任务普通规则结果均只含 KPI；hidden `pkg.extract.*` 完整保留且不出现在默认目录。

### 测试

- [X] T005 [P] [US1] 更新 `tests/test_scan_config_registry.py`，断言活动普通规则集合严格等于 `{"kpi.measurement_units"}`、hidden 集合全部以 `pkg.extract.` 开头、`deploy/config/scan_rules.yaml` 只含 `kpi_all` 且 `disabled_rules == []`；先运行并确认因旧规则仍注册而失败。
- [X] T006 [P] [US1] 更新 `tests/test_api.py` 的 inspector 与上传任务断言，要求默认目录和任务结果只含 KPI；增加同一断言覆盖 `include_hidden=true` 时 hidden 不进入普通集合。
- [X] T007 [P] [US1] 更新 `tests/test_sample_guard.py`，把代表性合成包的活动普通规则结果期望收缩为唯一 KPI，并保留“非 KPI 文件存在但无对应结果”的断言；先确认失败。
- [X] T008 [P] [US1] 更新 `tests/test_overview.py`，断言 `registered_rule_count` 等于活动普通规则数 1，不把 hidden 解压基础设施计入普通规则统计；先确认失败。

### 实现

- [X] T009 [US1] 删除 `app/inspectors/alarm/`、`app/inspectors/config/`、`app/inspectors/log/`、`app/inspectors/resource/`、`app/inspectors/traffic/`，并移除 `app/` 下对已删除模块的任何活动导入；不得删除 `app/inspectors/pkg.py`、`base.py`、`registry.py` 或 `kpi/measurement.py`。
- [X] T010 [US1] 将 `deploy/config/scan_rules.yaml` 收缩为仅含 `kpi_all` 的扫描组，设置 `disabled_rules: []`；保持 `^kpi/.*\.csv$`、`^traffic/.*\.csv$` 与 `kpi.measurement_units.rule_version == "3.3.0"` 不变。
- [X] T011 [US1] 在 `app/services/overview.py` 将 `registered_rule_count` 改为活动普通规则数（`registry.all()`），保留 hidden 解压执行但排除其普通规则统计口径。
- [X] T012 [US1] 删除仅测试已删除规则的 `tests/test_alarm_flapping.py` 与 `tests/test_rules.py`；规则机制通用测试若仍需要虚构规则，改用测试内局部 `Inspector`，不得伪造已删除的生产规则。
- [X] T013 [US1] 更新 `tests/test_baseline_pipeline.py`、`tests/test_baseline_storage.py`、`tests/test_baseline_schemas.py`、`tests/test_prepare_pipeline.py` 和 `tests/test_executor_parallel_policy.py`，把活动规则断言改为 KPI，并保留 hidden 解压、prepare、并行与存储行为覆盖。
- [X] T014 [US1] 更新 `tests/test_cli_explain_match.py`、`tests/test_debug_local_script.py`、`tests/test_task_run_fields.py`、`tests/test_rerun_status.py` 和 `tests/test_rule_state_tasks.py`，将活动 CLI/API/启停场景从已删除规则改为 KPI；历史或通用注入场景需在测试名称中明确标注“历史/虚构”。
- [X] T015 [US1] 运行 `tests/test_scan_config_registry.py tests/test_api.py tests/test_sample_guard.py tests/test_overview.py tests/test_baseline_pipeline.py tests/test_cli_explain_match.py`，修复所有活动规则仍指向非 KPI 的失败。

**检查点（MVP）**：默认注册表、任务执行计划和规则目录均只有 KPI；hidden 解压基础设施完整。

---

## 阶段 4：用户故事 2 - 保留历史任务可追溯性（优先级：P2）

**目标**：已持久化的非 KPI 结果仍可读取，但不可重新注册、启停、重跑或重建。

**独立测试**：预置含非 KPI 结果的历史任务，在 KPI-only 代码树上 GET 成功；同代码 rerun/incremental rebuild 返回明确 `unknown_rule` 且任务现场摘要不变。

### 测试

- [X] T016 [P] [US2] 更新 `tests/test_baseline_review.py`，预置 `log.error_density` 历史 JSON/SQLite 后断言 `GET /api/v2/tasks/{task_id}/rules/log.error_density` 返回原内容，同时 `/api/v2/inspectors` 不含该规则；先确认 GET 因注册表预检而失败。
- [X] T017 [P] [US2] 更新 `tests/test_api_robustness.py`、`tests/test_baseline_delete.py`、`tests/test_baseline_rerun.py` 和 `tests/test_baseline_storage.py`，用历史夹具覆盖非 KPI 结果读取、删除任务后 404、以及历史文件字段内容不变。
- [X] T018 [P] [US2] 更新 `tests/test_task_rebuild.py` 和 `tests/test_api.py`，断言 rerun 与 incremental rebuild 对 `log.error_density`、`alarm.stat` 等已删除代码返回 `400 unknown_rule`，并在请求前后比较任务目录摘要和 `system.json`，确认零修改。
- [X] T019 [P] [US2] 更新 `web/src/pages/RuleDetailPage.test.tsx` 与 `web/e2e/alarm-flapping-rule-detail.spec.ts` 的语义，使其验证“历史结果在 inspector 元数据缺失时仍可展示”；不得把这些规则描述为活动规则或可重跑能力。
- [X] T020 [P] [US2] 更新 `web/e2e/theme.spec.ts`、`web/e2e/page-states.spec.ts` 或相关历史种子，将非 KPI 规则明确命名为历史任务夹具；活动目录和启停状态 E2E 只使用 KPI。

### 实现

- [X] T021 [US2] 修改 `app/api/router.py` 的 `get_rule_result_v2`：移除活动注册表前置检查，直接调用 `_load_rule`；结果存在于 DB/JSON/system 摘要时返回，只有不存在时返回 404。不得放宽 rerun/rebuild 注册表预检。
- [X] T022 [US2] 确认 `app/services/tasks.py` 与 `app/cli.py` 的未知规则预检对已删除代码返回既有明确错误且不修改现场；仅在测试证明缺陷时做最小修复，不新增旧规则兼容分支。
- [X] T023 [US2] 调整 `web/src/pages/RuleDetailPage.tsx` 的历史详情逻辑：inspector 列表缺失该代码时仍渲染已保存结果；若无法安全重跑，则隐藏或禁用重跑入口并显示规则已下线提示；保持 KPI 详情交互不变。
- [X] T024 [US2] 运行 `tests/test_baseline_review.py tests/test_api_robustness.py tests/test_baseline_delete.py tests/test_baseline_rerun.py tests/test_task_rebuild.py` 与 `cd web && npm test -- --run src/pages/RuleDetailPage.test.tsx`，修复历史读取和前端回归。

**检查点**：非 KPI 历史证据可读，规则目录仍 KPI-only，已删除规则不能执行。

---

## 阶段 5：用户故事 3 - 保持包处理与台账能力（优先级：P3）

**目标**：解压、分类、台账、结果持久化、报告和原包完整性不受规则删除影响。

**独立测试**：含 KPI + 台账 + 非 KPI 数据的合成包完成全流程，KPI 可运行、台账写入、分类目录齐全、非 KPI 无规则结果、原包 SHA-256 不变；无 KPI 输入时唯一普通结果为 KPI skip。

### 测试

- [X] T025 [P] [US3] 更新 `tests/test_real_package.py`，删除旧规则直接执行/契约快照，保留并强化成员分类、清单、设备台账和 KPI 数据存在性断言；非 KPI 内容不得被当作活动规则证据。
- [X] T026 [P] [US3] 更新 `tests/test_inventory_task_flow.py` 与 `tests/test_baseline_extraction.py`，断言 KPI-only 任务仍写入设备台账，7 个分类目录和 manifest 完整，非 KPI 文件被保留。
- [X] T027 [P] [US3] 在 `tests/test_kpi_only_rule_library.py` 新增端到端用例：含 KPI 的合成包产生 1 条 KPI 普通结果并写入至少 1 台设备；无 KPI 的合成包产生唯一 `skip` 且 `skip_reason` 非空；两次执行前后原包 SHA-256 一致。
- [X] T028 [P] [US3] 在 `tests/test_kpi_only_rule_library.py` 新增包内容用例：alarm/config/log/resource/traffic 文件仍出现在对应分类目录，但新任务 `rules/` 与 `system.rules` 中不存在这些代码。

### 实现

- [X] T029 [US3] 更新 `tests/test_baseline_extraction.py`、`tests/test_inventory_task_flow.py` 和 `tests/test_extraction_*` 中受规则收缩影响的共享断言；不得删除分类、解压安全、路径穿越、资源预算或台账测试。
- [X] T030 [US3] 更新 `tests/fixtures/make_sample.py` 与 `tests/fixtures/make_real_package.py` 的看护断言，使混合数据继续覆盖包处理，但活动规则结果只期望 KPI；保持固定时间戳、幂等和既有样例只增不减。
- [X] T031 [US3] 运行 `tests/test_real_package.py tests/test_inventory_task_flow.py tests/test_baseline_extraction.py tests/test_kpi_only_rule_library.py`，确认 KPI、台账、解压、分类、skip 和 checksum 全部通过。

**检查点**：包处理与台账能力完整，非 KPI 文件仅作为证据保留。

---

## 阶段 6：收尾与横切关注点

**目的**：清理活动文档残留，完成契约与全量验证。

- [X] T032 [P] 更新 `docs/architecture.md`，将规则编排、规则清单、示例规则和活动能力说明收敛为 KPI-only；删除或明确标注已下线的告警、配置、日志、资源和话统规则说明。
- [X] T033 [P] 更新 `docs/data-model.md` 和 `docs/design/mechanisms.md`，明确 `RuleCategory` 历史兼容、hidden `pkg.extract.*`、历史结果读取和 KPI-only 活动目录；保留分类目录数据结构。
- [X] T034 [P] 检查 `README.md`、`AGENTS.md`、`docs/` 中仍把已删除规则描述为活动能力的文本；历史 `specs/` 与 `docs/superpowers/` 可作为历史记录保留，但必须避免被当前能力索引引用。
- [X] T035 清理活动中对已删除规则目录的导入、类型引用、fixture 名称和测试期望；允许保留的旧代码字符串仅限历史结果、分类数据、注入式测试或明确历史文档。
- [X] T036 运行 `rg -n "app\\.inspectors\\.(alarm|config|log|resource|traffic)|registry\\.get\\(\"(alarm|config|log|resource|traffic)" app tests web --glob '!**/node_modules/**'`，逐条确认无活动可执行引用。
- [X] T037 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确认 OpenAPI 没有 Schema/客户端破坏性漂移。
- [X] T038 运行 `.venv/bin/python build.py lint` 和 `.venv/bin/python build.py test`，记录退出码、通过数和失败数；任一失败不得进入合入。
- [X] T039 运行 `.venv/bin/python build.py verify`，确认 CLI/API 全流程、KPI 命中/跳过、台账、报告和原包 checksum。
- [X] T040 运行 `.venv/bin/python build.py web-build` 和 `.venv/bin/python build.py e2e`；若仅因子集耗时，至少运行规则目录、任务详情、历史详情和 KPI 场景相关 spec，并在报告中列出实际命令。
- [X] T041 按 quickstart.md 逐项复核，核对 spec.md 的 FR-001 至 FR-015、SC-001 至 SC-008 均有测试或验证证据；将本文件已完成项标记为 `[X]`。

---

## 依赖与执行顺序

```text
T001 → T002 → T003 → T004
                      ├─→ T005/T006/T007/T008
                      │      └─→ T009 → T010 → T011 → T012/T013/T014 → T015
                      ├─→ T016/T017/T018/T019/T020
                      │      └─→ T021 → T022/T023 → T024
                      └─→ T025/T026/T027/T028
                             └─→ T029/T030 → T031
T015 + T024 + T031 → T032/T033/T034 → T035/T036 → T037 → T038 → T039 → T040 → T041
```

## 用户故事依赖

- **US1（P1）**：先收缩注册和生产模块；是 US2/US3 活动断言的基线。
- **US2（P2）**：依赖 US1 删除模块后仍能读取历史数据；不得通过恢复旧规则实现。
- **US3（P3）**：依赖 US1 的活动 KPI-only 配置；继续覆盖包处理与台账。

## 并行机会

- T005、T006、T007、T008 修改不同测试文件，可并行。
- T016、T017、T018、T019、T020 修改不同历史兼容测试，可并行。
- T025、T026、T027、T028 修改不同包处理/历史断言文件，可并行。
- T032、T033、T034 修改不同文档，可并行。

## MVP 范围

完成 T001-T015 即交付 US1：默认配置启动后活动普通规则只有 KPI，执行计划和新任务结果不再出现任何已删除规则。

## 需求覆盖

| 需求 | 任务 |
| --- | --- |
| FR-001、FR-002 | T005、T009、T010、T015 |
| FR-003、FR-004 | T005、T011、T013 |
| FR-005 | T010、T014、T031 |
| FR-006 | T006、T019、T020 |
| FR-007、FR-008 | T016、T017、T018、T021、T023、T024 |
| FR-009、FR-010 | T025、T026、T027、T028、T029、T031 |
| FR-011 | T014、T015 |
| FR-012 | T003、T016、T019、T023、T037 |
| FR-013 | T004、T007、T027、T028、T030 |
| FR-014 | T032、T033、T034 |
| FR-015 | T001、T027、T031、T039 |
