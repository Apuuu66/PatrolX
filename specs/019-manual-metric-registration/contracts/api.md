# API 契约草案：人工注册指标

实际契约以 `docs/api/openapi.yaml` 为准；实现时先同步 OpenAPI，再生成前端客户端。

## 注册或改绑当前未注册指标

`POST /api/v5/kpi/measurement-bindings/{binding_id}/register-metric`

权限：`admin`。

请求体：

```json
{
  "name_zh": "呼叫请求次数",
  "name_en": "call_request",
  "bind_existing_resource_id": null
}
```

- `bind_existing_resource_id`：可空；`null` 表示创建新人工指标，非空表示绑定既有 ME 资源。
- 创建新指标时：`name_zh` 必填且不能为空，`name_en` 可空。
- 绑定既有资源时：`name_zh` 和 `name_en` 必须为 `null`；`display_unit` 由绑定行已有数据提供，不作为请求字段。
- `name_zh` 与同 `kind=me` 资源冲突且未选择该资源时，返回冲突错误和既有资源 ID。

成功响应：`200`，返回更新后的绑定 JSON；`metric_resource_id` 有值，`status=candidate`。

主要错误：

- `kpi_binding_not_found`：绑定不存在。
- `kpi_metric_name_conflict`：ME 中文名已存在且未选择该资源。
- `kpi_metric_not_found`：选择的已有指标不存在。
- `kpi_metric_kind_invalid`：选择的资源不是 ME。

## 编辑人工注册指标

`PATCH /api/v5/kpi/measurement-resources/{resource_id}`

权限：`admin`。

请求体：

```json
{
  "name_zh": "呼叫请求总数",
  "name_en": "call_request_total",
  "enabled": true
}
```

字段均为可选；至少提供一个可更新字段。

成功响应：`200`，返回更新后的资源 JSON。

主要错误：

- `kpi_metric_not_found`：资源不存在。
- `kpi_metric_not_manual`：资源 ID 不带 `ME__MANUAL_` 前缀。
- `kpi_metric_name_conflict`：新中文名与其他 ME 资源冲突。
