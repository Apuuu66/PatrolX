# PatrolX 巡检系统

PatrolX 是一个面向系统维护场景的**离线巡检系统**：不连接被检系统、不做在线采集，用户将预先收集好的数据打包上传，系统对包内数据执行规则化巡检，输出契约化结果与 HTML 报告。

设计文档与开发约定见 [AGENTS.md](AGENTS.md)。

## 快速开始（本地开发模式）

```bash
make install        # 安装依赖（uv + Python 3.12）
# 将收集包放入 uploads/ 根目录
python main.py      # 一键扫描 → 解压 → 运行全部规则 → 生成契约数据与报告
make verify-one RULE=log.error_density   # 单条规则重跑
```

## 在线模式

```bash
make run            # 启动 FastAPI（SQLite + 文件存储）
cd web
npm install         # 首次：安装前端依赖
npm run dev         # 启动前端（默认代理 http://127.0.0.1:8000）
```

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
