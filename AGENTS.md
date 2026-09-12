# AGENTS.md — PatrolX Agent 开发指南

## 项目速览

PatrolX 是离线巡检系统：

- 不连接被检系统、不做在线采集。
- 输入为用户上传或放入 `uploads/` 的 `zip` / `tar.gz` 数据包。
- 一个数据包 = 一个任务 = 一个系统。
- 输出任务 → 系统 → 规则 → 发现四层契约化结果。
- 本地模式与在线模式共用巡检器、规则库、执行契约和展示结构。

长期设计约束见 [`.specify/memory/constitution.md`](.specify/memory/constitution.md)。

## 权威文档索引

| 主题 | 文档 |
| --- | --- |
| 项目宪法与不可妥协原则 | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) |
| 架构、数据流、规则编排 | [`docs/architecture.md`](docs/architecture.md) |
| 契约数据模型 | [`docs/data-model.md`](docs/data-model.md) |
| API 契约 | [`docs/api/openapi.yaml`](docs/api/openapi.yaml) |
| 真实样例包结构 | [`docs/example/real-package-structure.md`](docs/example/real-package-structure.md) |
| 分类规则配置 | [`deploy/config/classify_rules.yaml`](deploy/config/classify_rules.yaml) |
| 路线图 | [`docs/roadmap.md`](docs/roadmap.md) |
| 系统基线规格 | [`specs/001-system-baseline/spec.md`](specs/001-system-baseline/spec.md) |
| 前端工程 | [`web/`](web/) |

接口结构、字段、错误码和 Schema 以 OpenAPI 文件为准；本文档不复制完整接口清单。

## 工程红线

Agent 修改代码前必须遵守：

- MUST NOT 引入被检系统连接或在线采集能力。
- MUST 保持一个包、一个任务、一个系统的隔离模型。
- MUST 同步更新 `docs/api/openapi.yaml`，再修改或扩展接口实现。
- MUST NOT 手写与 OpenAPI 不一致的前端 API 调用。
- MUST NOT 破坏既有契约字段含义；破坏性 API 变更必须进入新版本。
- MUST NOT 让规则直接依赖其他规则实现；规则只通过 `inputs[]` 和 artifacts 交互。
- MUST NOT 在核心调度器中硬编码业务规则。
- MUST NOT 让单文件解析失败静默中断整个任务。
- MUST NOT 修改原始上传包内容。
- MUST 对解压做路径穿越、链接和资源预算防护。
- MUST 在无数据、依赖缺失或格式不适用时返回 `skip` + `skip_reason`。
- MUST 在巡检逻辑变化时升级 `rule_version`。
- MUST 保持 UTC 存储；时间字段使用 `*_at` 命名。

## 代码结构

```text
app/
├── main.py              # 本地入口，同时可被 uvicorn 导入
├── cli.py               # 本地 CLI / 单规则入口
├── api/                 # FastAPI 路由层
├── core/                # 配置、注册表、安全解压、分类
├── models/              # Pydantic 契约模型与持久化模型
├── services/            # 任务执行、结果组织、报告等业务服务
├── inspectors/          # 巡检规则
└── reports/             # 报告模板和渲染

web/                     # React + TypeScript + Vite 前端
uploads/                 # 原始包输入现场
output/                  # 解压数据、artifacts、规则结果、日志、报告
deploy/                  # Docker 与配置
docs/                    # 架构、契约、样例和路线图
tests/                   # 单元测试、契约测试和 fixtures
```

更详细结构和职责见 [`docs/architecture.md`](docs/architecture.md)。

## 本地运行与调试

```bash
make install        # 安装后端依赖
make verify         # 本地全流程，等价于 python main.py
make verify-one RULE=<rule_code> [SYSTEM=<system_id>]  # 单规则重跑
make run            # 当前通过 run_online.py 启动在线 API + Web
make contract       # 导出/校验 OpenAPI
make gen-web-api    # 生成前端 API 客户端
make test           # pytest
make lint           # ruff check + format check
```

前端开发：

```bash
cd web && npm run dev
```

真实样例包结构见 [`docs/example/real-package-structure.md`](docs/example/real-package-structure.md)。

## 后端约定

- Python 3.11+。
- FastAPI + Pydantic v2。
- 使用 Ruff 做 lint 和格式化。
- Python 代码使用全量类型注解，遵循 PEP 8。
- 注释、提交信息、文档使用中文；标识符和接口字段使用英文。
- 分层为 `api → services → inspectors/models`，禁止跨层直调。
- 业务错误使用统一异常类型和错误码。
- 日志使用 structlog；关键操作记录任务、规则和结果上下文。
- 结构化数据优先使用 pandas/pyarrow；引入新依赖必须有明确收益。

## 巡检规则约定

新规则必须：

- 继承并注册到 `Inspector` 机制。
- 声明完整元数据：`code`、`name`、`category`、`severity`、`priority`、`rule_version`、
  `description`、`recommendation`。
- 声明 `inputs[]` 和输出契约。
- 不直接依赖其他规则实现。
- 无数据时返回 `skip`，不得静默通过。
- 单个解析失败不影响任务。
- 提供单元测试和样例数据。
- 本地可通过 `make verify-one` 或规则文件内 `__main__` 入口调试。

规则状态：

| 状态 | 含义 |
| --- | --- |
| `pass` | 通过 |
| `warn` | 告警 |
| `fail` | 失败 |
| `error` | 执行异常 |
| `skip` | 跳过，必须说明原因 |

执行编排：

- P0 数据准备。
- P1 基础检查。
- P2 综合分析。
- 依赖由 `inputs[]` 消费的 artifact key 自动推导。
- 依赖必须指向更高优先级；`pkg.extract.*` 是隐藏基础设施例外。
- Artifact 记录生产者 `rule_version`；版本不一致视为过期。

## API 契约约定

- `docs/api/openapi.yaml` 是唯一接口契约源。
- 接口路径使用 `/api/v1`。
- 新增或修改接口必须同步 OpenAPI、Pydantic Schema、测试和前端生成客户端。
- 资源接口直接返回资源 JSON。
- 创建/重跑类接口返回 `202 + Location`。
- 错误统一返回 `{code, message, detail}`。
- 列表使用 `page` / `page_size` 并返回总数。
- 破坏性变更必须升级版本前缀，不得改变 `/api/v1` 既有字段含义。

## 前端约定

- React + TypeScript + Vite + Ant Design + ECharts。
- API 客户端由 OpenAPI 生成，禁止手写不一致调用。
- 桌面优先，不做移动端适配。
- 状态色统一：pass 绿、warn 黄、fail 红、error 灰、skip 蓝。
- 简约克制：卡片化、留白充足、无冗余动效。
- 单规则重跑后只刷新该规则；任务执行中可轮询摘要。

## 测试与交付门槛

合入前至少执行：

```bash
make lint
make test
```

涉及本地全流程、解压、执行器或报告时执行：

```bash
make verify
```

涉及契约时执行：

```bash
make contract
make gen-web-api
```

关键场景必须有测试：

- 新巡检规则。
- artifact 依赖和重跑。
- 安全解压。
- OpenAPI / Pydantic 契约一致性。
- CLI 与 API 双模式结果一致性。
- 前端构建或关键交互。

## Git 约定

分支命名：

- `feature/*`
- `fix/*`
- `chore/*`
- `docs/*`

提交信息：

```text
<type>(<scope>): <subject>
```

示例：

```text
feat(kpi): 增加阈值巡检器
fix(executor): 修复单规则重跑依赖
docs(architecture): 拆分 AGENTS.md
```

提交粒度保持单一主题。合入前必须通过 lint/test；文档变更至少检查链接和一致性。

## Agent 工作流

项目最高约束是 Constitution，不是某个 Agent 或工具流程。

### 使用 Spec Kit 的场景

以下工作必须走 Speckit：

- 新增大功能。
- 修改 OpenAPI 契约。
- 修改巡检数据模型。
- 修改规则执行器、任务模型或存储模型。
- 设计复杂前端交互。
- 引入新的运行模式或部署形态。

流程：

```text
specify → review → plan → review → tasks → implement
```

产物放在对应 feature 的 `spec.md`、`plan.md`、`tasks.md` 中。

### 小改动

小改动、文档调整、单条规则调试、测试补齐可以不走完整 Spec Kit，但仍必须：

1. 明确改动边界。
2. 使用测试验证。
3. 执行 `make lint` / `make test`。
4. 遵守 Constitution。

### 实现阶段

Speckit 大功能进入实现后，主工作区切回 `main` 释放功能分支，然后在 worktree 内按以下顺序调用 Superpowers 技能：

1. `superpowers:using-git-worktrees` — 创建隔离 worktree（第一步，先于任何代码修改）。
2. `superpowers:test-driven-development` — 代码任务先写测试、确认失败、再实现、再通过（红绿重构循环）。非代码任务（契约更新、客户端生成、配置修改）直接执行并验证。
3. `superpowers:systematic-debugging` — 遇到 bug 或测试失败时使用，先分析根因再修复。
4. `superpowers:verification-before-completion` — 声明任务完成前必须运行验证命令并确认输出，禁止凭感觉说"完成"。

Spec/plan 阶段不重复叠加实现计划；实现阶段不重走 Speckit 规划。

小改动（不涉及实现代码变更）可以直接在主工作区进行，无需 worktree。

### 多窗口协作

- 实现阶段必须使用 git worktree 创建隔离目录，在 worktree 内完成编码、测试和验证。
- 主工作区仅用于规格规划（specify/plan/tasks），规格文档必须全部提交后才创建 worktree。
- 主工作区不得修改 `app/`、`web/`、`deploy/`、`tests/` 等实现代码。
- 避免多个 Agent 同时修改同一文件。
- worktree 内验证通过后将功能分支合入 `main` 并删除 worktree；合入前必须跑通质量门槛，合入失败应回滚并修复后重试。
