# 台账删除 API 契约

所有写接口要求 `Authorization` 会话具有 `admin` 角色。错误返回统一 `{code, message, detail}`。

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
