# AGENTS.md — PatrolX Agent 开发指南

## 项目速览

PatrolX 是离线巡检系统：

- 不连接被检系统、不做在线采集。
- 输入为用户上传或放入 `uploads/` 的 `zip` / `tar.gz` 数据包。
- 压缩包名称唯一并派生 `task_id`；一个数据包 = 一个任务 = 一个输出目录。
- 省份、运营商、产品形态和版本是任务元数据；不使用 `system_id` 目录层。
- 输出任务 → 规则 → 发现契约化结果。
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
- MUST 保持一个包、一个任务、一个输出目录的隔离模型。
- MUST 同步更新 `docs/api/openapi.yaml`，再修改或扩展接口实现。
- MUST NOT 手写与 OpenAPI 不一致的前端 API 调用。
- MUST NOT 破坏既有契约字段含义；破坏性 API 变更必须进入新版本。
- MUST NOT 让规则导入、实例化或调用其他规则；普通规则只声明并匹配自己的 `source_patterns`。
- MUST NOT 在核心调度器中硬编码业务规则。
- MUST NOT 让单文件解析失败静默中断整个任务。
- MUST NOT 修改原始上传包内容。
- MUST 对解压做路径穿越、链接和资源预算防护。
- MUST 在无匹配文件、格式不适用或解析失败时返回 `skip` + `skip_reason`。
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
output/<task_id>/        # 解压数据、规则结果、日志、报告
deploy/                  # Docker 与配置
docs/                    # 架构、契约、样例和路线图
tests/                   # 单元测试、契约测试和 fixtures
```

更详细结构和职责见 [`docs/architecture.md`](docs/architecture.md)。

## 本地运行与调试

```bash
make install        # 安装后端依赖
make verify         # 本地全流程，等价于 python main.py
make verify-one RULE=<rule_code>  # 单规则重跑
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

`make verify-one` 只执行目标规则：先保证任务解压完成，再按该规则的 `source_patterns` 匹配文件，最后只重写该规则 JSON、更新任务摘要和 HTML 报告；随后刷新前端即可查看最新结果。

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
- 声明 `source_patterns[]` 和输出指标契约；正则匹配 `output/<task_id>/` 下的相对路径。
- 不直接依赖其他规则实现。
- 无匹配文件时返回 `skip`，不得静默通过。
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

- 解压是隐藏的 `pkg.extract.*` 内部前置规则，必须安全、幂等且只解压一次。
- P1 基础检查。
- P2 综合分析。
- 不建立规则间依赖图；每条普通规则只按自己的 `source_patterns` 读取匹配文件。
- 单规则重跑只执行目标规则，不补跑其他普通规则。

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
- `source_patterns` 匹配与单规则重跑。
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

### 主工作区与 Worktree

主工作区是默认仓库目录，`main` 是分支；两者不是同一概念。主工作区通常停留在 `main`，用于讨论、分析、规格、计划、任务清单和纯文档维护。

主工作区允许写入：

- `specs/`
- `AGENTS.md`
- `README.md`
- `.specify/`
- `.agents/`
- `docs/` 中除 `docs/api/openapi.yaml` 外的叙述文档

主工作区禁止写入：

- `app/`
- `web/`
- `deploy/`
- `tests/`
- `docs/api/openapi.yaml`
- `pyproject.toml`、`Makefile`、`package.json` 等依赖和构建配置

worktree 的隔离单位是任务或功能分支，不是会话。每个分支最多对应一个 worktree；新会话必须先查找并复用已有 worktree。实现类变更无论大小都必须在 worktree 内进行。单条规则调试只读取或只运行时可在主工作区进行，修改代码、测试、配置或契约时必须进入 worktree。

worktree 根目录固定为仓库父目录下的 `PatrolX-wt/`：

```text
<repo-parent>/PatrolX-wt/<branch-name-with-slash-replaced-by-hyphen>
```

在本机当前仓库中就是：

```text
/Users/yigui/code/PatrolX-wt/
```

例如 `feature/003-report-export` 对应：

```text
/Users/yigui/code/PatrolX-wt/feature-003-report-export
```

不得把 worktree 放在仓库内部、`.worktrees/`、`worktrees/` 或临时目录中。已有 worktree 通过 `git worktree list` 查找并复用。

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
specify → review → plan → review → tasks → review → implement
```

产物放在对应 feature 的 `spec.md`、`plan.md`、`tasks.md` 中。

### Speckit 功能流程

1. 主工作区确认 `main` 干净并更新到最新基线。
2. 运行 specify 生成 feature 编号和短名称后，立即创建并切换功能分支：

   ```bash
   git switch -c feature/NNN-short-name
   ```

3. 在主工作区完成规格、计划和任务清单；每个 review 通过后提交到功能分支。
4. 规格文档全部提交后，主工作区切回 `main` 释放功能分支：

   ```bash
   git switch main
   ```

5. 将分支名中的 `/` 替换为 `-`，创建 worktree：

   ```bash
   git worktree add ../PatrolX-wt/feature-NNN-short-name feature/NNN-short-name
   ```

6. 进入 worktree 后初始化并验证基线：

   ```bash
   make install
   make web-install
   make lint
   make test
   ```

7. 在 worktree 内按任务实现，每完成一个任务同步更新 `tasks.md` 复选框并提交。
8. 验证通过后合入 `main`，在 `main` 上再次验证，最后清理 worktree 和分支。

### 小改动

文档调整、流程调整和其他纯文档修改可以直接在主工作区进行，仍必须检查一致性和链接。

涉及实现的小修复、规则修复、测试补齐、配置调整和契约调整必须创建或复用 worktree。若不需要完整 Speckit，仍必须：

1. 明确改动边界。
2. 使用测试验证。
3. 执行 `make lint` / `make test`。
4. 遵守 Constitution。

### 实现阶段技能

在 worktree 内按以下方式使用 Superpowers：

1. `superpowers:using-git-worktrees` — 确认或创建隔离 worktree，先于任何代码修改。
2. `superpowers:test-driven-development` — 有行为变更的任务先写失败测试，再实现并使其通过；纯文档和纯生成产物按自身验证方式执行。
3. `superpowers:systematic-debugging` — 遇到 bug、测试失败或意外行为时，先分析根因再修复。
4. `superpowers:verification-before-completion` — 声明任务完成前必须运行验证命令并确认输出，禁止凭感觉说“完成”。

Spec/plan 阶段不重复叠加实现计划；实现阶段不重走 Speckit 规划。

### 契约变更顺序

涉及 API 时必须在 worktree 内按以下顺序处理：

1. 修改 `docs/api/openapi.yaml`。
2. 执行 `make contract`。
3. 执行 `make gen-web-api`。
4. 增加或更新契约测试。
5. 更新 Pydantic Schema、API 实现、前端页面和测试。
6. 运行完整质量门禁。

禁止手写与 OpenAPI 不一致的前端 API 调用。

### 质量门禁

所有实现变更至少执行：

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

涉及前端时执行：

```bash
make web-build
```

### 合入与清理

合入前如果 `main` 已前移，必须先在 worktree 内将 `main` 合入功能分支，解决冲突并重新跑质量门禁。

主工作区合入：

```bash
git switch main
git merge --no-ff feature/NNN-short-name
```

合入后至少再次执行：

```bash
make lint
make test
```

并按变更类型追加契约、全流程或前端验证。全部通过后清理：

```bash
git worktree remove ../PatrolX-wt/feature-NNN-short-name
git branch -d feature/NNN-short-name
```

如果合并冲突或合入后验证失败，保留 worktree 和分支，回到 worktree 修复并重新验证；主工作区不得直接修改实现代码。

### 多窗口协作

- 一个功能一个分支，一个分支最多一个 worktree。
- 主工作区只做规格、计划、任务清单和纯文档维护。
- 实现代码、契约、测试、配置和生成客户端只在 worktree 内修改。
- 规格文档全部提交后才创建实现 worktree。
- 继续已有功能时复用已有 worktree，不按会话重复创建。
- 避免多个 Agent 同时修改同一文件。
