# API 契约增量：任务数据长期留存与磁盘现场治理

正式契约必须先落入 `docs/api/openapi.yaml`，再修改 FastAPI 实现并生成前端客户端。本文件记录增量语义，不替代 OpenAPI。

## 版本原则

- 不新增路径、不改既有路径、不改 `/api/v1` 与 `/api/v2` 既有字段含义；全部为可选字段与错误语义的**非破坏性增量**。
- 任务运行字段随 `InspectionTask` / `TaskSummary` 自然出现在 `/api/v2/tasks`（列表）与 `/api/v2/tasks/{task_id}`（详情）。
- 上传恢复复用既有 `POST /api/v3/tasks`，只扩展"同名任务已存在"分支的行为，不新增接口。

## Schema 增量

### `InspectionTask` / `TaskSummary`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `last_run_at` | string(date-time) \| null | 否 | 最近一次运行的**开始**时刻（UTC）；从未运行为 `null` |
| `duration_ms` | integer \| null（≥0） | 否 | 最近一次运行耗时（毫秒）；运行中、从未运行为 `null` |

- 两个字段在 `TaskSummary`（继承 `InspectionTask`）上同样可见，列表与详情展示一致。
- 既有 `created_at`（创建时刻）语义不变：重跑/重建不更新。
- 其他 Schema（`RuleResult`、`SystemInspection`、`Finding`、`Metric`、`TaskListResponse`、`TaskLogs`）无字段变化。

## 错误码

| 错误码 | HTTP | 触发条件 | 消息要求 |
| --- | --- | --- | --- |
| `scene_cleaned` | 410 | 任务存在但现场目录已按留存策略清理，且操作依赖现场文件（报告、日志、重跑、重建） | 报告：说明报告已随现场清理、核心数据仍可在任务详情查看；日志：说明执行日志不入库且已随现场清理；重跑/重建：说明需重新上传同名数据包、确认覆盖后全量重建 |
| `package_missing` | 409 | 输出目录存在但原始上传包缺失或为空（既有错误码，消息补充恢复建议） | 提示可重新上传同名数据包、确认覆盖后全量重建 |
| `package_checksum_conflict` | 409 | 同名任务已存在，重传包 checksum 与首次接收记录不一致（既有错误码） | 保持既有语义与文案口径（可补充"内容不一致，拒绝恢复"） |
| `device_not_found` | 400 | `PATCH /api/v2/tasks/{task_id}/device-id` 或创建流程手动指定设备 ID 时，该 ID 不在设备台账 | 明确提示设备 ID 不存在于设备台账；不创建/不修改任务记录 |

所有错误继续使用统一结构 `{code, message, detail}`（既有错误契约不变）。

## `POST /api/v3/tasks` 同名判定与恢复语义（FR-013）

> 2026-10-13 修订：界面重传同名包改为 033 FR-024 的"覆盖确认 + 全量重建"（先删除旧任务再用当前包创建），不再直接依赖本表的恢复路径；本表语义保留为创建接口在探测未命中时的兜底，状态码、错误码与字段不变。

同名（派生同一 `task_id`）已存在时按以下矩阵处理：

| 现场包 | checksum 比对依据 | 结果 |
| --- | --- | --- |
| 存在 | 现场文件 | 一致：`202` + `Location`（既有幂等语义，不重跑）；不一致：`409 package_checksum_conflict` |
| 缺失（现场已清理） | `tasks.package_checksum` | 一致：把上传包写回 `uploads/<task_id>/<package_file>` 恢复现场，返回 `202` + `Location`；不重跑、不改任务历史数据、不触发留存清理 |
| 缺失 | 库中无 checksum（升级前历史任务）但有可读历史包 | 以历史包 checksum 为准并回填库，再按上一行处理 |
| 缺失 | 无 checksum 且无可读历史包 | `409`，消息说明无法校验原始包，不能恢复 |

- 恢复后的任务由用户显式发起重跑/重建，系统不得自动执行（FR-012）。
- 恢复不写/不改 `last_run_at`、`duration_ms`；重跑/重建时按正常运行更新。

## 受影响端点

| 端点 | 变化 |
| --- | --- |
| `GET /api/v2/tasks` | 数据源切换为数据库；返回新增字段；筛选、分页（默认 10）、排序语义不变 |
| `GET /api/v2/tasks/{task_id}` | 数据源切换为数据库；返回新增字段；`system.rules` 仍为摘要 |
| `GET /api/v2/tasks/{task_id}/system` | 数据源切换为数据库；`exclude_details` 行为不变 |
| `GET /api/v2/tasks/{task_id}/rules/{rule_code}` | 数据源切换为数据库；`exclude_records` 行为不变 |
| `GET /api/v2/overview` | 数据源切换为数据库聚合；字段与口径不变 |
| KPI 趋势 / 版本对比 / 指标明细端点 | 历史点改读数据库；响应 Schema 不变 |
| `GET /api/v2/tasks/{task_id}/report` | 现场缺失返回 410 `scene_cleaned`（原为 404） |
| `GET /api/v2/tasks/{task_id}/logs` | 现场缺失返回 410 `scene_cleaned`（原为 404）；执行日志仍不入库 |
| `POST /api/v2/tasks/{task_id}/rerun`、`POST /api/v2/tasks/{task_id}/rebuild` | 现场目录缺失时前置校验返回 410 `scene_cleaned`（不进入队列） |
| `PATCH /api/v2/tasks/{task_id}/device-id` | 新增台账存在性校验，不存在返回 400 `device_not_found` |
| `POST /api/v3/tasks` | 扩展同名恢复行为（见上，作为探测未命中的兜底）；界面重传同名包走"覆盖确认 + 全量重建"（先 DELETE 旧任务再创建），请求/响应 Schema 不变 |
| `DELETE /api/v2/tasks/{task_id}` | 级联删除补充 `task_rule_results`、`task_kpi_points`；其余语义不变 |

## 契约同步要求

- 先改 `docs/api/openapi.yaml`（Schema 字段 + 端点响应描述 + 错误码），再改 `app/models/schemas.py` 与实现。
- 执行 `python build.py contract` 校验 OpenAPI 与 Pydantic 一致，执行 `python build.py gen-web-api` 重新生成 `web/src/api`。
- 契约测试至少覆盖：新增字段可空性、`scene_cleaned` 410、`device_not_found` 400、`package_checksum_conflict` 409、恢复成功路径。
