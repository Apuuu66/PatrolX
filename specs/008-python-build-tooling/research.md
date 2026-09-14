# 研究记录：统一 Python 构建工具

## R1 — 统一入口实现方式

**Decision**：在仓库根目录新增 `build.py`，使用 Python 标准库 `argparse` 和 `subprocess` 编排子命令。

**Rationale**：
- 用户已在规格澄清中确定 `python build.py <操作> [参数]`。
- 标准库方案在干净环境中不需要额外安装命令框架。
- 参数列表方式调用子进程可避免 Make/shell 语法和 Windows 转义差异。

**Alternatives considered**：
- `python -m patrolx.build`：需要先安装项目，降低干净环境可用性。
- 安装 console script：安装前无法使用，增加引导复杂度。
- shell 脚本：无法满足 Windows 与无 Unix shell 目标。

## R2 — 虚拟环境创建与依赖安装

**Decision**：标准流程由 `build.py` 调用 `python -m venv .venv` 创建环境，随后使用该环境中的 pip 安装 `requirements-lock.txt`，并以 `--no-deps` 处理本地项目安装。

**Rationale**：
- `venv` 和 `ensurepip`/pip 属于官方 Python 生态，可满足“干净环境仅要求官方 Python”的验收。
- 通过锁文件安装避免每次按 `pyproject.toml` 范围重新解析。
- 不复用 uv 创建的 `.venv` 元数据；不满足标准环境时提示重建。

**Alternatives considered**：
- 继续 uv sync：需要额外安装 uv，违背最新澄清。
- 每次按 `pyproject.toml` 解析：依赖版本不精确，跨机器不可复现。
- 使用 `pip-tools` 等额外锁工具：标准安装仍可行，但增加工具依赖；仅在锁维护确有需要时可在开发环境中评估。

## R3 — 精确锁文件形态

**Decision**：新增 `requirements-lock.txt` 作为唯一权威后端锁。它记录直接依赖与传递依赖的精确版本，并允许 PEP 508 环境标记表达平台差异。`build.py lock` 用于刷新该文件。

**Rationale**：
- 精确锁满足用户要求的版本确定性。
- pip 可跨平台消费该文件，无需 uv。
- 环境标记可处理 `uvicorn[standard]` 等依赖在不同平台的可选组件，避免一份锁文件在 Windows 上失败。

**Alternatives considered**：
- `uv.lock`：需要 uv，已被排除。
- 只锁直接依赖：传递依赖仍漂移。
- 多平台各自生成锁：增加维护成本且难以评审。
- 无锁安装：不符合精确版本要求。

## R4 — 前端与端到端依赖

**Decision**：前端依赖继续由 npm/package-lock 管理，端到端浏览器继续由 Playwright 管理；`build.py` 负责统一发现工具并透传命令。

**Rationale**：
- 这些是前端生态自身依赖，规格明确不要求用 Python 替代。
- 保留 `web/package-lock.json` 可继续约束前端版本。
- 统一入口只需消除项目级入口分裂。

**Alternatives considered**：
- 用 Python 下载/管理浏览器：重复实现 Playwright 能力。
- 不支持前端命令：违反 FR-004。

## R5 — 跨平台进程调用

**Decision**：后端命令使用 `.venv` 内 Python 可执行文件；前端命令通过 `shutil.which()` 发现 npm/npx，并始终以参数列表调用。

**Rationale**：
- Windows 的 npm/npx 通常是 `.cmd` 入口，直接假设 Unix 路径会失败。
- 参数列表可避免 shell 转义和 `set -e` 语义差异。
- 以当前仓库根目录作为工作目录，保证相对路径语义一致。

**Alternatives considered**：
- `shell=True`：跨平台风险高，且难以安全转义。
- 继续依赖 bash：无法满足 Windows 目标。

## R6 — 旧入口迁移范围

**Decision**：删除 `Makefile`、`run-offline.sh`、`run-online.sh` 和 `uv.lock`；活跃文档统一使用 `python build.py`。历史 Speckit 产物与归档计划不改写。

**Rationale**：
- 避免旧入口继续分叉。
- 权威文档与实际入口一致。
- 历史记录保留原貌，降低无关变更。

**Alternatives considered**：
- 保留 deprecated 包装：迁移期看似友好，但违反唯一权威入口要求。
- 批量改写历史计划：产生无关 diff，且无法证明当时执行环境。

## R7 — Docker 依赖安装

**Decision**：Dockerfile 改为复制并安装 `requirements-lock.txt`，不使用 uv 和旧 `requirements.txt`；生产启动命令不变。

**Rationale**：
- 与本地标准依赖锁一致。
- 避免 `requirements.txt` 与新锁漂移。
- 不改变容器端口、健康检查或 API 行为。

**Alternatives considered**：
- 在容器中引入 build.py 安装流程：容器镜像只需依赖安装，不需要开发者编排能力。
- 保留旧 requirements.txt：形成第二套后端依赖入口。

## R8 — 契约影响

**Decision**：OpenAPI 与生成前端客户端不做语义修改；本功能单独提供开发者命令契约文档。

**Rationale**：
- 构建器不是在线 API 契约的一部分。
- `contract` 与 `gen-web-api` 仅迁移调用入口，产物应保持一致。

**Alternatives considered**：
- 将 build CLI 写入 OpenAPI：错误抽象，OpenAPI 描述 HTTP API。
