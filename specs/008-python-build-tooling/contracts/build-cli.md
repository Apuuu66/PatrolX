# 构建命令契约：`build.py`

本契约描述开发者构建入口，不修改 `docs/api/openapi.yaml` 或在线 HTTP API。所有命令均从仓库根目录执行。

## 调用形式

```bash
python build.py <command> [arguments]
```

- 命令名称、参数和退出语义在 macOS、Linux、Windows 保持一致。
- 后端命令优先使用 `.venv` 内解释器。
- 前端命令由入口发现 npm/npx 并透传参数。
- 未知命令或参数错误返回非零，并显示可用命令或正确用法。
- 前置条件缺失返回非零，并给出可执行下一步，例如 `python build.py install` 或 `python build.py e2e-install`。

## 命令列表

| 命令 | 用途 | 前置条件 | 成功结果 |
|---|---|---|---|
| `help` | 显示可用命令和用法 | 无 | 显示命令列表。 |
| `install` | 创建/校验 `.venv` 并精确安装后端依赖 | Python 3.11+、`requirements-lock.txt` | `.venv` 可用于后端命令。 |
| `lock` | 从依赖声明刷新精确锁 | Python 3.11+、pip | `requirements-lock.txt` 更新，diff 可审查。 |
| `verify` | 运行本地全流程巡检 | `.venv` 和后端依赖、输入数据包 | 任务、规则结果、日志和报告按现有契约生成。 |
| `verify-one --rule <rule_code>` | 只重跑目标规则 | `.venv`、后端依赖、任务输入 | 仅目标规则结果刷新，摘要与报告同步。 |
| `run` | 启动在线 API + Web 开发服务 | `.venv`、后端依赖、Node/npm | 后端与前端按现有地址启动。 |
| `contract` | 校验/导出 OpenAPI | `.venv` 和后端依赖 | OpenAPI 与实现一致或明确导出成功。 |
| `gen-web-api` | 生成前端 API 客户端 | Node/npm、OpenAPI 契约 | `web/src/api/client.ts` 按契约更新。 |
| `test` | 运行后端测试 | `.venv` 和后端依赖 | pytest 成功。 |
| `lint` | 运行后端风格检查 | `.venv` 和后端依赖 | Ruff check 和 format check 成功。 |
| `web-install` | 安装前端依赖 | Node/npm | `web/` 依赖按锁安装。 |
| `web-dev` | 启动前端开发服务 | Node/npm、前端依赖 | Vite 按现有配置启动。 |
| `web-build` | 构建前端 | Node/npm、前端依赖 | 构建产物生成。 |
| `e2e-install` | 安装端到端前置 | Node/npm | npm 依赖与 Chromium 就绪。 |
| `e2e` | 运行端到端测试 | Node/npm、前端依赖、浏览器 | Playwright 测试完成。 |

## 参数规则

- `verify-one` 必须提供 `--rule <rule_code>`；缺失时返回用法错误。
- 其余命令不得要求用户输入 Make 变量或 shell 包装参数。
- 现有环境变量（如输入目录、输出目录、日志配置）继续传递给后端工作流，不改变名称与语义。
- 前端命令的额外参数只透传给 npm/npx，不改变本项目命令名称。

## 退出码约定

| 退出码 | 含义 |
|---|---|
| `0` | 成功。 |
| `1` | 工作流、子进程或前置条件执行失败。 |
| `2` | 入口用法错误，例如未知命令或必选参数缺失。 |

具体子进程可保留其原有非零退出码；`build.py` 不得把失败转换成成功。

## 输出与错误

- 成功输出应说明已执行的工作流和关键产物位置。
- 失败时必须保留子进程 stderr/stdout，不得静默吞没。
- 缺失前置条件时输出缺少的工具、文件或参数，以及下一步命令。
- 帮助信息使用中文；命令名、文件路径和参数保持英文。

## 平台要求

- 不要求 GNU Make。
- 不要求 uv。
- 不要求 Unix shell。
- Windows 使用 `Scripts/python.exe`，macOS/Linux 使用 `bin/python`。
- Windows 优先发现 `npm.cmd`/`npx.cmd`，macOS/Linux 发现 `npm`/`npx`。
- 子进程必须以参数列表启动，不依赖 shell 解释。

## 与既有契约的关系

- OpenAPI 契约继续由 `docs/api/openapi.yaml` 和实现同步保证。
- `contract` 与 `gen-web-api` 只迁移入口，不改变产物语义。
- 巡检结果、任务摘要、执行日志和报告格式不在本契约中重定义。
