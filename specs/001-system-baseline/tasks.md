---
description: "系统基线功能实现任务列表"
---

# 任务：系统基线

**输入**：来自 `specs/001-system-baseline/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md 已就绪

**测试**：包含测试任务。本基线把执行模型收敛为“包名任务目录 + 规则源文件正则 + 单规则原地重算”。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事
- 描述中包含精确的文件路径

## 路径约定

- 后端代码位于 `app/`
- 前端代码位于 `web/src/`
- 后端测试位于 `tests/`
- 配置位于 `deploy/config/`

---

## 阶段 1：设置与契约同步（共享基础设施）

**目的**：为基线验证准备可复用的测试工具、样例上下文和阻塞实现的基线契约

- [x] T001 在 `tests/baseline_helpers.py` 中创建基线测试助手，封装临时 `uploads/`、`output/` 与 SQLite 环境运行本地任务
- [x] T002 在 `tests/baseline_helpers.py` 中添加 `wait_for_task()`、`load_task()`、`load_rule()`、`strip_volatile()` 工具，统一忽略 `executed_at` 与 `duration_ms`
- [x] T002A [Contract] 在 `docs/api/openapi.yaml` 中新增 `/api/v2` 基线契约：任务、系统、规则、发现、报告、重跑与删除接口；任务现场唯一使用 `task_id`；规则元数据暴露 `severity`、`source_patterns`；`/api/v2` 模型不包含 `system_id`、`artifacts`、`inputs[]` 和 `outputs_artifacts`；任务创建接口必须定义同名同 checksum 复用语义和同名不同 checksum 的 `409 package_checksum_conflict` 错误响应；`/api/v2` 不得提供 `force` 或删除重建语义。迁移期不得删除或改变 `/api/v1` 既有字段含义。
- [x] T002B [Contract] 根据 T002A 运行 `make gen-web-api`，更新前端 API 客户端引用到 `/api/v2`；同步契约测试与前端构建检查，且不新增 `/api/v1` 消费者。

**检查点**：后续测试可以稳定运行样例包并读取契约结果；`/api/v2` 契约和生成客户端已作为实现门禁同步

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：固化单任务目录、规则源文件契约、输出校验和安全解压约束

**⚠️ 关键**：本阶段完成前不得开始任何用户故事工作

- [x] T003 在 `app/models/schemas.py` 中添加模型校验：`status=skip` 时 `skip_reason` 必须非空；发现必须提供非空包相对 `source_file` 与 `evidence`；`evidence` 超过安全展示上限时必须截断，`source_file` 仍保留完整相对路径。
- [x] T004 在 `app/models/schemas.py` 中添加摘要校验：任务摘要计数等于规则数量，且各状态计数之和等于总数
- [x] T005 在 `app/services/store.py` 中固化文件存储分层：在线 SQLite 只保存任务运行元数据；解压数据、规则 JSON、报告和执行日志保留在 `output/<task_id>/`，本地模式无需数据库
- [x] T006 [P] 在 `tests/test_baseline_storage.py` 中验证 `TaskRecord` 不承载巡检业务证据，规则结果、报告和日志落在 `output/<task_id>/`，不出现 `system_id` 目录层或 artifacts 目录
- [x] T007 [P] 在 `tests/test_baseline_schemas.py` 中覆盖 skip 原因、发现可追溯性、摘要一致性校验，以及长 `evidence` 截断后 `source_file` 仍完整保留。
- [x] T008 在 `app/inspectors/base.py` 中为普通规则添加并校验 `source_patterns`：正则必须可编译、匹配任务目录内相对路径、禁止绝对路径和路径穿越
- [x] T009 在 `app/services/executor.py` 中校验 `pass`、`warn`、`fail` 结果的 metrics key/unit 与规则声明契约一致；不一致时记为 `error` 并写入结构化日志。规则执行异常必须转换为显式 `error` 结果，不得中止任务；`error` 结果的 metrics 和 findings 可以为空。
- [x] T010 [P] 在 `tests/test_baseline_registry.py` 中覆盖完整注册元数据校验矩阵：规则代码命名、`name`、`category`、`severity`、`priority`、`rule_version`、`description`、`recommendation`、空/非法 `source_patterns`、路径穿越模式和 metrics 契约不一致。
- [x] T011 [P] 在 `tests/test_baseline_archive.py` 中补充文件数、单文件大小、总量预算、链接拒绝、路径穿越和深层嵌套限制测试
- [x] T012 在 `app/core/archive.py` 中根据 T011 修复安全解压缺口，确保超限或异常归档产生可记录的 `ArchiveError`
- [x] T002C 在基础层完成后，在 `app/api/router.py` 中实现 `/api/v2` 任务、系统、规则、发现、报告、重跑与删除路由；迁移完成前保持 `/api/v1` 行为不变。
- [x] T002D [Contract] 将前端、后端契约测试和集成测试的 API 调用迁移到 `/api/v2`；确认没有新增 `/api/v1` 消费者。

**检查点**：单任务目录、源文件匹配契约、输出校验、解压安全约束、`/api/v2` 路由和消费者迁移已可作为用户故事的阻塞门禁

---

## 阶段 3：用户故事 1 - 执行离线巡检（优先级：P1）🎯 MVP

**目标**：一个受支持包按唯一包名成为唯一任务目录，安全分类解压，规则按 `source_patterns` 执行，并产出结果、报告与日志

**独立测试**：将样例包放入临时输入目录并运行离线流程，验证恰好生成一个任务目录，规则结果、报告、日志存在；无匹配数据的规则可见跳过

### 用户故事 1 的测试

- [x] T013 [P] [US1] 在 `tests/test_baseline_pipeline.py` 中验证单包生成单任务目录、类别目录、规则 JSON、`report.html` 与 `execution.log`
- [x] T014 [US1] 在 `tests/test_baseline_pipeline.py` 中验证唯一包名生成唯一 `task_id`；同一系统元数据下的不同包名必须形成不同任务，且任务结果互不合并
- [x] T014A [US1] 在 `tests/test_baseline_pipeline.py` 中验证同名同 checksum 包复用既有 `task_id` 与任务现场；同名不同 checksum 包返回冲突且不覆盖既有 `uploads/`、`output/`、规则结果、报告和日志；在线 API 断言错误码为 `package_checksum_conflict`。
- [x] T015 [P] [US1] 在 `tests/test_baseline_extraction.py` 中验证主包按类落位、嵌套子包 checksum 去重、重复执行不重复解压
- [x] T016 [US1] 在 `tests/test_baseline_extraction.py` 中验证格式错误或不可识别文件不中止任务，并在解压结果、执行日志或对应规则结果中可见
- [x] T016A [US1] 在 `tests/test_baseline_pipeline.py` 中注入运行时抛异常的规则样例，验证该规则结果为 `error`，结构化日志包含 `task_id` 与 `rule_code`，任务继续完成，其他规则结果保持可访问，并断言 `error` 结果的 metrics 与 findings 为空或显式为空集合。
- [x] T017 [P] [US1] 在 `tests/test_baseline_report.py` 中验证报告包含状态计数、规则摘要、发现来源/证据/建议、跳过原因和执行时间；发现按 `critical` → `high` → `medium` → `low` 排序，同级别按规则优先级和规则代码稳定排序。

### 用户故事 1 的实现

- [x] T018 [US1] 在 `app/inspectors/pkg.py` 中更新解压清单与规则结果：失败子包记录 checksum、目标目录、错误信息和未解压状态，不静默跳过
- [x] T019 [US1] 在 `app/core/classify.py` 与 `deploy/config/classify_rules.yaml` 中核对日志、KPI、话统、告警、配置、资源和 `other` 分类规则，补充缺失的真实样例映射
- [x] T020 [US1] 在 `app/cli.py` 中统一离线运行摘要输出：任务 ID、任务数、状态统计、报告路径和执行日志路径
- [x] T021 [US1] 在 `app/services/report.py` 与 `app/reports/templates/report.html.j2` 中修正 T017 暴露的报告内容缺口，保持 HTML 只在线预览、无下载入口

**检查点**：此时用户故事 1 应完整可用且可独立测试；`make verify` 与样例流水线测试通过

---

## 阶段 4：用户故事 2 - 审查结果（优先级：P2）

**目标**：用户可以从任务状态下钻到规则和发现，并追溯来源、证据、严重程度和建议

**独立测试**：读取已完成任务的 API 和报告，验证每个展示发现都有规则、来源位置、证据和建议；每条跳过规则有原因

### 用户故事 2 的测试

- [x] T022 [P] [US2] 在 `tests/test_baseline_review.py` 中验证任务摘要、系统、规则结果和发现的接口下钻路径，并断言发现包含非空包相对 `source_file`、截断后的 `evidence` 与 `recommendation`。
- [x] T023 [US2] 在 `tests/test_baseline_review.py` 中验证跳过规则通过系统、单规则接口和报告暴露 `skip_reason`
- [x] T024 [US2] 在 `tests/test_baseline_report.py` 中补充报告与契约结果的对应关系：报告展示的发现/跳过状态必须来自契约 JSON

### 用户故事 2 的实现

- [x] T025 [US2] 在 `app/api/router.py` 中保证任务、系统、单规则接口返回基线审查所需字段；hidden 内部规则计入任务摘要但不出现在公开规则列表中，其成功结果不单独泄漏。
- [x] T026 [US2] 在 `app/reports/templates/report.html.j2` 中为发现的严重程度、来源、证据、建议和跳过原因提供统一可读展示
- [x] T027 [P] [US2] 在 `web/src/pages/TaskDetailPage.tsx`、`web/src/pages/RuleDetailPage.tsx` 和 `web/src/components/StatusBadge.tsx` 中核对下钻、状态徽标与 `skip_reason` 展示，仅修复缺失项
- [x] T028 [US2] 运行 `make web-build` 验证审查页面使用最新 `/api/v2` 生成客户端并保持可构建。

**检查点**：用户故事 1 和 2 均应独立可用

---

## 阶段 5：用户故事 3 - 本地/在线一致（优先级：P3）

**目标**：同一包名在本地 CLI 与在线 API 中产生相同任务 ID、任务目录布局和一致的业务结果

**独立测试**：分别用 CLI 与 API 处理同一包，剥离执行标识和时间后比较任务统计、系统、规则、metrics 和 findings

### 用户故事 3 的测试

- [x] T029 [P] [US3] 在 `tests/test_baseline_consistency.py` 中比较本地与在线契约结果，忽略 `executed_at`、`duration_ms` 和运行标识，但比较规则状态、metrics 和 findings
- [x] T030 [US3] 在 `tests/test_baseline_consistency.py` 中验证两个任务携带相同系统元数据时仍保持任务目录、结果与日志隔离

### 用户故事 3 的实现

- [x] T031 [US3] 在 `app/cli.py` 与 `app/services/tasks.py` 中消除本地/在线执行路径的业务分歧，共享 `Executor`、包名 `task_id`、单任务存储布局和报告生成入口
- [x] T032 [US3] 在 `app/services/store.py` 中确保任务和规则结果使用同一 UTC 序列化与别名规则，避免双模式字段语义漂移

**检查点**：本地与在线结果一致性测试通过，模式同构约束得到回归保护

---

## 阶段 6：用户故事 4 - 重跑目标规则（优先级：P4）

**目标**：目标规则可独立重跑；规则按内部 `source_patterns` 读取任务目录内文件；结果、摘要和报告同步刷新

**独立测试**：完成一次巡检后重跑目标规则，验证目标结果按源文件模式刷新，摘要和报告更新，其他规则 JSON 内容和 mtime 不被无关改写

### 用户故事 4 的测试

- [x] T033 [P] [US4] 在 `tests/test_baseline_rerun.py` 中验证本地 CLI 与在线 API 单规则重跑后，目标规则 JSON、`task.json` 摘要和 `report.html` 更新，且无关规则结果不变
- [x] T034 [US4] 在 `tests/test_baseline_rerun.py` 中覆盖 `source_patterns` 匹配、无匹配文件时返回带原因的 `skip`，以及任务现场缺失时先幂等解压

### 用户故事 4 的实现

- [x] T035 [US4] 在 `app/services/executor.py` 中实现 `run_one()` 直接匹配目标规则 `source_patterns`、执行目标规则并替换目标结果；不实现规则间依赖图
- [x] T036 [US4] 在 `app/cli.py`、`app/services/tasks.py` 与规则文件内置运行入口中共用单规则重跑收尾：更新目标规则结果、任务摘要和 HTML 报告，保证前端 API 刷新后可读取最新结果

**检查点**：规则开发者可以只重跑目标规则并看到无关结果保留

---

## 阶段 7：用户故事 5 - 删除任务（优先级：P5）

**目标**：显式删除任务后，SQLite 记录、原始包输入、输出现场、报告和日志均无残留

**独立测试**：创建并完成任务后调用删除接口，验证任务不可访问，且 `uploads/<task_id>/` 与 `output/<task_id>/` 不存在

### 用户故事 5 的测试

- [x] T036A [US5] 在 `tests/test_baseline_delete.py` 中先验证任务完成后、未请求删除前，`uploads/<task_id>/`、`output/<task_id>/`、任务契约、规则 JSON、报告和日志持续可访问。
- [x] T037 [P] [US5] 在 `tests/test_baseline_delete.py` 中验证删除 API 移除 SQLite 记录、任务契约 JSON、规则 JSON、报告、日志和 `uploads/<task_id>/` 原始包
- [x] T038 [US5] 在 `tests/test_baseline_delete.py` 中验证删除后再次查询任务、系统、规则、报告和日志均返回 404，重复删除返回 404

### 用户故事 5 的实现

- [x] T039 [US5] 在 `app/services/tasks.py` 中显式清理任务级联目录，避免 `ignore_errors=True` 掩盖残留；无法完全删除时返回明确错误并记录日志
- [x] T040 [US5] 在 `app/api/router.py` 中保持删除接口 204/404 语义与 OpenAPI 契约一致

**检查点**：所有用户故事均应独立可用

---

## 阶段 8：收尾与横切关注点

**目的**：验证完整基线，清理实现并同步文档

- [x] T041 校验 `docs/api/openapi.yaml`、`app/models/schemas.py`、`app/api/router.py` 与 web 生成客户端全部使用 T002A 定义的 `/api/v2` 基线契约；确认 `/api/v1` 只处于迁移兼容状态且未被不兼容修改。
- [x] T042 [P] 在 `README.md`、`docs/architecture.md` 与 `specs/001-system-baseline/quickstart.md` 中核对基线命令、单任务目录布局和文档链接
- [x] T043 清理新增代码中的重复逻辑，保持规则互不引用、数据入口只通过 `source_patterns`
- [x] T043A 检查本功能中被修改执行或解析逻辑的巡检器；对每条逻辑变更的规则递增 `rule_version`，并在提交信息或变更记录中说明原因。
- [x] T043B 在 `/api/v2` 实现与消费者迁移完成后，将 `/api/v1` 在 OpenAPI 和文档中标记为 deprecated，并通过静态检查确认前端、测试和文档无 `/api/v1` 引用。
- [x] T043C 确认 `/api/v1` 已无消费者后，从 `docs/api/openapi.yaml`、`app/api/router.py`、`app/models/schemas.py`、测试和 web 生成客户端中删除 `/api/v1` 及其 OpenAPI 专属字段；更新架构与 API 文档，并确认运行时无 `/api/v1` 引用。`Inspector.inputs[]` 和 `outputs_artifacts` 的内部代码迁移仍按预处理优化 TODO 单独处理。
- [x] T044 在 T043C 通过后运行 `make lint`、`make test`、`make contract`、`make gen-web-api`、`make verify` 和 `make web-build`；前端目录存在测试脚本时执行 `npm test`。
- [x] T045 按 `specs/001-system-baseline/quickstart.md` 手工验证离线流程、重跑、本地/在线一致性和任务删除

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：无依赖，可立即开始。
- **基础层（阶段 2）**：依赖阶段 1；阻塞所有用户故事。
- **用户故事（阶段 3–7）**：依赖阶段 2；建议按 P1 → P2 → P3 → P4 → P5 交付。
- **收尾（阶段 8）**：依赖全部用户故事完成。

### 用户故事依赖

- **US1（P1）**：基础层完成后可开始，是 MVP。
- **US2（P2）**：依赖已完成巡检结果；可与 US1 集成但接口/报告可独立验证。
- **US3（P3）**：依赖 US1 的离线结果；在线侧可基于既有 API 测试。
- **US4（P4）**：依赖一次完成的巡检或可重建的任务现场。
- **US5（P5）**：依赖至少一个可删除任务；实现上不依赖 US3/US4 的业务逻辑变化。

### 每个用户故事内部

1. 先添加测试并确认失败。
2. 修复服务、模型、执行器或模板。
3. 运行该故事对应测试。
4. 通过后再进入下一个优先级。

### 并行机会

- 阶段 2 中 T006、T007、T010、T011 分属不同测试文件，可并行。
- 阶段 3 中仅 `[P]` 任务 T013、T015、T017 可并行；T014/T014A、T016/T016A 等同文件或依赖测试任务按顺序执行。实现任务按依赖串行。
- 阶段 4 中 T022–T024 可并行；前端检查 T027 可与后端报告修正并行。
- 阶段 5 中 T029–T030 可并行。
- 阶段 6 中 T033–T034 可并行。
- 阶段 7 中 T037–T038 可并行。

---

## 并行示例：用户故事 1

```bash
# 可同时编写不同文件的 US1 测试：
Task: "在 tests/test_baseline_pipeline.py 中验证单包离线全流程"
Task: "在 tests/test_baseline_extraction.py 中验证分类解压与容错"
Task: "在 tests/test_baseline_report.py 中验证报告可审查内容"
```

---

## 实现策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1 设置。
2. 完成阶段 2 基础契约与安全门禁。
3. 完成阶段 3 离线巡检。
4. 停止并运行 `make lint`、`make test`、`make verify`。
5. 独立验证报告与任务隔离后再继续。

### 增量交付

1. 设置 + 基础层 → 单任务目录、源文件契约与安全基线。
2. US1 → 离线巡检 MVP。
3. US2 → 可审查、可追溯结果。
4. US3 → 本地/在线语义一致。
5. US4 → 目标规则快速迭代。
6. US5 → 生命周期收口。
7. 阶段 8 → 全量验证与文档同步。

---

## 注意事项

- [P] 任务 = 不同文件，无未完成依赖。
- 每个任务或逻辑组完成后提交。
- 不改变既有字段含义；确需契约变更必须同步 `docs/api/openapi.yaml`、生成代码和测试。
- 提交巡检规则逻辑变更时升级对应 `rule_version`；本地调试不需要额外缓存开关。
- `/api/v1` 仅作为迁移期兼容入口；迁移完成后按 T043B/T043C 废弃并删除，`/api/v2` 是唯一公开 API 版本。
- 不引入规则间依赖图、artifacts、并发执行、分布式调度、PDF 导出、报告下载、在线规则编辑或自动清理。
- 待办：规则预处理文件优化完成后，评估并移除 `Inspector.inputs[]`、`outputs_artifacts` 及 OpenAPI/Schema 中对应旧字段；普通规则数据入口迁移到 `source_patterns[]`，输出迁移到 `outputs_metrics`。完成前不得基于旧字段新增普通规则数据入口。
