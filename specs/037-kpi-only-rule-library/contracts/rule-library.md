# 契约：KPI-only 规则库与历史结果

本功能不新增 API 路径、字段、Schema 或版本；以下行为在现有 `/api/v2` 契约上生效。

## 活动规则目录

`GET /api/v2/inspectors`

- 默认响应只包含 `kpi.measurement_units`，其 `hidden=false`、`category=kpi`。
- `include_hidden=true` 时可按既有参数返回 `pkg.extract.*`；hidden 解压基础设施不得被解释为普通规则。
- 响应不得包含 `alarm.*`、`config.*`、`log.*`、`resource.*`、`traffic.*` 活动规则。
- `InspectorInfo` 字段保持不变。

`GET /api/v2/inspector-states`

- 只返回活动普通规则 `kpi.measurement_units` 的启停状态。
- SQLite 中遗留的非 KPI 状态行保留，但不出现在分页结果或统计中。

`PUT /api/v2/inspector-states/{rule_code}/enabled`

- KPI 规则沿用现有启停语义。
- hidden 规则返回既有 `rule_not_manageable`。
- 已删除规则返回明确的 `not_found`，不得重建状态或执行旧代码。

## 任务结果与历史读取

`GET /api/v2/tasks/{task_id}/rules/{rule_code}`

- 对活动 KPI 与历史非 KPI 规则一视同仁：按 SQLite、规则 JSON、system 摘要顺序读取。
- 已持久化结果存在时返回 200，即使该规则已从活动库删除。
- 结果不存在时返回既有 `404 not_found`。
- 读取历史结果不得把规则重新加入活动目录或允许其重跑。
- `RuleResult` Schema 字段不变。

`GET /api/v2/tasks/{task_id}/system`

- 新任务的 `rules` 只包含 KPI 普通规则结果。
- 历史任务仍保留其已持久化的非 KPI 摘要，供历史追溯。
- hidden `pkg.extract.*` 不进入普通规则结果。

## 新任务执行计划

`POST /api/v3/tasks` 创建的默认任务：

```text
EXTRACT: pkg.extract.main + pkg.extract.{logs,kpi,traffic,alarm,config,resource,other}
PREPARE: 活动规则私有 prepare（如有）
INSPECT: kpi.measurement_units（启用时）
```

- 普通规则结果数量为 1。
- 非 KPI 文件仍解压、分类并保留。
- KPI 无输入时返回 `status=skip` 且 `skip_reason` 非空。

## 重跑与重建

`POST /api/v2/tasks/{task_id}/rerun`

- `rule_codes` 包含已删除规则时返回 `400 unknown_rule`。
- 不改变任务状态、输出文件、历史结果或执行日志。
- 空 `rule_codes` 的既有全量语义不变。

`POST /api/v2/tasks/{task_id}/rebuild`

- `mode=incremental` 只接受活动普通规则 KPI。
- 已删除规则返回 `400 unknown_rule`；hidden 解压规则返回 `400 invalid_rebuild_request`。
- 预检失败不得修改任务现场。

## CLI

- `run_single_rule("log.error_density", ...)` 等已删除代码必须返回明确的未注册/不存在错误。
- `kpi.measurement_units` 的 CLI/API 双模式结果继续保持同构。

## 兼容性

- 不修改 `/api/v1` 或 `/api/v2` 既有字段含义。
- 不升级 API 主版本。
- 不删除 `RuleCategory` 历史枚举值。
- 不迁移或清空真实 SQLite 历史数据。
- OpenAPI 只允许更新说明文字，不改变 `operationId`、参数或响应 Schema。
