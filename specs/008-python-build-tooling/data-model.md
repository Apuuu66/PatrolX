# 数据模型：统一 Python 构建工具

本功能不改变巡检任务、规则结果、报告或 API 数据契约。以下实体只描述构建入口的开发者契约与本地状态。

## 统一构建操作

开发者通过 `python build.py` 调用的最小工作流单元。

| 字段/属性 | 说明 |
|---|---|
| `name` | 子命令名称，例如 `install`、`verify`、`verify-one`。 |
| `purpose` | 面向开发者的用途描述。 |
| `arguments` | 可选参数或必选参数；同一参数在所有平台语义一致。 |
| `prerequisites` | 执行前需要满足的后端环境、前端依赖、浏览器或契约状态。 |
| `target` | 被调用的现有后端/前端工作流。 |
| `expected_outputs` | 命令成功后的主要产物或状态。 |
| `failure_behavior` | 非零退出、保留错误输出并给出可操作提示。 |

### 命令状态

- `known`：已注册的子命令。
- `unknown`：未注册子命令，必须提示帮助。
- `ready`：前置条件满足，可执行。
- `blocked`：缺少 Python 版本、`.venv`、Node/npm、浏览器或其他前提。
- `succeeded`：子进程零退出。
- `failed`：子进程或环境检查非零退出。

## 后端构建环境

本地虚拟环境状态，不进入任务输出或版本库。

| 属性 | 说明 |
|---|---|
| `path` | 仓库根目录下的 `.venv`。 |
| `python_version` | 必须满足项目声明的 Python 3.11+。 |
| `interpreter_path` | 平台相关：`bin/python` 或 `Scripts/python.exe`。 |
| `pip_available` | 可用于按锁文件安装依赖。 |
| `lock_installed` | 环境依赖与 `requirements-lock.txt` 匹配。 |
| `health` | `missing`、`ready`、`stale` 或 `incompatible`。 |
| `state_marker` | 成功执行标准 `install` 后写入 `.venv/.patrolx-build-state.json`，记录 Python 主次版本和当前锁文件 SHA-256。 |

### 状态转换

1. `missing → ready`：执行标准 `install` 成功。
2. `ready → ready`：复用环境执行后端命令。
3. `ready → stale/incompatible`：Python 版本、关键环境标记、安装标记缺失/无效或锁内容不匹配。
4. `stale/incompatible → ready`：按提示重建并重新执行 `install`。

## 后端依赖锁

`requirements-lock.txt` 是唯一权威安装清单。

| 属性 | 说明 |
|---|---|
| `scope` | 后端运行、测试和 lint 依赖。 |
| `version_policy` | 直接依赖与传递依赖均记录精确版本。 |
| `platform_markers` | 使用环境标记表达平台差异。 |
| `source` | 从 `pyproject.toml` 的依赖声明解析刷新。 |
| `authority` | 标准安装唯一输入；不得由 uv.lock 或临时解析替代。 |
| `change_flow` | 修改 `pyproject.toml` → 执行 `build.py lock` → 审查锁 diff → 安装并测试。 |

## 前端依赖状态

前端生态继续使用其既有锁文件与工具链。

| 属性 | 说明 |
|---|---|
| `path` | `web/`。 |
| `lock_file` | `web/package-lock.json`。 |
| `tool` | npm；必要时 npx 调用本地开发工具。 |
| `browser_tool` | Playwright。 |
| `health` | `missing`、`ready` 或 `blocked`。 |

## 构建前提

| 前提 | 适用命令 | 缺失行为 |
|---|---|---|
| Python 3.11+ | 所有后端相关命令 | 非零退出并提示安装/选择正确解释器。 |
| `.venv` | `verify`、`run`、`verify-one`、`contract`、`test`、`lint` | 提示执行 `python build.py install`。 |
| `requirements-lock.txt` | `install`、`lock` 相关流程 | 非零退出并说明锁文件缺失。 |
| Node/npm | `run`、前端和端到端命令 | 提示安装 Node.js 并说明所需版本。 |
| Playwright 浏览器 | `e2e` | 提示执行 `python build.py e2e-install`。 |

## 质量门禁

交付前必须通过的最小检查集合。

| 门禁 | 命令 | 结果 |
|---|---|---|
| 后端风格 | `python build.py lint` | Ruff check 与 format check 成功。 |
| 后端测试 | `python build.py test` | pytest 成功。 |
| API 契约 | `python build.py contract` | OpenAPI 与实现一致。 |
| 前端客户端 | 涉及契约时 `python build.py gen-web-api` | 生成客户端与契约一致。 |
| 本地巡检 | 涉及全流程时 `python build.py verify` | 任务、规则结果和报告生成语义不变。 |
