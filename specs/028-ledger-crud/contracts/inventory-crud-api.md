# 台账 CRUD API 契约

所有写接口要求 `Authorization` 会话具有 `admin` 角色。错误返回统一 `{code, message, detail}`。

## `POST /api/v2/inventory/devices`

创建设备档案。

请求：

```json
{
  "province": "江苏",
  "operator": "移动",
  "device_name": "NJ-AGG-001",
  "remark": "核心汇聚设备"
}
```

响应：`201`，`Location: /api/v2/inventory/devices/{device_id}`，body 为 `InventoryDevice`。

错误：

| code | 状态 | 场景 |
| --- | --- | --- |
| `device_already_exists` | 409 | 同省份规范化设备名已存在 |
| `invalid_request` | 400 | 必填字段为空或格式不合法 |

## `PATCH /api/v2/inventory/devices/{device_id}`

更新设备维护信息，第一版只支持 `remark`。

请求：

```json
{ "remark": "更换光模块后需复核版本" }
```

响应：`200`，body 为最新 `InventoryDevice`。

错误：

| code | 状态 | 场景 |
| --- | --- | --- |
| `not_found` | 404 | 设备不存在 |
| `invalid_request` | 400 | 缺少请求体或字段不属于可维护范围 |

## `DELETE /api/v2/inventory/devices/{device_id}`

物理删除设备台账。

响应：`204`。

错误：

| code | 状态 | 场景 |
| --- | --- | --- |
| `not_found` | 404 | 设备不存在 |

删除范围：

- `inventory_devices` 中该设备。
- `inventory_observations` 中该设备全部观测。
- `inventory_change_audits` 中该设备历史审计。
- 追加一条删除审计，记录操作者和删除前摘要。

不删除范围：

- `uploads/<task_id>/<package>`
- `output/<task_id>/inventory.json`
- 任务记录、任务详情、巡检规则结果和报告。

## 响应模型增量

`InventoryDevice` 在既有字段后新增：

```json
{
  "remark": "核心汇聚设备",
  "created_by": "admin",
  "updated_by": "admin",
  "updated_at": "2026-10-07T08:00:00Z"
}
```

所有新增字段均为可选或可空，不破坏既有客户端。
