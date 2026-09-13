# 任务：规则私有预处理与轻量缓存

**输入**：来自 `specs/004-rule-prepare-cache/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/prepare-runtime.md、quickstart.md

**测试**：本计划包含测试任务；实现前先确认对应测试失败，再补齐实现。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行，且与其他并行任务没有同一文件依赖
- **[故事]**：该任务所属的用户故事

---

## 阶段 0：设置

**目的**：建立可复用的测试上下文和失败注入工具，避免后续故事重复搭建环境

- [ ] T001 [P] 在 `tests/test_prepare_cache.py` 中创建规则注册、临时任务目录、prepared 根目录和日志收集测试 helper
- [ ] T002 [P] 在 `tests/test_prepare_pipeline.py` 中创建可注册假 extract / prepare / inspect 规则的 pipeline fixture

**检查点**：两个测试文件可被 pytest 收集，且当前新增测试明确失败或被标记为待实现。

---

## 阶段 1：治理门禁（阻塞实现）

**目的**：在修改执行器前把 prepare 语义、缓存边界、`source_patterns` 契约和任务级目录边界固化为正式约定；不迁移既有解压分类目录。

- [ ] T003 在 `.specify/memory/constitution.md` 中新增规则私有 prepare、prepared 隔离、轻量缓存约束；明确 `source_patterns` 为 Python regex 且使用 `re.fullmatch()` 匹配 `output/<task_id>/` 相对路径，版本升级为 `2.2.0`
- [ ] T004 [P] 在 `AGENTS.md` 中同步规则约定、`EXTRACT → PREPARE → INSPECT` 编排、prepared 目录、缓存自动刷新和单规则重跑语义
- [ ] T005 [P] 在 `docs/architecture.md` 中同步三阶段流程、prepared 生命周期、缓存语义、失败隔离和任务级目录边界
- [ ] T006 [P] 在 `docs/data-model.md` 中同步 `source_patterns` regex 语义、prepared 数据模型和任务级目录边界
- [ ] T007 检查治理与架构文档不得引入 `system_id` 运行时目录或公共 `artifacts/inputs` 规则输入；不得将 `data/` 定义为解压根目录目标模型，允许保留“拒绝 `data/` 方案”的说明；确认 `source_patterns` 示例为 `^logs/...`、`^kpi/...`

**检查点**：治理文档与功能规格一致；后续实现不得扩大目录迁移范围。

---

## 阶段 2：基础层

**目的**：建立 prepare 契约、注册表和任务上下文，所有用户故事都依赖这些前置能力

- [ ] T008 在 `app/inspectors/base.py` 中增加 `source_patterns: list[str]` 和 `PrepareSpec`；约束一个 owner 最多一个 prepare，prepare 只包含 `code`、`owner_code`、`run`，不声明 outputs
- [ ] T009 在 `app/inspectors/registry.py` 中实现 prepare 注册、owner 唯一性校验、prepare code 唯一性校验和按 owner 查询的只读访问
- [ ] T010 在 `app/services/executor.py` 的 `RuleContext` 中增加 `prepared_dir`，并在 `app/cli.py` 的 `_new_context` 注入 `output/<task_id>/prepared/`
- [ ] T011 在 `app/services/prepare.py` 中创建 owner prepared 目录路径、marker 路径、当前规则 Python 文件路径解析和 md5 计算的纯函数 helper
- [ ] T012 在 `app/inspectors/base.py` 或 `app/services/prepare.py` 中实现 `source_patterns` 匹配 helper：POSIX 相对路径、`re.fullmatch()`、防路径穿越

**检查点**：基础层完成；未实现编排前，现有 `make lint` 和 `make test` 仍必须通过。

---

## 阶段 3：用户故事 1 - 固定三阶段执行（优先级：P1）🎯 MVP

**目标**：执行顺序稳定为 `EXTRACT → PREPARE → INSPECT`，同阶段内按优先级和规则代码排序。

**独立测试**：注册两个假 prepare 和两个假 inspect 后运行 `Executor.run_all`，通过执行日志断言阶段屏障和排序。

### 测试

- [ ] T013 [US1] 在 `tests/test_prepare_pipeline.py` 中编写三阶段顺序、prepare 排序、inspect 排序和主包失败阻断的失败测试

### 实现

- [ ] T014 [US1] 在 `app/services/executor.py` 中实现 extract plan、prepare plan、inspect plan；prepare 排序为 `owner priority → owner code → prepare code`，inspect 排序为 `priority → code`
- [ ] T015 [US1] 在 `app/services/executor.py` 中重写 `run_all`，实现 extract 全部终态后才执行 prepare、prepare 全部完成后才执行 inspect
- [ ] T016 [US1] 在 `app/cli.py` 的 `run_task` 中处理主包解压失败：任务状态必须失败，不生成完成报告
- [ ] T017 [US1] 在 `app/cli.py` 的 `_rebuild_system` 中改为只按 inspect plan 重建规则顺序，避免隐藏 prepare 进入报告

**检查点**：三阶段测试通过；普通任务执行结果与现有行为兼容。

---

## 阶段 4：用户故事 2 - 规则私有预处理（优先级：P1）

**目标**：普通规则可拥有私有 prepare，prepared 数据按 owner 隔离，两条样例规则不再重复解析原始大文件。

**独立测试**：为 `kpi.threshold` 和 `log.app_service` 运行全流程，检查各自 prepared 目录存在，且其他规则不能读取对方 prepared 数据。

### 测试

- [ ] T018 [US2] 在 `tests/test_prepare_pipeline.py` 中编写两个 prepare 输出按 owner 隔离、owner inspect 使用私有数据的测试

### 实现

- [ ] T019 [US2] 在 `app/inspectors/kpi/threshold.py` 中保留 `^kpi/...` source patterns，声明私有 prepare，生成 owner 私有 KPI 值数据，并让 inspect 读取该数据
- [ ] T020 [P] [US2] 在 `app/inspectors/log/common.py` 中补充不依赖具体规则的日志归一化纯工具，供规则文件复用
- [ ] T021 [US2] 在 `app/inspectors/log/app_service.py` 中保留 `^logs/...` source patterns，声明私有 prepare，生成 AppService 私有记录数据，并让 inspect 读取该数据

**检查点**：两条样例规则全流程通过；既有未迁移规则继续按原逻辑执行。

---

## 阶段 5：用户故事 3 - 当前规则代码变化自动重建（优先级：P1）

**目标**：当前规则 Python 文件内容变化时自动重建 prepared，不提供刷新命令或开关。

**独立测试**：运行规则后修改该规则文件并重跑，检查 marker 变化、prepared 重建；不改代码重跑时检查缓存命中。

### 测试

- [ ] T022 [US3] 在 `tests/test_prepare_cache.py` 中编写缓存命中、代码变化重建、目录删除重建和输出文件缺失不重建的失败测试；用例不得依赖刷新命令、环境变量或全局开关触发缓存刷新

### 实现

- [ ] T023 [US3] 在 `app/services/executor.py` 中实现 marker 不存在/不一致重建、一致复用；重建前清空 owner prepared 目录，成功后写 marker
- [ ] T024 [US3] 在 `app/services/executor.py` 中输出 `prepare_cache_hit` 和 `prepare_cache_rebuild` 结构化日志，包含任务、owner 规则和 prepare 上下文

**检查点**：缓存测试通过；重复运行同一规则不重复执行 prepare 函数。

---

## 阶段 6：用户故事 4 - 单规则重跑快速完成（优先级：P2）

**目标**：重跑目标规则时只执行目标 prepare/复用和目标 inspect，不补跑其他普通规则。

**独立测试**：完成任务后修改目标规则并单规则重跑，检查只有目标规则结果、任务摘要和报告更新。

### 测试

- [ ] T025 [US4] 在 `tests/test_rerun_status.py` 中编写单规则重跑只执行目标 prepare + inspect、其他普通规则不被执行的测试

### 实现

- [ ] T026 [US4] 在 `app/services/executor.py` 的 `run_rule_with_deps` 中加入目标 owner prepare 检查；无 prepare 规则保持现有行为
- [ ] T027 [US4] 在 `app/cli.py` 和 `app/services/tasks.py` 中验证单规则重跑路径都注入同一 prepared root，并只更新目标规则 JSON、任务摘要和 HTML 报告

**检查点**：单规则重跑测试通过；在线 API 重跑和本地 CLI 行为一致。

---

## 阶段 7：用户故事 5 - 失败不扩散（优先级：P2）

**目标**：prepare 失败、无输入或主包失败时，任务行为明确且不误导用户。

**独立测试**：构造 prepare 异常、无匹配输入和 category 子包失败场景，检查显式状态、skip 原因和其他规则继续执行。

### 测试

- [ ] T028 [US5] 在 `tests/test_prepare_pipeline.py` 中编写 prepare 异常、prepare 无匹配输入、category 子包失败导致 owner skip、category 子包部分失败但仍有可用源文件时 owner 正常执行、其他规则继续执行的测试

### 实现

- [ ] T029 [US5] 在 `app/services/executor.py` 中实现 prepare `SKIP` / `FAILED` 状态跟踪；category 子包部分失败时只向 prepare 提供可用源文件，prepare 未就绪时框架直接生成 owner `skip` 结果，不调用 owner inspect 函数
- [ ] T030 [US5] 在 `app/services/executor.py` 中输出 `prepare_skip`、`prepare_error`、`inspect_skip_prepare_not_ready` 结构化日志
- [ ] T031 [US5] 在 `app/services/prepare.py` 中保证 prepare 失败不写新 marker，且不会把失败结果误判为缓存命中

**检查点**：失败隔离测试通过；主包失败、子包失败和普通 prepare 失败语义都明确。

---

## 阶段 8：收尾与横切关注点

**目的**：规则版本、契约检查和全量验证

- [ ] T032 检查 `kpi.threshold`、`log.app_service` 的 `rule_version` 已因巡检逻辑变化递增；如未递增则在对应规则文件中修正
- [ ] T033 在 `docs/api/openapi.yaml` 确认无接口变更；如发现新增公共字段或规则列表暴露 prepare，先停止实现并回溯 OpenAPI 契约
- [ ] T034 运行 `make lint && make test`，修复所有回退
- [ ] T035 运行 `make verify`，按 `specs/004-rule-prepare-cache/quickstart.md` 验证缓存命中、自动重建和失败隔离

---

## 依赖与执行顺序

### 阶段依赖

1. 阶段 0 设置可立即开始。
2. 阶段 1 治理门禁依赖阶段 0；必须在阶段 2 前完成。
3. 阶段 2 基础层依赖治理门禁。
4. 阶段 3 US1 依赖阶段 2。
5. 阶段 4–7 依赖阶段 2；其中 US3、US4、US5 还依赖 US1建立阶段编排。
6. 阶段 8 依赖阶段 3–7 全部完成。

### 用户故事依赖

- **US1（P1）**：基础层完成后开始，是阶段编排 MVP。
- **US2（P1）**：依赖 US1的 prepare 执行位置；样例规则间可并行。
- **US3（P1）**：依赖 US1；实现缓存核心。
- **US4（P2）**：依赖 US1和 US3。
- **US5（P2）**：依赖 US1和基础 prepare 执行；可与 US4并行但都会修改 executor，建议串行合入。

### 推荐执行顺序

```text
T001/T002 → T003–T007
→ T008–T012
→ US1: T013–T017
→ US2: T018–T021
→ US3: T022–T024
→ US4: T025–T027
→ US5: T028–T031
→ 收尾: T032–T035
```

### 并行机会

- `T001` 与 `T002` 可并行。
- `T004`、`T005`、`T006` 可并行，但都依赖 T003确定的语义。
- `T019`（KPI 规则）与 `T020/T021`（日志规则）可分别推进，但合入前需共享 helper 稳定。
- 避免并行修改 `app/services/executor.py` 的 US3、US4、US5任务；建议按顺序实现。

---

## 实现策略

### MVP 优先

1. 完成治理门禁和基础层。
2. 完成 US1，验证三阶段顺序。
3. 可先停止演示阶段编排；但实际业务收益需继续 US2。

### 建议功能完整增量

1. 完成 US1 + US2，获得可用规则私有预处理。
2. 完成 US3，获得开发体验核心的自动缓存刷新。
3. 完成 US4，保证单规则调试收益。
4. 完成 US5，保证失败场景可用。
5. 最后完成契约检查和全量验证。
