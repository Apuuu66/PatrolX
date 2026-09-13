# 实现计划：规则私有预处理与轻量缓存

**分支**：`004-rule-prepare-cache` | **日期**：2026-09-13 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/004-rule-prepare-cache/spec.md` 的功能规格

## 摘要

在现有离线巡检流程中增加隐藏的 `PREPARE` 阶段。执行顺序固定为 `EXTRACT → PREPARE → INSPECT`。每条普通巡检规则可以声明只属于自身的预处理单元，并把中间数据写入任务内、owner 规则私有的 `prepared` 目录。预处理不引入跨规则公共 artifact，不建立普通规则依赖图。

缓存刷新使用当前规则代码文件内容 SHA-256：marker 不存在或不一致时重建，一致时复用。不校验 prepared 输出完整性，不提供刷新命令或开关。第一版实现框架与缓存语义，并把 `log.app_service`、`kpi.threshold` 迁移为样例。

## 技术上下文

**语言/版本**：Python 3.11+

**主要依赖**：FastAPI、Pydantic v2、pytest、Ruff；本特性不新增运行时依赖

**存储**：SQLite + 文件存储；prepared 数据只使用任务目录下的文件

**测试**：pytest；涉及全流程时使用本地样例包验证

**目标平台**：本地 CLI / PyCharm 单进程运行；在线模式共用同一任务执行服务

**性能目标**：同任务重复运行目标规则时，已迁移规则不再重复解析原始大文件

**约束条件**：离线、单节点、轻量默认；规则私有隔离；失败不扩散；不修改原始上传包；不迁移既有解压目录

**规模/范围**：新增 prepare 框架、轻量缓存、三阶段编排、两条样例规则迁移和配套测试

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 处理 |
| --- | --- | --- |
| 离线优先、不连接被检系统 | 通过 | prepare 只读取任务解压结果 |
| 一个包、一个任务、一个输出目录 | 通过 | 既有数据目录已按任务隔离；本特性只新增 `output/<task_id>/prepared/` |
| 契约驱动 | 通过 | 不改变对外 API 契约，无 OpenAPI 字段变更 |
| 轻量默认 | 通过 | 第一版顺序执行，不引入外部服务或复杂调度 |
| 容错 | 通过 | 单个 prepare 失败不阻断任务，owner 规则显式 skip |
| 安全解压 | 通过 | 不新增解压行为 |
| 规则隔离与 `source_patterns` | 前置修正 | 通过 Constitution 新增规则私有 prepare 语义消除冲突；保留 `source_patterns`，不引入公共 `artifacts/inputs` |
| 巡检逻辑变化升级 `rule_version` | 通过 | 迁移两条规则时递增 `rule_version`；prepare 缓存另用代码文件 SHA-256 判断 |

**修正要求**：治理与架构文档修正是阻塞基础层任务。实现 prepare 执行器前必须同步更新 `.specify/memory/constitution.md`、`AGENTS.md`、`docs/architecture.md` 和 `docs/data-model.md`。修正内容覆盖规则私有 prepare、prepared 隔离、轻量缓存、`source_patterns` regex 契约和任务级目录模型。Constitution 版本升级为 `2.2.0`，属于 MINOR。

## 阶段 0 研究结论

详见 [research.md](research.md)。关键决定：

- 规则模型保留 `source_patterns`；prepare 继承 owner 的 source patterns 和优先级。
- `source_patterns` 是 Python regex，统一使用 `re.fullmatch()`；匹配对象是 `output/<task_id>/` 下以 `/` 归一化的 POSIX 相对路径，不使用 glob。
- 解压数据目录保持现状：`output/<task_id>/logs/`、`kpi/` 等分类目录；样例 pattern 使用 `^logs/...`、`^kpi/...`。
- prepare 是隐藏基础设施单元，不注册为普通巡检规则，不写规则结果 JSON。
- 第一版顺序执行 prepare；prepare 之间保持无依赖，后续可引入 bounded concurrency。
- 缓存 marker 使用当前规则代码文件内容 SHA-256；不检查输出文件完整性。
- `log.app_service` 与 `kpi.threshold` 作为首批迁移样例。
- 本特性不迁移既有任务级运行时目录；解压数据、规则结果和报告路径保持现状，只新增 `output/<task_id>/prepared/`，不新增 `system_id` 目录。

## 阶段 1 设计

### 1. 数据与模型

详见 [data-model.md](data-model.md)。

- `Inspector` 增加内部 `source_patterns` 和可选 `prepare`。
- `source_patterns` 匹配 helper 统一执行 `re.fullmatch(pattern, normalized_relative_path)`；路径分隔符归一为 `/`，并拒绝任务目录逃逸。
- `PrepareSpec` 包含 `code`、`owner_code`、`run`，不声明 outputs。
- prepared 目录为 `output/<task_id>/prepared/<owner_code>/`。
- 缓存 marker 为 `output/<task_id>/prepared/<owner_code>/.prepare.sha256`。
- 对外 `RuleResult`、任务摘要和报告结构不变；prepare 不写入规则结果。

### 2. 执行编排

- `EXTRACT`：执行全部 `pkg.extract.*` 隐藏规则并等待终态。
- 主包 `pkg.extract.main` 失败时任务失败，不进入 prepare/inspect。
- `PREPARE`：按 `owner priority → owner code → prepare code` 执行。
- `INSPECT`：普通规则按 `priority → code` 执行。
- prepare 命中缓存时不执行规则函数，只记录结构化日志。
- prepare 失败或无可用输入时，owner inspect 被框架直接置为 `skip`，不执行 owner `run`。
- 单规则重跑只执行目标 owner 的 prepare/缓存检查和目标 inspect；extract 依赖按现有机制确保就绪。

### 3. 首批规则

- `kpi.threshold`：
  - source patterns 匹配 KPI 目录下的 CSV/TXT。
  - prepare 生成规则私有 KPI 值数据。
  - inspect 读取私有数据，不再遍历原始 KPI 文件。
- `log.app_service`：
  - source patterns 匹配日志目录下的 `.log` / `.log.gz`。
  - prepare 只归一化并筛选 AppService 相关记录。
  - inspect 读取私有记录数据，不再依赖 `log.filter` 公共产物。
- 其他日志规则继续按现状执行，后续版本逐步迁移。

### 4. 兼容与边界

- 目录边界是基础层任务：既有解压分类目录、source patterns、解压清单和测试路径保持兼容；新增 prepared 路径只允许位于 `output/<task_id>/prepared/<owner_code>/`。
- 现有 `inputs` / `outputs_artifacts` 继续兼容当前 extract、日志过滤和未迁移规则。
- 本特性不新增公共 artifact key。
- prepared 数据不进入 `ArtifactStore` manifest。
- 单独删除 prepared 中的业务输出文件但 marker 仍在时，不自动重建；删除整个 owner prepared 目录时重建。
- 主包解压失败必须导致任务失败；category 子包失败只影响对应 prepare/inspect。

### 5. 测试设计

新增或扩展测试覆盖：

- 三阶段顺序与固定排序。
- prepare 继承 owner priority。
- 缓存命中、代码变化重建、删除 prepared 目录重建。
- 单规则重跑只执行目标 prepare + inspect。
- prepare 失败时 owner inspect `skip`，其他规则继续。
- 无匹配输入时显式 `skip`。
- CLI/API 全流程结果一致性。
- 两条样例规则的基本业务结果不回退。

### 6. 交付验证

```bash
make lint
make test
make verify
```

本特性不修改 OpenAPI；无需执行 `make gen-web-api`。若后续把 prepare 信息暴露到 API，则必须先更新 `docs/api/openapi.yaml`。

## 项目结构

### 文档（本功能）

```text
specs/004-rule-prepare-cache/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── prepare-runtime.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── inspectors/
│   ├── base.py                    # Inspector / source_patterns / PrepareSpec
│   ├── registry.py                # prepare 注册与只读查询
│   ├── log/
│   │   ├── app_service.py         # 首批日志 prepare + inspect
│   │   └── common.py              # 日志共享纯工具，不构成规则依赖
│   └── kpi/
│       └── threshold.py           # 首批 KPI prepare + inspect
├── services/
│   ├── executor.py                # 三阶段编排、prepare 执行、缓存、失败隔离
│   ├── artifacts.py               # 保留现有公共 artifact 机制，不承载 prepared
│   └── tasks.py                   # 单规则重跑与任务状态衔接
└── cli.py                         # 本地运行、单规则入口和 prepared 根目录注入

tests/
├── test_prepare_cache.py
├── test_prepare_pipeline.py
└── test_executor.py

docs/
├── architecture.md
.specify/
└── memory/
    └── constitution.md
AGENTS.md
```

**结构决策**：沿用现有分层 `api → services → inspectors/models`。prepare 逻辑属于规则层，调度与缓存属于服务层。

## 复杂度跟踪

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| Constitution 当前缺少 prepare 语义 | 规则私有预处理可减少大文件重复解析，且不引入跨规则依赖 | 完全不新增 prepare 会继续重复解析大文件；通过 MINOR 修正 Constitution 后保留 `source_patterns` |
| 规格早期误判为需要迁移 `system_id` 目录 | 当前实现已经是任务级目录，额外 `data/` 迁移会扩大范围 | 不做目录迁移；C2 通过移除过期假设、固化任务级目录和治理文档同步解决 |
