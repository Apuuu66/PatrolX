---
description: "KPI 基础数据管理实现任务列表"
---

# 任务：KPI 基础数据管理

**输入**：来自 `specs/013-kpi-base-data-management/` 的设计文档

**前置条件**：`plan.md`、`spec.md`、`research.md`、`data-model.md`、`contracts/kpi-split-config.md`、`quickstart.md`

**测试**：本功能涉及配置契约、目录聚合、离线导入、任务快照、重跑边界和分类兼容性，必须采用 TDD；相关用户故事先写测试并确认失败，再实现。

**格式**：`[ID] [P?] [Story?] 描述`

- `[P]`：文件边界独立，可与同阶段其他 `[P]` 任务并行。
- `[US1]` 到 `[US4]`：对应用户故事。
- 未标记 Story 的任务属于共享基础或收尾工作。

---

## 阶段 1：设置

**目的**：建立拆分配置目录和配置入口。

- [ ] T001 在 `app/core/config.py` 中将 KPI 单文件配置设置替换为 `kpi_data_dir`，默认 `deploy/data/kpi`；新增 `base/metrics.json`、`base/units.json` 和五个规则文件的固定路径访问器，保留 `settings.resolved()` 语义。
- [ ] T002 [P] 在 `tests/test_kpi_catalog_split_config.py` 中添加设置与固定路径测试：默认目录为 `deploy/data/kpi`，七类文件路径固定，环境变量覆盖目录后仍指向目标子文件。

**检查点**：目录契约入口就绪，旧文件仍可存在但不再被代码引用。

---

## 阶段 2：基础层（阻塞所有用户故事）

**目的**：完成一次性数据迁移、目录聚合加载和严格校验。

### 测试

- [ ] T003 [P] 在 `tests/test_kpi_catalog_split_config.py` 编写文件级 Schema 测试：七个文件齐全时可加载；任一文件缺失、JSON 损坏、重复对象字段、未知字段或 `schema_version != 1` 时失败；`metrics.json.source_csv_sha256`、每个 `metrics[]/units[]` 的四个公共字段、`common.json.input_timezone/budgets` 以及各类规则数组的容器字段均为必填。
- [ ] T004 [P] 在 `tests/test_kpi_catalog_split_config.py` 编写跨文件引用测试：`ME_*/UNIT_*` 的 `resource_id/key` 全局唯一；`unit_key` 只能为 `null`；指标规则、公式、阈值、容量和展示规则引用缺失时失败；公式循环时失败。
- [ ] T005 [P] 在 `tests/test_kpi_catalog_split_config.py` 编写内容指纹测试：固定按 `base/metrics.json`、`base/units.json`、`rules/common.json`、`rules/metric-rules.json`、`rules/thresholds.json`、`rules/capacity-rules.json`、`rules/display-rules.json` 顺序计算 `base_data_version`；任一字节变化都会改变指纹。

### 实现

- [ ] T006 [P] 创建 `deploy/data/kpi/base/metrics.json`、`base/units.json` 和 `rules/common.json`、`metric-rules.json`、`thresholds.json`、`capacity-rules.json`、`display-rules.json`；内容从现有 `deploy/data/kpi_catalog.json` 按类型拆分，保持 UTF-8、LF、缩进 2 和确定性字段顺序。
- [ ] T007 在 `app/inspectors/kpi/catalog.py` 实现 `load_kpi_catalog()` 目录读取：只读取七个固定文件，使用严格 JSON 解析；聚合成既有 `KpiGitCatalog` 内存结构；执行完整跨文件校验；按固定文件集合计算 `base_data_version`，不回退旧单文件。
- [ ] T008 在 `app/services/kpi_catalog.py` 和 `app/services/kpi_resources.py` 中把所有当前配置读取入口切换到目录加载器；保持有效目录组合、SQLite 分类、任务快照契约和资源查询输出字段不变。
- [ ] T009 从仓库删除 `deploy/data/kpi_catalog.json`，并更新/移除直接断言旧单文件的测试；确认 `app/`、`tests/` 和 `deploy/` 中没有代码路径继续将其作为权威配置。

**检查点**：目录配置可加载，非法目录显式失败，旧单文件不再存在或被引用。

---

## 阶段 3：用户故事 1 - 按类型维护指标配置（优先级：P1）🎯 MVP

**目标**：离线刷新基础指标和预留单位时，不触碰任何规则文件；人工规则修改保持独立。

**独立测试**：复制当前配置目录，执行资源 CSV 导入后比较七类文件；只允许 `metrics.json` 和 `units.json` 变化，规则文件字节不变。

### 测试

- [ ] T010 [P] [US1] 在 `tests/test_kpi_catalog_tool.py` 编写拆分导入测试：资源 CSV 有效时只重写 `deploy/data/kpi/base/metrics.json` 和 `base/units.json`，五个规则文件字节不变；`ME_*` 进入 `metrics`，`UNIT_*` 进入 `units`，稳定 key 排序且 `unit_key=null`。
- [ ] T011 [P] [US1] 在 `tests/test_kpi_catalog_tool.py` 编写完整替换测试：CSV 移除既有指标后目标 `metrics.json` 移除该指标；该指标被公式、阈值或容量规则引用时导入或聚合校验失败，规则文件和基础文件不产生部分替换。
- [ ] T012 [P] [US1] 在 `tests/test_kpi_catalog_tool.py` 编写无效输入测试：表头错误、空 CSV、非法 `ME_*/UNIT_*`、空名称、重复 `resource_id/key` 时命令失败，错误包含行号或资源 ID。

### 实现

- [ ] T013 [US1] 在 `app/tools/kpi_catalog.py` 中实现 `generate --csv <path> --data-dir <path>`：只解析表头 `资源id,中文描述,英文描述`；只写 `base/metrics.json` 和 `base/units.json`；读取既有规则目录用于完整校验，但永不写规则文件。
- [ ] T014 [US1] 在 `app/tools/kpi_catalog.py` 中实现确定性原子输出：UTF-8、LF、缩进 2、稳定字段顺序、记录 `source_csv_sha256`；任何读取、解析、校验或写盘失败时目标文件保持原样。
- [ ] T015 [US1] 用临时目录和当前资源 CSV 执行 US1 独立验证：导入后比较规则文件 SHA-256，确认不变；新增基础指标无规则时仍保留在 `metrics.json`，不自动进入业务域巡检。

**检查点**：基础数据刷新与规则维护完全隔离。

---

## 阶段 4：用户故事 2 - 保持任务结果可追溯（优先级：P1）

**目标**：新任务记录当前完整有效配置；旧任务重跑继续使用既有快照；缺快照的单规则重跑失败。

**独立测试**：完成任务后修改阈值，创建新任务并比较两个快照；旧任务快照不变，新任务包含新阈值；对旧任务执行指定规则重跑时快照缺失则失败。

### 测试

- [ ] T016 [P] [US2] 在 `tests/test_kpi_task_snapshot.py` 编写快照生成测试：新任务首次需要 KPI 配置时从拆分目录组合 SQLite 分类生成 `output/<task_id>/kpi/kpi_catalog_snapshot.json`；`metrics` 和 `rules` 为完整有效配置，`captured_at` 使用 UTC；配置内容不变时两次生成的 `base_data_version` 和有效配置一致，仅 `captured_at` 可不同。
- [ ] T017 [P] [US2] 在 `tests/test_kpi_task_snapshot.py` 编写不可变测试：已有有效快照时修改 `deploy/data/kpi/` 配置和分类状态，再次全量重跑和指定规则重跑都复用快照，快照文件字节不变。
- [ ] T018 [P] [US2] 在 `tests/test_kpi_task_snapshot_missing.py` 编写缺失快照测试：已有任务缺少 `kpi_catalog_snapshot.json` 时，指定规则重跑失败并提示快照缺失；全量重跑缺少快照可初始化补写一次，已有快照仍不被覆盖。
- [ ] T019 [P] [US2] 在 `tests/test_kpi_deterministic_rerun.py` 编写确定性回归：使用相同输入包和相同 KPI 快照执行 KPI 巡检两次，剥离 `task_id`、执行时间、耗时和运行态标识后断言规则结果一致。

### 实现

- [ ] T020 [US2] 在 `app/services/kpi_catalog.py` 中保持快照路径和 `KpiTaskCatalogSnapshot` 契约不变；新任务首次需要 KPI 配置时生成快照，已有有效快照永远复用，损坏快照显式失败。
- [ ] T021 [US2] 在 `app/cli.py` 的 `run_single_rule()` 中区分已有任务快照缺失场景：任务已完成且 `output/<task_id>/kpi/kpi_catalog_snapshot.json` 缺失时立即失败；不调用当前目录配置补写历史快照。
- [ ] T022 [US2] 在 `app/cli.py`、`app/services/tasks.py` 和 `app/api/router.py` 的任务/重跑路径中确认全量重跑不覆盖有效快照；统一错误上下文包含 `task_id` 和快照相对路径，不新增业务 API 字段。同步调整 `web/src/pages/TaskDetailPage.tsx`，不把 `base_data_version` 或 `classification_version` 展示为配置版本。
- [ ] T023 [US2] 执行 US2 独立验证：完成任务 -> 修改规则 -> 新任务；比较新旧快照，确认旧快照不变且新快照包含新规则；运行 T019 确定性回归。

**检查点**：历史结果可追溯，配置变化不会污染旧任务。

---

## 阶段 5：用户故事 3 - 配置错误尽早暴露（优先级：P2）

**目标**：重复资源、缺失引用、公式循环、无效阈值和必填项错误在生成新任务快照前被拒绝，错误可定位。

**独立测试**：构造非法目录并调用目录加载或新任务快照服务，断言失败、错误信息含文件和位置、不生成快照。

### 测试

- [ ] T024 [P] [US3] 在 `tests/test_kpi_catalog_split_config.py` 中补齐可定位错误测试：重复指标、未知规则引用、公式循环、无效阈值引用分别触发失败；错误包含相对文件路径、数组下标或字段路径；本任务只断言错误定位，不重复 T003/T004 的基础 Schema 场景。
- [ ] T025 [P] [US3] 在 `tests/test_kpi_task_snapshot.py` 中补齐新任务防护测试：拆分目录校验失败时 `load_task_kpi_config()` 不创建 `kpi_catalog_snapshot.json`，不回退旧配置，异常上下文包含根因。
- [ ] T026 [P] [US3] 在 `tests/test_kpi_catalog_split_config.py` 中补齐单位预留测试：`UNIT_*` 可登记；`ME_*` 的 `unit_key` 非空时失败；单位存在与否不改变阈值、公式或巡检计算。

### 实现

- [ ] T027 [US3] 在 `app/inspectors/kpi/catalog.py` 中完善跨文件错误定位：错误统一包含相对路径、JSON 数组下标或字段路径；保持单一异常类型 `KpiCatalogError`，不吞掉根因。
- [ ] T028 [US3] 在 `app/services/kpi_catalog.py` 中确认配置加载失败与数据库失败分开报告：配置错误先于分类数据库读取；任一失败都不写任务快照，不静默跳过。
- [ ] T029 [US3] 执行 US3 独立验证：用非法样例目录分别运行目录加载和新任务快照创建，确认全部失败且无部分输出。

**检查点**：非法配置无法进入任务结果。

---

## 阶段 6：用户故事 4 - 继续使用现有分类方式（优先级：P2）

**目标**：拆分配置后，业务域分类、审计、未分类指标和移除指标的历史记录行为保持不变。

**独立测试**：在现有基础指标配置页面将已登记未分类指标分类到呼叫域；检查有效目录、分类审计和页面待分类线索；重新导入同名同 key 指标后分类仍保留。

### 测试

- [ ] T030 [P] [US4] 在 `tests/test_kpi_resource_api_v3.py` 和 `tests/test_kpi_classification_db.py` 中补齐分类回归：未分类指标可通过现有 API 分类到 `call`，响应与审计记录成功；非法域和失败事务不产生部分分类。
- [ ] T031 [P] [US4] 在 `tests/test_kpi_catalog_tool.py` 和 `tests/test_kpi_classification_db.py` 编写重导入兼容测试：同名同 key 指标重新导入后，SQLite 分类状态保留；名称更新不重置分类或清空审计。
- [ ] T032 [P] [US4] 在 `tests/test_kpi_task_snapshot.py` 和 `tests/test_kpi_classification_db.py` 编写移除指标测试：基础指标被 CSV 移除且未被规则引用时，不进入新任务快照；既有分类记录不物理删除，分类修订和审计不变。
- [ ] T033 [P] [US4] 在 `tests/test_kpi_resource_metrics.py` 和 `tests/test_kpi_real_sample_api.py` 编写未登记指标线索测试：CSV 中的未登记指标通过 `missing_from_base` / `metric_not_registered` 展示为待分类线索；KPI 规则状态仍为 `pass/warn/fail/error/skip`，不因线索变成 `fail`。
- [ ] T034 [P] [US4] 在 `tests/test_kpi_resource_api_v3.py` 中增加禁止运行时导入回归：解析 `docs/api/openapi.yaml`，断言 KPI 资源路径集合不包含 CSV upload/import 端点；检查 `web/src` 不新增资源 CSV 上传入口。

### 实现

- [ ] T035 [US4] 在 `app/services/kpi_catalog.py` 中确认 `_effective_metrics()` 只把存在且已分类指标写入任务快照；移除指标保留数据库分类记录，未分类指标保留在拆分基础数据但不进入业务域。
- [ ] T036 [US4] 在 `app/services/kpi_resources.py` 和 `app/inspectors/kpi/common.py` 中保持现有分类状态、审计、`missing_from_base` 和未登记指标线索语义；不新增在线导入能力，不改变 KPI 规则状态映射。同步调整 `web/src/pages/KpiResourcesPage.tsx`，不把 `base_data_version` 或 `classification_version` 展示为配置版本。
- [ ] T037 [US4] 使用测试环境执行 US4 独立验证：通过现有 API 和基础指标配置页面完成分类，检查审计、重新导入分类保留、移除指标分类记录保留以及待分类线索展示；确认页面不再展示配置版本或分类修订。

**检查点**：拆分配置不改变日常分类操作和历史分类审计。

---

## 阶段 7：收尾与横切关注点

**目的**：同步文档、运行全量门禁并确认无契约漂移。

- [ ] T038 [P] 更新 `docs/architecture.md` 和 `docs/data-model.md`：记录 `deploy/data/kpi/` 七文件契约、CSV 完整替换、引用保护、快照不可变、分类兼容和旧单文件退役；接口细节继续引用 `docs/api/openapi.yaml`。
- [ ] T039 [P] 更新 `docs/design/entrypoints.md` 和 `docs/design/task-rerun.md`：替换离线导入命令为 `--data-dir deploy/data/kpi`，更新快照复用、指定规则重跑缺失快照失败和全量重跑初始化补写语义。
- [ ] T040 [P] 检查 `specs/013-kpi-base-data-management/` 与 `docs/` 中的链接和术语一致性：使用“拆分配置”“任务快照”“内容指纹”，不引入“目录版本/组合版本”概念。
- [ ] T041 运行 `.venv/bin/python build.py lint`，修复所有 Ruff check/format 问题。
- [ ] T042 运行 `.venv/bin/python build.py test`，确认目录加载、CSV 导入、资源接口、分类兼容、任务快照、重跑和现有 KPI 巡检回归全部通过；T022/T036 触碰前端后另运行 `cd web && npm run build`。
- [ ] T043 运行 `.venv/bin/python build.py verify`，确认本地全流程可使用拆分配置完成任务并生成快照；若输出契约意外变化，先停止并回到 Speckit review，不得静默修改契约。
- [ ] T044 按 `specs/013-kpi-base-data-management/quickstart.md` 执行最终验证：确认离线导入只改基础文件、旧任务快照不变、新任务使用新配置、现有分类界面仍可用。

---

## 依赖与执行顺序

### 阶段依赖

1. 阶段 1 设置完成后进入阶段 2。
2. 阶段 2 的目录加载和迁移阻塞所有用户故事。
3. 用户故事按 US1 → US2 → US3 → US4 执行。
4. 阶段 7 依赖全部用户故事完成。

### 用户故事内部依赖

- **US1**：T010/T011/T012 可并行；T013 依赖测试；T014 依赖 T013；T015 依赖 T014。
- **US2**：T016/T017/T018/T019 可并行；T020 依赖测试；T021/T022 依赖 T020；T023 依赖 T021/T022。
- **US3**：T024/T025/T026 可并行；T027 依赖测试；T028 依赖 T027；T029 依赖 T028。
- **US4**：T030/T031/T032/T033/T034 可并行；T035/T036 依赖相关测试；T037 依赖 T035/T036。

### 并行机会

- T002/T003/T004/T005 属于不同测试边界，可并行编写。
- T006 与测试任务可并行准备，但必须在 T007 前完成。
- 各用户故事内的测试任务分别可并行。
- T038/T039/T040 可在功能验证通过后并行执行。

## 实现策略

### MVP 优先

1. 完成阶段 1 + 阶段 2。
2. 完成 US1，实现基础数据与规则分离维护。
3. 停止并独立验证 MVP，再进入 US2。

### 增量交付

1. US2 打通任务快照、确定性结果和重跑边界。
2. US3 完成配置错误前置暴露。
3. US4 验证并保持现有分类能力。
4. 阶段 7 完成文档同步与全量质量门禁。

### 完成标准

- 全部任务复选框为 `[X]`。
- `spec.md`、`plan.md`、`tasks.md` 无未解决矛盾。
- `deploy/data/kpi_catalog.json` 不存在，也没有代码回退路径。
- 离线 CSV 导入永远不会改写规则文件。
- 新任务、旧任务、重跑、错误路径和分类操作符合规格与宪法。
- 质量门禁全部通过，并有最新命令输出作为证据。
