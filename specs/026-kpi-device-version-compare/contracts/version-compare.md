# 版本对比契约设计

正式 Schema 落入 `docs/api/openapi.yaml`，本文件记录新增边界。

## 候选接口

`GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/version-candidates`

Query：

- `object_key`：必填，传给服务层以保持候选上下文一致性。
- `period_minutes`：必填 integer|null。

Response：`MeasurementVersionCandidateList`

服务层在候选阶段只做设备、状态、版本和任务元数据筛选；不因维度无点隐藏候选，便于用户看到“该版本任务没有当前维度数据”的原因。

## 对比接口

`GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/version-compare`

Query：

- `baseline_task_id`：必填。
- `object_key`：必填。
- `period_minutes`：必填 integer|null。

Response：`MeasurementVersionComparison`

错误处理：

- 当前任务不存在：404。
- `rule_code != kpi.measurement_units`：404。
- 服务发现可定位不匹配时返回 200 + `match.status=degraded/no_history`，不使用 500 隐藏原因。
- 缺少必填 query：FastAPI 422。

## 契约同步

实现前先修改 OpenAPI，并执行：

```bash
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
```
