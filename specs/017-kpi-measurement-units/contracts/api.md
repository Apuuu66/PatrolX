# API 契约草案

Base path: `/api/v5`

## POST /api/v5/kpi/measurement-units/import

multipart/form-data：

- `file`: 资源目录 CSV

响应 `200`：

```json
{
  "added": {"mu": 1, "me": 2, "unit": 1},
  "updated": {"mu": 0, "me": 1, "unit": 0},
  "skipped": [],
  "errors": []
}
```

规则：同一类资源按中文名合并；同名不同 `resource_id` 保留既有或首个 `resource_id` 并允许更新英文名。同一 `resource_id` 对应不同中文名时返回行级 `resource_id_conflict` 且不覆盖。不删除 CSV 中未出现的资源；单行错误跳过并返回 errors。

## GET /api/v5/kpi/measurement-units

查询：`search`、`enabled`、`page`、`page_size`。

返回测量单元列表、指标统计、绑定统计和派生统计。

## PATCH /api/v5/kpi/measurement-units/{resource_id}

请求 `{"enabled": true|false}`，仅允许 `MU__*`。

## GET /api/v5/kpi/measurement-bindings

查询：`measurement_unit_id`、`status`、`search`、`page`、`page_size`。

## PATCH /api/v5/kpi/measurement-bindings/{binding_id}

请求 `{"status": "confirmed"|"ignored", "enabled": true|false}`。改绑冲突必须返回 `409 kpi_binding_conflict`。

## POST /api/v5/kpi/measurement-derived

请求：

```json
{
  "measurement_unit_id": "MU__CALL_SESSION_API_STATISTICS",
  "metric_resource_id": "ME_SUCCESS_RATE",
  "numerator_metric_id": "ME_SUCCESS_CALLS",
  "denominator_metric_id": "ME_TOTAL_CALLS"
}
```

响应 `201`。模板固定 `success_rate`；依赖必须属于同一 MU。

## GET /api/v2/tasks/{task_id}/rules/kpi.measurement_units

复用普通规则结果读取；`metadata.result` 是新版 MU 巡检结构，包含文件发现、绑定发现、MU 汇总、指标明细、对象明细、派生指标和待处理项。
