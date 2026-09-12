# API 契约：系统基线

权威接口已在 [`docs/api/openapi.yaml`](../../../docs/api/openapi.yaml) 中定义。本文档记录 OpenAPI 契约和实现必须持续满足的基线行为。

## 通用契约规则

- API 路径保持在 `/api/v1` 版本下。
- 资源响应直接返回资源 JSON。
- 创建/重跑操作使用 accepted 响应语义并附带轮询位置。
- 错误使用既定的 `{code, message, detail}` 错误结构。
- 列表响应使用分页并返回总数。
- 破坏性变更要求新版本，而非对 `/api/v1` 的语义变更。
- 生成的前端客户端必须与 OpenAPI 保持同步。

## 基线端点

| 能力 | 方法和路径 | 基线要求 |
| --- | --- | --- |
| 健康检查 | `GET /healthz` | 报告服务存活状态。 |
| 指标 | `GET /metrics` | 暴露 Prometheus 兼容的运维指标。 |
| 创建任务 | `POST /api/v1/tasks` | 接受一个包；返回 accepted 响应和轮询位置。 |
| 列表任务 | `GET /api/v1/tasks` | 返回分页任务摘要和总数。 |
| 任务详情 | `GET /api/v1/tasks/{task_id}` | 返回任务状态、统计和系统摘要。 |
| 删除任务 | `DELETE /api/v1/tasks/{task_id}` | 将任务输入和输出作为单一生命周期单元移除。 |
| 重跑规则 | `POST /api/v1/tasks/{task_id}/rerun` | 支持全部或选定规则代码；返回 accepted 响应。 |
| 报告 | `GET /api/v1/tasks/{task_id}/report` | 提供在线预览的 HTML 报告。 |
| 执行日志 | `GET /api/v1/tasks/{task_id}/logs` | 提供任务执行历史。 |
| 系统巡检 | `GET /api/v1/tasks/{task_id}/system` | 返回系统摘要和规则状态。 |
| 规则结果 | `GET /api/v1/tasks/{task_id}/rules/{rule_code}` | 返回一条完整规则结果。 |
| 总览 | `GET /api/v1/overview` | 返回聚合仪表盘/总览数据。 |
| 巡检器元数据 | `GET /api/v1/inspectors` | 返回注册规则元数据和输出契约。 |
| 字典列表 | `GET /api/v1/dicts` | 返回内置/配置的字典组。 |
| 更新字典 | `PUT /api/v1/dicts/{dict_name}` | 维护一个字典组。 |

## 基线不变量

1. 一个上传的包映射到一个任务。
2. 一个任务暴露一个系统巡检。
3. 规则结果通过稳定规则代码可寻址。
4. 规则元数据包含描述、建议、输入、输出和版本。
5. 重跑可以更新目标规则而不丢弃无关结果。
6. 删除是任务级的，覆盖保留包输入和生成输出。
7. 任何端点不得引入对被检系统的在线采集。
