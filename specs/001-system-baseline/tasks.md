---
description: "系统基线功能实现任务列表"
---

# 任务：系统基线

**输入**：来自 `specs/001-system-baseline/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md 已就绪

**测试**：包含测试任务。本基线的核心是验证与加固既有实现，测试先于实现变更执行。

**组织方式**：任务按用户故事分组；共享契约与安全约束先进入基础层。

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

## 阶段 1：设置（共享基础设施）

**目的**：为基线验证准备可复用的测试工具和样例上下文

- [ ] T001 在 `tests/baseline_helpers.py` 中创建基线测试助手，封装临时 `uploads/`、`output/` 与 SQLite 环境运行本地任务
- [ ] T002 在 `tests/baseline_helpers.py` 中添加 `wait_for_task()`、`load_system()`、`load_rule()`、`strip_volatile()` 工具，统一忽略 `executed_at` 与 `duration_ms`

**检查点**：后续测试可以稳定运行样例包并读取契约结果

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：固化数据契约、规则注册、输出校验和安全解压等所有故事依赖的约束

**⚠️ 关键**：本阶段完成前不得开始任何用户故事工作

- [ ] T003 在 `app/models/schemas.py` 中添加模型校验：`status=skip` 时 `skip_reason` 必须非空；发现必须提供非空 `source_file` 与 `evidence`
- [ ] T004 在 `app/models/schemas.py` 中添加摘要校验：`SystemInspection.summary.total` 等于 `rules` 数量，且各状态计数之和等于 `total`

- [ ] T005 在 `app/services/store.py` 中固化当前文件存储分层：SQLite 只保存任务运行元数据；本基线的包输入、解压数据、artifacts、规则 JSON、报告和执行日志继续保留在磁盘。业务代码必须通过存储层读写巡检结果，不得直接绑定文件路径或 SQL，为后续结果入库保留可替换后端
- [ ] T006 [P] 在 `tests/test_baseline_storage.py` 中验证当前 `TaskRecord` 不承载巡检业务数据，规则结果、artifacts、报告和日志落在磁盘，且 API/CLI 不绕过存储层直接访问文件或数据库
- [ ] T007 [P] 在 `tests/test_baseline_schemas.py` 中覆盖 skip 原因、发现可追溯性和摘要一致性校验
- [ ] T008 在 `app/inspectors/registry.py` 中强化注册校验：规则 `code` 文件系统安全，`description` 与 `recommendation` 非空，artifact key 全局唯一且可定位生产者
- [ ] T009 在 `app/services/executor.py` 中校验 `pass`、`warn`、`fail` 结果的 metrics key/unit 与规则声明契约一致；不一致时记为 `error` 并写入结构化日志
- [ ] T010 [P] 在 `tests/test_baseline_registry.py` 中覆盖非法注册元数据、未声明 artifact、循环/非法优先级依赖和 metrics 契约不一致
- [ ] T011 [P] 在 `tests/test_baseline_archive.py` 中补充文件数、单文件大小、总量预算、链接拒绝、路径穿越和深层嵌套限制测试
- [ ] T012 在 `app/core/archive.py` 中根据 T011 修复安全解压缺口，确保超限或异常归档产生可记录的 `ArchiveError`

**检查点**：契约不变量、规则边界和解压安全约束已可作为用户故事的阻塞门禁

---

## 阶段 3：用户故事 1 - 执行离线巡检（优先级：P1）🎯 MVP

**目标**：一个受支持包在离线流程中成为唯一任务与系统上下文，安全分类解压，执行适用规则，并产出报告与执行日志

**独立测试**：将样例包放入临时输入目录并运行离线流程，验证恰好生成一个任务和一个系统，规则结果、报告、日志存在；无数据类别可见跳过

### 用户故事 1 的测试

- [ ] T013 [P] [US1] 在 `tests/test_baseline_pipeline.py` 中验证单包生成单任务、单系统、类别目录、规则 JSON、`report.html` 与 `execution.log`
- [ ] T014 [US1] 在 `tests/test_baseline_pipeline.py` 中验证同一输入目录中的多个压缩包形成独立任务，任务结果互不合并
- [ ] T015 [P] [US1] 在 `tests/test_baseline_extraction.py` 中验证主包按类落位、嵌套子包 checksum 去重、重复执行不重复解压
- [ ] T016 [US1] 在 `tests/test_baseline_extraction.py` 中验证格式错误或不可识别文件不中止任务，并在解压结果、执行日志或对应规则结果中可见
- [ ] T017 [P] [US1] 在 `tests/test_baseline_report.py` 中验证报告包含状态计数、规则摘要、发现来源/证据/建议、跳过原因和执行时间

### 用户故事 1 的实现

- [ ] T018 [US1] 在 `app/inspectors/pkg.py` 中更新解压清单与规则结果：失败子包记录 checksum、目标目录、错误信息和未解压状态，不静默跳过
- [ ] T019 [US1] 在 `app/core/classify.py` 与 `deploy/config/classify_rules.yaml` 中核对日志、KPI、话统、告警、配置、资源和 `other` 分类规则，补充缺失的真实样例映射
- [ ] T020 [US1] 在 `app/cli.py` 中统一离线运行摘要输出：任务数、系统 ID、状态统计、报告路径和执行日志路径
- [ ] T021 [US1] 在 `app/services/report.py` 与 `app/reports/templates/report.html.j2` 中修正 T017 暴露的报告内容缺口，保持 HTML 只在线预览、无下载入口

**检查点**：此时用户故事 1 应完整可用且可独立测试；`make verify` 与样例流水线测试通过

---

## 阶段 4：用户故事 2 - 审查结果（优先级：P2）

**目标**：用户可以从任务状态下钻到系统、规则和发现，并追溯来源、证据、严重程度和建议

**独立测试**：读取已完成任务的 API 和报告，验证每个展示发现都有规则、来源位置、证据和建议；每条跳过规则有原因

### 用户故事 2 的测试

- [ ] T022 [P] [US2] 在 `tests/test_baseline_review.py` 中验证任务摘要、系统、规则结果和发现的接口下钻路径，并断言发现包含非空来源与证据
- [ ] T023 [US2] 在 `tests/test_baseline_review.py` 中验证跳过规则通过系统、单规则接口和报告暴露 `skip_reason`
- [ ] T024 [US2] 在 `tests/test_baseline_report.py` 中补充报告与契约结果的对应关系：报告展示的发现/跳过状态必须来自契约 JSON

### 用户故事 2 的实现

- [ ] T025 [US2] 在 `app/api/router.py` 中保证任务、系统、单规则接口返回基线审查所需字段，且不泄漏 hidden 内部规则的成功结果
- [ ] T026 [US2] 在 `app/reports/templates/report.html.j2` 中为发现的严重程度、来源、证据、建议和跳过原因提供统一可读展示
- [ ] T027 [P] [US2] 在 `web/src/pages/TaskDetailPage.tsx`、`web/src/pages/RuleDetailPage.tsx` 和 `web/src/components/StatusBadge.tsx` 中核对下钻、状态徽标与 `skip_reason` 展示，仅修复缺失项
- [ ] T028 [US2] 运行 `make web-build` 验证审查页面和生成 API 客户端保持可构建

**检查点**：用户故事 1 和 2 均应独立可用

---

## 阶段 5：用户故事 3 - 本地/在线一致（优先级：P3）

**目标**：同一包在本地 CLI 与在线 API 中产生一致的业务结果结构和规则结果语义

**独立测试**：分别用 CLI 与 API 处理同一包，剥离执行标识和时间后比较任务统计、系统、规则、metrics、findings 与 artifacts 引用

### 用户故事 3 的测试

- [ ] T029 [P] [US3] 在 `tests/test_baseline_consistency.py` 中比较本地与在线契约结果，忽略 `executed_at`、`duration_ms` 和运行标识，但比较规则状态、metrics、findings 与 `artifacts[]`
- [ ] T030 [US3] 在 `tests/test_baseline_consistency.py` 中验证两个任务使用相同系统标识时仍保持任务目录、结果与日志隔离

### 用户故事 3 的实现

- [ ] T031 [US3] 在 `app/cli.py` 与 `app/services/tasks.py` 中消除本地/在线执行路径的业务分歧，共享 `Executor`、存储布局和报告生成入口
- [ ] T032 [US3] 在 `app/services/store.py` 中确保任务、系统、规则结果使用同一 UTC 序列化与别名规则，避免双模式字段语义漂移

**检查点**：本地与在线结果一致性测试通过，模式同构约束得到回归保护

---

## 阶段 6：用户故事 4 - 重跑目标规则（优先级：P4）

**目标**：目标规则可独立重跑；缺失或版本过期依赖先重建；有效依赖复用；无关结果保持不变

**独立测试**：完成一次巡检后重跑目标规则，验证目标结果刷新、过期 artifact 重生、有效 artifact 复用，其他规则 JSON 内容和 mtime 不被无关改写

### 用户故事 4 的测试

- [ ] T033 [P] [US4] 在 `tests/test_baseline_rerun.py` 中验证本地 CLI 与在线 API 单规则重跑后，目标规则 JSON、`task.json`/`system.json` 摘要和 `report.html` 更新，且无关规则结果不变
- [ ] T034 [US4] 在 `tests/test_baseline_rerun.py` 中修改依赖 artifact 的 `rule_version` 或删除 artifact，验证目标规则重跑前自动重建依赖
- [ ] T035 [US4] 在 `tests/test_baseline_rerun.py` 中验证有效依赖被复用且生产者不重复执行

### 用户故事 4 的实现

- [ ] T036 [US4] 在 `app/services/artifacts.py` 中保持 manifest 记录 `rule_code`、`rule_version` 与路径，并拒绝生产者不一致的 artifact 复用
- [ ] T037 [US4] 在 `app/services/executor.py` 中保证 `run_rule_with_deps()` 递归解析传递依赖、先重建缺失/过期依赖，再更新目标规则
- [ ] T038 [US4] 在 `app/cli.py` 与 `app/services/tasks.py` 中统一本地与在线单规则重跑收尾：更新受影响规则结果、系统摘要、任务统计和 HTML 报告，并通过存储层保证前端 API 刷新后可读取最新结果

**检查点**：规则开发者可以只重跑目标规则并看到无关结果保留

---

## 阶段 7：用户故事 5 - 删除任务（优先级：P5）

**目标**：显式删除任务后，SQLite 记录、原始包输入、输出现场、报告和日志均无残留

**独立测试**：创建并完成任务后调用删除接口，验证任务不可访问，且 `uploads/<task_id>/` 与 `output/<task_id>/` 不存在

### 用户故事 5 的测试

- [ ] T039 [P] [US5] 在 `tests/test_baseline_delete.py` 中验证删除 API 移除 SQLite 记录、任务契约 JSON、规则 JSON、artifacts、报告、日志和 `uploads/<task_id>/` 原始包
- [ ] T040 [US5] 在 `tests/test_baseline_delete.py` 中验证删除后再次查询任务、系统、规则、报告和日志均返回 404，重复删除返回 404

### 用户故事 5 的实现

- [ ] T041 [US5] 在 `app/services/tasks.py` 中显式清理任务级联目录，避免 `ignore_errors=True` 掩盖残留；无法完全删除时返回明确错误并记录日志
- [ ] T042 [US5] 在 `app/api/router.py` 中保持删除接口 204/404 语义与 OpenAPI 契约一致

**检查点**：所有用户故事均应独立可用

---

## 阶段 8：收尾与横切关注点

**目的**：验证完整基线，清理实现并同步文档

- [ ] T043 检查 `docs/api/openapi.yaml` 与 `app/models/schemas.py`、`app/api/router.py` 的一致性；若模型校验影响错误示例，则同步契约
- [ ] T044 [P] 在 `docs/roadmap.md` 中补充巡检结果入库与磁盘增长治理设计：文件继续作为运行现场与证据权威源，数据库优先作为查询投影；定义 `ResultStore`/`ResultRepository` 边界、`FileResultStore` 与 `DatabaseResultProjection` 职责、任务/系统/规则/发现/指标入库粒度、`task_id/system_id/rule_code/rule_version/source_file/evidence` 关键字段、任务完成后同步或异步投影、checksum/总数一致性校验和查询/归档场景。同时按数据类型定义生命周期：active 全现场、compact 清理解压数据和 artifacts、archive 将结果投影/报告索引后归档原始包、deleted 级联清理；说明磁盘水位、保留窗口、dry-run、执行中保护与单规则重跑恢复语义。本基线不实现自动清理
- [ ] T045 [P] 在 `README.md`、`docs/architecture.md` 与 `specs/001-system-baseline/quickstart.md` 中核对基线命令、目录布局和文档链接
- [ ] T046 清理新增代码中的重复逻辑，保持规则互不引用、依赖只通过 `inputs[]` 表达
- [ ] T047 运行 `make lint`、`make test`、`make contract`、`make verify` 和 `make web-build`
- [ ] T048 按 `specs/001-system-baseline/quickstart.md` 手工验证离线流程、重跑、本地/在线一致性和任务删除

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：无依赖，可立即开始。
- **基础层（阶段 2）**：依赖阶段 1；阻塞所有用户故事。
- **用户故事（阶段 3–7）**：依赖阶段 2；建议按 P1 → P2 → P3 → P4 → P5 交付。
- **收尾（阶段 8）**：依赖全部用户故事完成。

- **存储演进**：本基线保持磁盘为巡检结果权威源；`T005/T006` 保证业务代码通过存储层访问结果，后续入库时可以增加数据库 Repository 或同步投影，而不要求重写执行器和 API。

### 用户故事依赖

- **US1（P1）**：基础层完成后可开始，是 MVP。
- **US2（P2）**：依赖已完成巡检结果；可与 US1 集成但接口/报告可独立验证。
- **US3（P3）**：依赖 US1 的离线结果；在线侧可基于既有 API 测试。
- **US4（P4）**：依赖一次完成的巡检与 artifact 状态。
- **US5（P5）**：依赖至少一个可删除任务；实现上不依赖 US3/US4 的业务逻辑变化。

### 每个用户故事内部

1. 先添加测试并确认失败。
2. 修复服务、模型、执行器或模板。
3. 运行该故事对应测试。
4. 通过后再进入下一个优先级。

### 并行机会

- 阶段 2 中 T006、T007、T010、T011 分属不同测试文件，可并行。
- 阶段 3 中 T013–T017 可并行；实现任务按依赖串行。
- 阶段 4 中 T022–T024 可并行；前端检查 T027 可与后端报告修正并行。
- 阶段 5 中 T029–T030 可并行。
- 阶段 6 中 T033–T035 可并行。
- 阶段 7 中 T039–T040 可并行。

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

1. 设置 + 基础层 → 契约与安全基线。
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
- 修改巡检规则逻辑时必须升级对应 `rule_version`。
- 不引入并发执行、分布式调度、PDF 导出、报告下载、在线规则编辑或自动清理。
