# 实现计划：统一 Python 构建工具

**分支**：`feature/python-build-tooling` | **日期**：2026-09-14 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/008-python-build-tooling/spec.md` 的功能规格

## 摘要

将当前分散在 Makefile、shell 包装脚本和 uv 工作流中的开发命令收敛为唯一根目录入口 `build.py`。标准流程只依赖官方 Python 与其标准库创建 `.venv`，使用 `requirements-lock.txt` 精确安装依赖；前端与端到端流程仍调用 Node/npm/浏览器，但由 `build.py` 统一发起。迁移保持巡检执行、任务隔离、结果契约、报告与 API 契约语义不变，并同步更新权威文档与测试。

## 技术上下文

**语言/版本**：Python 3.11+；构建入口自身仅使用标准库。前端继续使用 Node/npm 生态。

**主要依赖**：后端保留现有 FastAPI、Pydantic v2、SQLAlchemy、Structlog、Ruff、pytest；前端保留 Vite、React、Ant Design、ECharts、openapi-typescript、Playwright。新增 `requirements-lock.txt`；移除 Makefile、本地启动 shell 包装脚本、uv 和 `uv.lock`。

**存储**：不适用；本功能不改变 SQLite、文件存储或任务产物模型。

**测试**：pytest 覆盖构建入口调度、参数校验、环境检查和旧入口移除看护；必要时用可注入命令执行器隔离 subprocess。

**目标平台**：开发者使用 macOS、Linux、Windows；生产容器当前保持 Python 3.12 slim 基线。

**项目类型**：Python 后端 + React Web 的单仓库开发工具迁移。

**性能目标**：构建命令自身启动与错误提示应即时；依赖安装性能不设硬性指标，正确性与可复现性优先。

**约束条件**：不得引入被检系统连接；不得改变巡检、任务、结果契约、报告或 OpenAPI 语义；不得依赖 GNU Make/uv；必须精确锁定后端依赖；文档与脚本在 Windows/macOS/Linux 间保持一致。

**规模/范围**：一个根目录构建入口、13 类现有工作流、精确锁文件、权威文档迁移和构建器测试。

## 命令映射

| 旧入口 | 新入口 | 说明 |
|---|---|---|
| `make install` | `python build.py install` | 创建/校验 `.venv`，按 `requirements-lock.txt` 精确安装后端依赖。 |
| `make verify` / `make offline` | `python build.py verify` | 调用本地全流程，等价于现有 `main.py`。 |
| `make run` / `make online` | `python build.py run` | 调用现有在线 API + Web 启动器。 |
| `make verify-one RULE=<code>` | `python build.py verify-one --rule <code>` | 调用现有单规则重跑逻辑。 |
| `make contract` | `python build.py contract` | 调用现有 OpenAPI 导出/校验逻辑。 |
| `make gen-web-api` | `python build.py gen-web-api` | 调用前端 API 客户端生成。 |
| `make test` | `python build.py test` | 调用 pytest。 |
| `make lint` | `python build.py lint` | 调用 Ruff check 和 format check。 |
| `make web-install` | `python build.py web-install` | 安装前端依赖。 |
| `make web-dev` | `python build.py web-dev` | 启动前端开发服务。 |
| `make web-build` | `python build.py web-build` | 构建前端。 |
| `make e2e-install` | `python build.py e2e-install` | 安装前端与 Playwright 浏览器依赖。 |
| `make e2e` | `python build.py e2e` | 运行端到端测试。 |

新增 `python build.py lock` 用于从 `pyproject.toml` 重新解析并刷新 `requirements-lock.txt`；该命令属于维护流程，不改变标准安装语义。

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

- **离线优先**：合规。构建器只在本地编排命令；依赖安装可能访问包仓库，属于开发环境准备，不是被检系统连接或在线采集。
- **一个包、一个任务**：合规。不改变任务模型、`task_id` 派生或输出目录隔离。
- **契约驱动**：合规。不修改 OpenAPI、Pydantic 契约或生成客户端语义；`gen-web-api` 保持既有行为。
- **模式同构**：合规。`verify` 与 `run` 只是调用现有本地/在线入口，不改变共享巡检器与执行契约。
- **巡检器插件架构 / 源文件匹配 / 增量重跑**：合规。不修改规则注册、匹配、prepare 或调度语义。
- **轻量默认**：合规。后端标准流程使用官方 Python、`venv`、pip 与文件锁；不新增运行时服务。
- **容错与可追溯**：合规。命令失败必须返回非零并保留可定位输出。
- **安全解压**：不适用；不改变解压实现。
- **技术基线**：合规。保持 Python 3.11+、FastAPI、Pydantic v2、React/Vite、SQLite 和文件存储；移除 uv 降低额外工具依赖。
- **开发工作流与质量门禁**：合规。权威文档同步改为 `build.py`，并补齐构建器测试。

## 项目结构

### 文档（本功能）

```text
specs/008-python-build-tooling/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── build-cli.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
build.py                          # 新增统一构建入口
requirements-lock.txt             # 新增后端精确依赖锁
pyproject.toml                    # 保留依赖声明与工具配置
requirements.txt                  # 移除或替换为指向锁文件的最小说明
Dockerfile                        # 改用精确锁文件安装后端依赖
README.md                         # 更新开发与交付命令
AGENTS.md                         # 更新 Agent 质量门禁与本地调试命令
docs/architecture.md              # 更新架构与开发者命令
docs/roadmap.md                   # 更新当前交付门禁命令
app/contract/export.py            # 仅更新说明中的旧命令表述
tests/                            # 新增构建器与迁移看护测试
web/                              # 前端工作流仍由 npm 执行
Makefile                          # 删除
run-offline.sh                    # 删除
run-online.sh                     # 删除
uv.lock                           # 删除
.gitignore                        # 移除 uv 专用忽略项
```

**结构决策**：沿用现有单仓库结构；构建入口放在仓库根目录，避免新增包、服务层或部署形态。

## 实施设计

### 统一入口

- `build.py` 使用标准库 `argparse` 提供子命令、帮助、版本检查和错误提示。
- 所有子进程通过 `subprocess.run()` 的参数列表执行，禁用 shell 解释。
- 后端命令优先选择 `.venv` 内解释器；`.venv` 缺失时提示先执行 `python build.py install`。
- 前端命令通过跨平台方式发现 npm/npx；Windows 优先匹配 `npm.cmd`/`npx.cmd`。
- 未知命令、缺失参数、缺少 Node/npm 或浏览器依赖时返回非零并给出下一步操作。
- 长时间运行的 `run` 与 `web-dev` 保持前台进程行为，Ctrl+C 语义由现有入口或前端工具保留。

### 环境与依赖

- `install` 使用 `sys.executable -m venv .venv` 创建环境；必要时用标准 `ensurepip`/pip 自升级保证 pip 可用。
- 安装流程使用 `requirements-lock.txt` 精确安装直接与传递依赖，再以 `--no-deps` 安装/更新本地项目，避免二次解析。
- `requirements-lock.txt` 必须覆盖后端运行、测试和 lint 依赖，并使用环境标记处理平台差异（尤其是 uvicorn 标准扩展相关依赖）。
- `lock` 通过 pip 的解析能力生成/刷新精确锁；更新锁后必须在 macOS、Linux 和 Windows 至少完成安装或等效干运行验证。
- 现有 uv 创建的 `.venv` 不作为标准环境依据；不满足要求时提示删除重建。

### 文档与迁移

- 活跃文档中的基础流程、质量门禁、契约流程、单规则调试和端到端命令全部替换为 `build.py`。
- `AGENTS.md` 与 Constitution 引用的质量门禁命令保持一致，但 Constitution 本身仅在工具语义变化确有必要时另行修正；本功能不改其治理原则。
- 删除 Makefile、`run-offline.sh`、`run-online.sh` 和 `uv.lock`。
- `.gitignore` 移除 uv 专用忽略项；本地旧缓存可由开发者手动清理。
- Dockerfile 改为使用 `requirements-lock.txt`，保持 API 运行行为不变。

## 测试策略

1. **单元测试**：验证 `build.py` 命令映射、参数透传、缺失参数、未知命令和前置条件错误。
2. **环境测试**：通过注入的执行器验证 `install` 创建 `.venv`、使用锁文件、禁止 shell 解释、跨平台解释器路径。
3. **迁移看护测试**：断言 Makefile、本地启动 shell 包装脚本和 `uv.lock` 不存在；活跃文档不再推荐 `make` 或 uv。
4. **等价性测试**：`contract`、`test`、`lint`、`verify`、`verify-one` 与旧命令产生相同产物或状态；巡检结果契约不变。
5. **前端/端到端冒烟**：前端依赖安装、构建和 Playwright 命令可由 `build.py` 发起。
6. **平台验证**：在 Windows、macOS、Linux 上验证安装与核心命令；至少通过测试替身覆盖路径差异。

## 复杂度跟踪

无宪法违规，不需要记录复杂度豁免。
