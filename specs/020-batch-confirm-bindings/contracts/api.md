# API 契约草案：指标绑定批量确认

实际契约以 `docs/api/openapi.yaml` 为准；实现时先同步 OpenAPI，再生成前端客户端。

## 批量确认绑定

`POST /api/v5/kpi/measurement-bindings/batch-confirm`

权限：`admin`。

请求体：

```json
{
  "binding_ids": [12, 13, 14]
}
```

- `binding_ids`：非空整数数组，最大 200 项。
- 服务层按首次出现顺序去重；重复 ID 只返回一条结果。
- 空数组或超过 200 项由请求模型拒绝。

成功响应：`200`。

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "items": [
    {
      "binding_id": 12,
      "outcome": "confirmed",
      "binding": { "id": 12, "status": "confirmed" }
    },
    {
      "binding_id": 13,
      "outcome": "already_confirmed"
    },
    {
      "binding_id": 999999,
      "outcome": "failed",
      "error_code": "kpi_binding_not_found",
      "message": "绑定不存在: 999999"
    }
  ]
}
```

- `succeeded` 包含 `confirmed` 和 `already_confirmed`。
- `items[]` 按请求中绑定 ID 首次出现顺序排序。
- `binding` 只在成功项返回；`error_code` / `message` 只在失败项返回。

主要失败原因：

- `kpi_binding_not_found`：绑定不存在。
- `kpi_binding_metric_missing`：候选绑定缺少 `metric_resource_id`。
- `kpi_binding_status_not_confirmable`：状态为 `conflict`、`ignored` 或其他不允许批量确认的状态。
- `kpi_binding_conflict`：同一 ME 指标跨测量单元冲突。
