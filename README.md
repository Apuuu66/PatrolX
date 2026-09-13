# PatrolX 巡检系统

PatrolX 是一个面向系统维护场景的**离线巡检系统**：不连接被检系统、不做在线采集，用户将预先收集好的数据打包上传，系统对包内数据执行规则化巡检，输出契约化结果与 HTML 报告。

设计文档见 [docs/architecture.md](docs/architecture.md)，Agent 开发约定见 [AGENTS.md](AGENTS.md)，长期项目约束见 [`.specify/memory/constitution.md`](.specify/memory/constitution.md)。

## 快速开始

只需要使用两类入口：

```bash
# 离线调试：把收集包放入 uploads/ 根目录后执行
./run-offline.sh

# 在线预览：启动后端 API 和前端页面，按 Ctrl+C 停止
python run_online.py
```

脚本会自动准备本地 Python 虚拟环境；在线模式还会在首次执行时安装前端依赖。

在线启动器支持常用参数，例如关闭后端自动重载：

```bash
python run_online.py --no-reload
```

### 任务 ID 规则

在线和离线使用统一格式：`task-<包名清洗后的标识>`，同一包 → 同一任务 → 同一输出目录。

```text
sample.zip → task-sample
```

### 规则调试闭环

```text
1. ./run-offline.sh               → 全流程跑完，数据准备好
2. ./run-online.sh                → 启动 Web
3. 浏览器打开前端                  → 看到任务结果
4. 改规则代码                      → 只改目标规则逻辑
5. make verify-one RULE=xxx       → 秒级重跑该规则
6. 浏览器刷新                      → 直接看到最新效果
```

单条规则在数据未准备时会 SKIP 并提示先执行全量巡检，不会回溯解压。

### 重复上传

在线重复上传同一个包时，若包 checksum 一致则复用既有任务现场；若 checksum 不同则返回 `409 package_checksum_conflict`，不会删除或覆盖既有任务。

前端技术栈：React + TypeScript + Vite + Ant Design + ECharts；API 客户端由契约自动生成：

```bash
make gen-web-api    # 由 docs/api/openapi.yaml 重新生成 web/src/api/client.ts
```

页面：任务列表（上传/重跑/删除）、任务详情（摘要/规则分组/单规则重跑）、规则详情（指标图表/发现/建议）、报告预览（iframe）、执行日志、规则管理（只读）、数据字典。本地与在线模式共用同一套页面与 API。

## 可观测

- `GET /healthz`：健康检查；`GET /metrics`：Prometheus 指标（任务/规则计数、任务耗时直方图）。
- 日志：structlog 结构化日志——开发环境彩色控制台，`PATROLX_ENV=production` 或 `PATROLX_LOG_JSON=1` 时输出 JSON；级别用 `PATROLX_LOG_LEVEL` 覆盖（默认 dev=DEBUG / prod=INFO）。
- 任务执行日志独立落盘：`output/<task_id>/execution.log`（JSON Lines，前端「执行日志」页查看）。

## 容器化部署（Docker 可选）

```bash
docker compose up --build -d    # 构建并启动（8000 端口；uploads/output 挂载持久卷）
```

镜像基于 `python:3.12-slim`，默认以生产模式启动（`PATROLX_ENV=production`、JSON 日志）。已内置健康检查。

## 常用命令

见 `Makefile`：`make contract`（导出 OpenAPI）、`make test`、`make lint`、`make verify`（本地全流程）等。
