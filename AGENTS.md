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
| 设计机制参考 | [`docs/design/mechanisms.md`](docs/design/mechanisms.md) |
| UI 设计规范 | [`docs/design/DESIGN.md`](docs/design/DESIGN.md) |
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
- MUST NOT 把 prepare作为普通规则展示，或让一条规则消费另一条规则的 prepared 数据。
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
output/<task_id>/        # 解压数据、规则结果、prepared 数据、日志、报告
deploy/                  # Docker 与配置
docs/                    # 架构、契约、样例和路线图
tests/                   # 单元测试、契约测试和 fixtures
```

更详细结构和职责见 [`docs/architecture.md`](docs/architecture.md)。

## 本地运行与调试

```bash
python build.py install             # 创建 .venv 并精确安装依赖
python build.py verify              # 本地全流程
python build.py verify-one --rule <rule_code>  # 单规则重跑
python build.py run                 # 通过 run_online.py 启动在线 API + Web
python build.py contract            # 导出/校验 OpenAPI
python build.py gen-web-api         # 生成前端 API 客户端
python build.py test                # pytest
python build.py lint                # ruff check + format check
```

前端开发：

```bash
cd web && npm run dev
```

`python build.py verify-one --rule <rule_code>` 只执行目标规则：先保证任务解压完成，再执行或复用目标规则私有 prepare，最后按该规则的 `source_patterns` 匹配文件执行目标规则；随后只重写该规则 JSON、更新任务摘要和 HTML 报告，刷新前端即可查看最新结果。

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
- 声明 `source_patterns[]` 和输出指标契约；使用 Python regex 的 `re.fullmatch()` 匹配 `output/<task_id>/` 下以 `/` 归一化的相对路径。
- 可选声明至多一个私有 prepare；prepare 继承 owner 的 `source_patterns` 和 priority，只把数据写入 `output/<task_id>/prepared/<owner_code>/`。
- 不直接依赖其他规则实现。
- 无匹配文件时返回 `skip`，不得静默通过。
- 单个解析失败不影响任务。
- 提供单元测试和样例数据。
- 本地可通过 `python build.py verify-one --rule <rule_code>` 或规则文件内 `__main__` 入口调试。

规则状态：

| 状态 | 含义 |
| --- | --- |
| `pass` | 通过 |
| `warn` | 告警 |
| `fail` | 失败 |
| `error` | 执行异常 |
| `skip` | 跳过，必须说明原因 |

执行编排：

- 固定顺序为 `EXTRACT → PREPARE → INSPECT`；主包解压失败时任务失败。
- 解压是隐藏的 `pkg.extract.*` 内部前置规则，必须安全、幂等且只解压一次。
- prepare 是隐藏的规则私有基础设施单元，按 owner priority 和规则代码排序，不进入普通规则结果。
- P1 基础检查。
- P2 综合分析。
- 不建立规则间依赖图；每条普通规则只按自己的 `source_patterns` 读取匹配文件或自己的 prepared 数据。
- 单规则重跑只执行目标规则私有 prepare/缓存检查和目标规则，不补跑其他普通规则。
- prepare 缓存以当前 owner 规则 Python 文件内容 SHA-256 做轻量校验；无手动刷新命令或全局开关。

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
python build.py lint
python build.py test
```

涉及本地全流程、解压、执行器或报告时执行：

```bash
python build.py verify
```

合入验证只跑一次：fast-forward 合入且合入后代码树与验证时完全一致时，不需要在合入后重跑全量测试；仅在非 fast-forward（有 merge/rebase 产生新树）时才需重跑。

涉及契约时执行：

```bash
python build.py contract
python build.py gen-web-api
```

新功能必须有自动化测试和展示效果用例：

- 自动化测试覆盖核心用户路径、关键契约和主要失败边界。
- 展示效果用例提供可重复运行的代表性样例数据或 fixture，并验证结果在界面、报告或 API 响应中真实可见。
- 前端新功能必须包含覆盖完整入口到关键结果的 E2E。
- 完成定义不得停留在“代码已实现”或“局部函数通过”；基础路径必须按真实用户操作可用，缺少任一验证证据不得合入。

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

推送约定：

- Agent 收到用户“推送”指令时，先检查工作区变更；只暂存本次会话修改或创建的文件，并按变更主题拆分成一个或多个常规提交。不得使用 `git add -A`，不得提交无关或无法确认归属的变更。
- 自动提交前必须执行合入门槛检查；提交全部完成后，默认将当前实现分支 fast-forward 合入 `main`，再推送 `origin/main`。
- 若出现非 fast-forward、合并冲突或验证失败，必须先报告并等待用户确认，不得强行推送。
- 用户明确指定其他目标分支时，按用户指定的目标执行。

## Agent 工作流

项目最高约束是 Constitution。

### 第一原则

- Speckit 的所有规划与讨论（`specify`、`clarify`、`plan`、`tasks`、`analyze` 及对应 review）都在检出 `main` 的主工作区进行；此阶段禁止创建实现分支或 worktree。
- tasks 生成后的 `analyze` 和 review 通过后，先把全部 Speckit 产物提交到 `main`，再从 `main` 创建实现分支和实现 worktree。
- 只有 Speckit 流程最终创建实现 worktree；小改动不创建 worktree。
- 实现、测试、调试和提交只能在实现分支对应的 worktree 内完成；主工作区不承载 Speckit 实现。
- spec 元数据中的“功能分支”只是实现目标名称，不是提前建分支的授权。
- 若主工作区未检出 `main`，或存在会影响切换的其他任务现场，必须报告并等待用户处理，不得擅自切分支。

### 变更分类

- Speckit：新增大功能、修改 OpenAPI 契约、修改数据模型、修改规则执行器/任务/存储模型、复杂前端交互、新增运行模式或部署形态。
- 小改动：小修复、文档调整、单规则调试、测试补齐；可不走 Speckit，且不创建 worktree。

### Speckit

```text
specify → clarify → review → plan → review → tasks → analyze → review → implement
```

`clarify` 在 `spec` review 前消除需求歧义，并将结论回写 `spec.md`。`analyze` 在任务生成后、实现前只读校验 `spec.md`、`plan.md` 和 `tasks.md` 的一致性；发现问题必须先修正对应产物并重新 review。

`spec.md`、`plan.md`、`tasks.md` 是唯一规划与任务来源。进入实现前必须提交这些产物；实现阶段可更新 `tasks.md` 复选框。修改 `spec.md` / `plan.md` 的需求、范围或方案语义时，必须回到 Speckit review，确认后更新并提交。

实现使用 Superpowers 执行：TDD、systematic-debugging、verification-before-completion。不得重复规划或维护第二份任务清单。

### 小改动

明确改动边界，使用测试验证，按项目质量门禁执行验证，并遵守 Constitution。

### 实现前置检查

每个 Speckit 实现回合在修改实现文件前必须执行：

```bash
git worktree list
git branch --show-current
```

Agent 必须确认：

1. 当前目录是对应实现分支的 worktree。
2. 当前分支是该 worktree 的检出分支。
3. Speckit 产物已在 `main` 提交。
4. 已有对应 worktree 时必须复用，不得重复创建。

任一条件不满足时，只允许执行只读检查或按第一原则创建/复用 worktree；不得修改源代码、测试或契约。用户要求继续当前分支不构成豁免，只有用户明确声明本次豁免时才可例外。回合结束报告必须包含前置检查结果。

目录固定为 `<repo-root>/.worktrees/<分支名，/ 替换为 ->`，必须保留在 `.gitignore` 中；同一分支最多一个 worktree。回合结束报告路径、分支、变更和验证结果；合入并确认后清理。
