---
description: "KPI 基础数据入库与分类状态存储实现任务列表"
---

# 任务：KPI 基础数据入库与分类状态存储

**输入**：来自 `specs/012-kpi-git-db-catalog/` 的设计文档

**前置条件**：`plan.md`、`spec.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`

**测试**：本功能涉及契约、数据模型、执行器和全流程，必须采用 TDD；每个用户故事先写测试并确认失败，再实现。

**格式**：`[ID] [P?] [Story?] 描述`

- `[P]`：文件边界独立，可与同阶段其他 `[P]` 任务并行。
- `[US1]` 到 `[US5]`：对应用户故事。
- 未标记 Story 的任务属于共享基础或收尾工作。

---

## 阶段 1：设置

**目的**：建立本功能的目录边界与配置入口。

- [x] T001 创建 `app/tools/__init__.py` 和 `deploy/data/.gitkeep`，为离线 KPI 目录工具与权威 JSON 建立目录结构。
- [x] T002 在 `app/core/config.py` 中新增 `kpi_catalog_path` 配置，默认 `deploy/data/kpi_catalog.json`，并使用 `settings.resolved()` 解析绝对路径；不得引入第二套构建入口或运行时 YAML 路径。

**检查点**：目录与配置路径就绪，未触碰旧 YAML 行为。

---

## 阶段 2：基础层（阻塞所有用户故事）

**目的**：先固定 API 契约、Pydantic 模型、Git JSON 模型和数据库表模型。

- [x] T003 更新 `docs/api/openapi.yaml`：新增 `GET /api/v3/kpi/resource-metrics`、`PUT /api/v3/kpi/resource-metrics/classification`、`GET /api/v3/kpi/resource-metrics/classification-audits`、`GET /api/v3/tasks/{task_id}/kpi/catalog-snapshot`；定义资源分页、分类请求/响应、审计分页和快照 Schema。分类请求必须包含 `operator`，不得包含 `expected_revision`。
- [x] T004 在 `docs/api/openapi.yaml` 中删除 `POST /api/v2/kpi/resource-metrics`、`GET /api/v2/kpi/resource-metrics`、`PUT /api/v2/kpi/resource-metrics/classification` 及其专用 Schema，保留任务、规则等其他 v2 接口。
- [x] T005 在 `app/models/schemas.py` 中实现 v3 KPI 资源、分类和快照 Pydantic 模型：基础字段为 `resource_id/key/name_zh/name_en`，分类域为 `unclassified/call/api/media`；`metric_keys` 最多 100 个且唯一。
- [x] T006 [P] 在 `app/models/db.py` 中定义 `KpiClassification`、`KpiClassificationRevision`、`KpiClassificationAudit`；`domain` 可空表示未分类，时间字段使用 UTC 且命名为 `created_at/updated_at/operated_at`。
- [x] T007 在 `app/inspectors/kpi/catalog.py` 中新增 Git JSON v1 数据结构、严格校验错误和加载器：校验 `schema_version`、未知字段、重复 key、非法资源 ID、空名称、规则引用和公式循环依赖；不解析 YAML。
- [x] T008 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确认 OpenAPI、Pydantic 和 `web/src/api/client.ts` 一致。

**检查点**：契约和共享模型可用；旧 v2 KPI 资源契约已移除；实现不得再扩展 YAML 资源逻辑。

---

## 阶段 3：用户故事 1 - 维护版本化 KPI 基础全集（优先级：P1）🎯 MVP

**目标**：维护人员用资源 CSV 离线生成确定性 Git JSON；运行页面只读取生成后的基础定义。

**独立测试**：用临时 CSV 执行生成器两次，输出字节一致；修改 `deploy/data/kpi_catalog.json` 后打开基础指标配置页面展示新版本指标，数据库分类状态不被改写。

### 测试

- [x] T009 [P] [US1] 在 `tests/test_kpi_catalog_generator.py` 编写资源 CSV 生成器测试：合法 `ME_*/UNIT_*`、稳定 key 排序、`unit_key` 固定为 null、`source_csv_sha256` 正确、重复执行字节一致。
- [x] T010 [P] [US1] 在 `tests/test_kpi_catalog_generator.py` 编写非法输入测试：非法表头、非法资源 ID、空名称、重复资源 ID、重复稳定 key、未知前缀；断言错误包含行号或资源 ID 且不生成部分文件。
- [x] T011 [P] [US1] 在 `tests/test_kpi_catalog_composition.py` 编写 Git JSON 加载测试：重复 key、非法 ID、未知规则引用和缺失公式输入均导致加载失败，且错误包含定位信息。

### 实现

- [x] T012 [US1] 在 `app/tools/kpi_catalog.py` 实现离线生成器：只解析固定表头 `资源id,中文描述,英文描述` 的资源 CSV；`ME_*` 写入 `metrics`，`UNIT_*` 写入 `units`，按稳定 key 升序，保留既有 `rules`，不推断类型、聚合、公式、阈值或展示规则。
- [x] T013 [US1] 在 `app/tools/kpi_catalog.py` 实现确定性原子输出：UTF-8/LF、稳定 JSON 序列化、记录 CSV SHA-256、输出前校验规则引用；命令入口为 `python -m app.tools.kpi_catalog generate --csv <path> --output <path>`。
- [x] T014 [US1] 创建空的合法 `deploy/data/kpi_catalog.json`：`schema_version=1`、空 `metrics`、空 `units`、空规则集合；不提交原始资源 CSV，不迁移旧 YAML 指标。
- [x] T015 [US1] 在 `app/services/kpi_resources.py` 中新增 Git JSON 基础资源查询模型：读取 `deploy/data/kpi_catalog.json`，与数据库分类状态组合为资源列表；基础字段不可由在线分类改写。
- [x] T016 [US1] 在 `app/api/router.py` 实现 `GET /api/v3/kpi/resource-metrics`：支持 `search/domain/include_missing/page/page_size`，返回 `base_data_version/classification_version/summary/items`；默认不显示 `missing_from_base=true` 记录。
- [x] T017 [US1] 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，更新 `web/src/pages/KpiResourcesPage.tsx` 使用 v3 资源接口展示资源 ID、中英文名和业务域；移除 CSV 上传控件与导入调用。
- [x] T018 [US1] 运行 US1 专属测试与 `.venv/bin/python build.py web-build`，确认基础指标随 Git JSON 展示、分类状态不被重新生成影响。

**检查点**：MVP 可用：离线生成、Git 展示和基础数据查询完成。

---

## 阶段 4：用户故事 2 - 在线分类结果持久化（优先级：P1）

**目标**：分类状态、操作人和审计保存到数据库；批量操作原子生效；不再写 YAML。

**独立测试**：不改 Git JSON，完成分类后重启服务并刷新页面，状态保持；批量中一个失败时整批回滚。

### 测试

- [x] T019 [P] [US2] 在 `tests/test_kpi_classification_db.py` 编写数据库测试：单条与批量分类成功、失败回滚、修订号只在成功请求后递增一次、审计包含操作时间/类型/操作人/前后状态。
- [x] T020 [P] [US2] 在 `tests/test_kpi_classification_db.py` 编写边界测试：未分类写入 `NULL`、跨域修改按完成顺序最后写入生效、不校验期望修订号、基础指标移除后分类记录保留且恢复后复用。
- [x] T021 [P] [US2] 在 `tests/test_kpi_resource_api_v3.py` 编写分类 API 契约测试：API 必须显式传 `operator`；请求包含 `expected_revision` 时契约校验失败；批量成功返回新 `classification_version`。
- [x] T022 [P] [US2] 在 `tests/test_kpi_resource_api_v3.py` 编写分类审计查询测试：支持 `metric_key/operator/domain` 过滤，按操作时间倒序分页，并返回操作时间/类型/操作人/前后状态。

### 实现

- [x] T023 [US2] 在 `app/models/db.py` 的 `init_db()` 中确保 KPI 分类、修订、审计表随 `Base.metadata.create_all()` 创建；不提供旧 YAML 迁移。
- [x] T024 [US2] 在 `app/services/kpi_resources.py` 实现数据库分类服务：同一事务内保存单条/批量状态、每个目标指标写审计、成功请求递增一次 `kpi_classification_revisions.revision`；数据库失败时抛出统一错误。
- [x] T025 [US2] 在 `app/services/kpi_resources.py` 实现引用保护：被公式输入、阈值或容量规则引用且已分类的指标不能换域或改回未分类；从未分类到首次分类允许；任一失败整批回滚。
- [x] T026 [US2] 在 `app/api/router.py` 实现 `PUT /api/v3/kpi/resource-metrics/classification`：请求 `metric_keys/domain/operator`，支持 `unclassified`；响应返回 `classification_version/domain/metric_keys/audited_count`。
- [x] T027 [US2] 在 `app/api/router.py` 实现 `GET /api/v3/kpi/resource-metrics/classification-audits`：支持 `metric_key/operator/domain/page/page_size`，按操作时间倒序返回分页审计。
- [x] T028 [US2] 更新 `web/src/pages/KpiResourcesPage.tsx`：提供操作人输入和批量分类控件；支持分类到三个业务域与改回未分类；调用 v3 接口，不发送期望修订号；提供分页审计查看；成功后刷新并显示新分类修订号。
- [x] T029 [US2] 在 `app/cli.py` 增加本地 `classify-kpi` 子命令：复用数据库分类服务和引用保护，审计操作人固定为 `cli`，不读写 YAML。
- [x] T030 [US2] 运行 US2 专属测试、重启 SQLite 文件验证分类持久化，并确认不生成或更新 `deploy/config/kpi/*.yaml`。

**检查点**：分类治理完整可用，事务、审计和引用保护通过。

---

## 阶段 5：用户故事 3 - 运行时组合 Git 与数据库（优先级：P1）

**目标**：任务执行使用 Git 基础/规则数据与数据库分类组合出的有效目录。

**独立测试**：相同基础版本与分类状态生成相同目录；分类变化后新任务使用新目录，旧任务快照不变；数据库不可用时任务失败。

### 测试

- [x] T031 [P] [US3] 在 `tests/test_kpi_catalog_composition.py` 编写有效目录组合测试：已分类指标进入对应领域、未分类不进入领域、规则引用完整、失效分类记录不生成领域指标。
- [x] T032 [P] [US3] 在 `tests/test_kpi_task_snapshot.py` 编写快照测试：任务启动写 `output/<task_id>/kpi/kpi_catalog_snapshot.json`，包含 `base_data_version/classification_version/captured_at/完整有效 metrics/完整 rules`。
- [x] T033 [P] [US3] 在 `tests/test_kpi_task_snapshot.py` 编写重跑与失败测试：单规则重跑优先读取既有快照；快照损坏时失败；数据库不可用时不回退 YAML 或空目录。
- [x] T034 [P] [US3] 在 `tests/test_kpi_single_rule.py` 扩展 CLI/API 一致性测试：相同快照下 `kpi.call`、`kpi.api`、`kpi.media` 生成相同领域目录与同构结果。

### 实现

- [x] T035 [US3] 创建 `app/services/kpi_catalog.py`：加载 Git JSON、计算文件 SHA-256、读取数据库分类修订和状态、组合按领域有效目录；目录错误使用 `kpi_catalog_invalid` 等统一错误码。
- [x] T036 [US3] 在 `app/services/kpi_catalog.py` 实现任务快照服务：首次任务执行时原子写快照，单规则重跑复用快照；快照缺失时加载当前配置补写，不提供手动刷新开关。
- [x] T037 [US3] 在 `app/services/tasks.py` 和 `app/cli.py` 的任务执行路径中确保任务开始前获得 KPI 快照；数据库、Git JSON 或快照校验失败时任务失败，不继续执行 KPI 规则。
- [x] T038 [US3] 更新 `app/inspectors/kpi/common.py`：源列匹配仅使用基础 `name_zh/name_en` 的规范化文本；不建立别名机制；KPI metadata 增加 `base_data_version` 和 `classification_version`。
- [x] T039 [US3] 更新 `app/inspectors/kpi/call.py`、`app/inspectors/kpi/api.py`、`app/inspectors/kpi/media.py`：从任务快照读取领域目录；保持 `source_patterns`、优先级、状态语义、结果契约和单文件错误隔离。
- [x] T040 [US3] 运行 US3 专属测试、`.venv/bin/python build.py test` 和 `.venv/bin/python build.py verify`，确认相同配置结果一致、配置变化后新任务更新且旧任务不变。

**检查点**：巡检运行时脱离 YAML，双模式共享同一路径。

---

## 阶段 6：用户故事 4 - 启用新模型并退役旧 YAML（优先级：P2）

**目标**：系统只读取 Git JSON 与数据库；旧 YAML 和在线 CSV 导入完全退役。

**独立测试**：部署目录保留旧 YAML 时，资源查询、分类和巡检都不读取或更新它；在线 API 没有 CSV 导入。

### 测试

- [x] T041 [P] [US4] 在 `tests/test_kpi_resource_api_v3.py` 编写旧入口退役测试：`/api/v2/kpi/resource-metrics` 及导入/分类端点返回 404；`/api/v3` 不提供 CSV 导入。
- [x] T042 [P] [US4] 在 `tests/test_kpi_catalog_composition.py` 编写旧 YAML 隔离测试：`deploy/config/kpi/*.yaml` 存在或内容损坏时，运行时仍只使用 Git JSON + DB，不读取、不更新、不回退。
- [x] T043 [P] [US4] 在 `tests/test_kpi_resource_api_v3.py` 编写失效记录测试：Git 移除指标后默认列表不显示；`include_missing=true` 可识别失效分类记录；基础指标恢复后复用状态。

### 实现

- [x] T044 [US4] 从 `app/services/kpi_resources.py` 删除 YAML registry、在线 CSV 解析导入、文件审计和 `expected_revision` 逻辑；保留必要的数据库/Git 组合服务并更新调用方。
- [x] T045 [US4] 从 `app/api/router.py` 删除旧 `/api/v2` KPI 资源查询、导入与分类路由，接入 `/api/v3` 实现；确认调度器与前端没有调用已删除接口。
- [x] T046 [US4] 删除 `deploy/config/kpi/api.yaml`、`deploy/config/kpi/call.yaml`、`deploy/config/kpi/media.yaml` 及不再使用的 `deploy/config/kpi/common.yaml`；不创建迁移工具。
- [x] T047 [US4] 清理 `tests/test_kpi_resource_metrics.py`、`tests/test_kpi_config_generator.py`、`tests/test_kpi_csv_rules.py` 中对旧 YAML/在线导入的断言，保留并迁移仍适用于 KPI 执行行为的场景。
- [x] T048 [US4] 运行 `.venv/bin/python build.py test` 和 `.venv/bin/python build.py verify`，确认旧文件删除后 KPI 流程仍能完成。

**检查点**：旧事实来源退役，在线只能查询和分类。

---

## 阶段 7：用户故事 5 - 历史任务可追溯（优先级：P2）

**目标**：审计人员可查看任务配置快照与两个配置版本；后续变更不改变历史解释。

**独立测试**：完成任务后修改 Git JSON 或分类，历史任务 API 仍返回原快照，规则结果中的版本不变。

### 测试

- [x] T049 [P] [US5] 在 `tests/test_kpi_task_snapshot.py` 编写任务快照 API 测试：任务存在返回快照；任务不存在 404；快照缺失 409；快照损坏 500。
- [x] T050 [P] [US5] 在 `tests/test_kpi_single_rule.py` 编写追溯测试：完成任务后修改基础数据和分类，历史结果 metadata 与快照中的 `base_data_version/classification_version/metrics/rules` 均不变。

### 实现

- [x] T051 [US5] 在 `app/api/router.py` 实现 `GET /api/v3/tasks/{task_id}/kpi/catalog-snapshot`：只读取任务现场，不触发重载 Git 或数据库；使用统一错误契约。
- [x] T052 [US5] 更新任务详情/KPI 结果前端展示：在 `web/src/pages/TaskDetailPage.tsx` 或现有 KPI 组件中展示 `base_data_version` 缩略值、`classification_version`，并可查看/下载完整快照；使用生成客户端。
- [x] T053 [US5] 运行 US5 专属测试，并手工验证“任务完成 -> 修改配置 -> 打开历史任务”的可追溯场景。

**检查点**：历史任务配置自解释且不可变。

---

## 阶段 8：收尾与横切关注点

**目的**：修复前端构建告警，完善文档与质量门禁。

- [x] T054 [P] [US-CLOSE] 在 `tests/test_kpi_catalog_scale.py` 编写 1000 行资源全集规模测试：生成器完成、目录加载和分页查询均成功，作为规格性能目标的功能性回归。
- [x] T055 更新 `web/src/App.tsx`：使用 `React.lazy` + `Suspense` 对任务、基础指标、规则管理、数据字典页面做路由级懒加载，并保持桌面优先和克制加载态。
- [x] T056 更新 `web/vite.config.ts`：通过 `build.rollupOptions.output.manualChunks` 拆分 `react/react-dom/react-router-dom`、`antd` 和 `echarts`；不得移除业务依赖。
- [x] T057 [P] 更新 `docs/architecture.md` 和 `docs/data-model.md`：记录 Git JSON、数据库分类/审计、任务快照、引用保护、旧 YAML 退役和 `/api/v3` 边界；接口细节引用 OpenAPI，不复制完整清单。
- [x] T058 [P] 检查 `specs/012-kpi-git-db-catalog/` 与 `docs/` 链接一致性；确认中文文档、英文标识符和 UTC `*_at` 命名约定。
- [x] T059 运行 `.venv/bin/python build.py lint`，修复所有 Ruff check/format 问题。
- [x] T060 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确认最终契约与生成客户端一致。
- [x] T061 运行 `.venv/bin/python build.py test` 和 `.venv/bin/python build.py verify`，确认全流程、CLI/API 一致性、1000 行规模测试和历史快照通过。
- [x] T062 运行 `.venv/bin/python build.py web-build`，确认构建成功且没有 chunk 大于 500 kB 告警；若有新增告警，必须继续修复而不是调高阈值。
- [x] T063 按 `specs/012-kpi-git-db-catalog/quickstart.md` 执行端到端验证，记录实际命令结果；确认导航为「基础指标」、页面标题为「基础指标配置」，且无资源 CSV 上传入口。

---

## 依赖与执行顺序

### 阶段依赖

1. 阶段 1 设置完成后进入阶段 2。
2. 阶段 2 契约与模型阻塞所有用户故事。
3. 用户故事按 US1 → US2 → US3 → US4 → US5 执行。
4. 阶段 8 依赖全部用户故事完成。

### 用户故事内部依赖

- **US1**：T009/T010/T011 可并行；T012 依赖测试；T013 依赖 T012；T015 依赖基础层；T016 依赖 T015；T017 依赖 T016；T018 最后验证。
- **US2**：T019/T020/T021/T022 可并行；T023 依赖 T022；T024 依赖 T023；T025 依赖 T024；T026/T027/T028/T029 依赖 T025；T030 最后验证。
- **US3**：T031/T032/T033/T034 可并行；T035 依赖基础层；T036 依赖 T035；T037 依赖 T036；T038/T039 依赖 T037；T040 最后验证。
- **US4**：T041/T042/T043 可并行；T044 → T045 → T046 → T047；T048 最后验证。
- **US5**：T049/T050 可并行；T051 依赖 T050；T052 依赖 T051；T053 最后验证。
- **收尾**：T054 先建立规模回归；T055/T056/T057/T058 可并行；T059 → T060 → T061 → T062 → T063 按质量门禁顺序执行。

### 并行机会

- 阶段 2 中 OpenAPI/Pydantic 与数据库模型可按文件边界并行，但 T008 必须最后生成客户端。
- 每个用户故事的测试任务可先行并行编写。
- US4 退役测试与 US5 追溯测试可并行，但实现需在 US3 快照服务完成后进行。
- 前端懒加载、文档更新与规模回归可在用户故事完成后并行。

## 实现策略

### MVP 优先

1. 完成阶段 1 + 阶段 2。
2. 完成 US1，可离线生成并展示 Git 基础数据。
3. 停止验证 MVP，再进入 US2。

### 增量交付

1. US2 增加持久化分类与审计。
2. US3 打通运行时组合和任务快照。
3. US4 退役旧 YAML 和在线导入。
4. US5 补齐历史追溯。
5. 阶段 8 完成前端性能与全量质量门禁。

### 完成标准

- 全部任务复选框为 `[X]`。
- `spec.md/plan.md/tasks.md` 无未解决的矛盾。
- 质量门禁全部通过，且有最新命令输出作为证据。
- Vite 大包告警消失。
- 旧 YAML、在线 CSV 导入和 `expected_revision` 行为不存在。
