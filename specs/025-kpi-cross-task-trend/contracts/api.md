# API 契约草案：KPI 跨任务历史趋势

本文件是阶段 1 设计契约。实现时必须先把以下变更写入 `docs/api/openapi.yaml`，再修改 Pydantic/FastAPI，并重新生成前端客户端。

所有新增字段和接口均为向后兼容新增；不修改既有 `/api/v2` 字段语义。

## 1. 创建任务时填写设备 ID

### 请求

`POST /api/v2/tasks`

`multipart/form-data` 新增可选字段：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `device_id` | string | 否 | trim 后可为空；非空长度 1–128。 |

### 响应

沿用 `202 + Location` 和 `TaskCreated`，不新增响应字段。

### 行为

- `device_id` 保存到 `TaskRecord.customer["device_id"]`。
- 巡检完成后同步输出到 `system.customer.device_id` 和 `task.json`。
- 空/未填写等同无设备 ID。

## 2. 修改任务设备 ID

### 请求

`PATCH /api/v2/tasks/{task_id}/device-id`

```json
{
  "device_id": "BCN-APP-01"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `device_id` | string | 是 | trim 后可为空；非空长度 1–128。 |

### 权限

- 仅 `admin`。
- 认证失败返回现有统一 401/403 语义。
- 权限必须由后端校验。

### 响应

`200 TaskSummary`

新增字段：

```json
{
  "device_id": "BCN-APP-01"
}
```

### 状态码

| 状态码 | 场景 |
| --- | --- |
| 200 | 修改成功。 |
| 400 | `invalid_device_id`。 |
| 403 | 非 admin。 |
| 404 | 任务不存在。 |
| 409 | 任务 pending/running，`task_busy`。 |
| 422 | 请求体验证失败。 |

### 行为

- 更新 SQLite `TaskRecord.customer["device_id"]`。
- 对已有 `system.json` 和 `task.json` 同步更新 `customer.device_id`。
- 不修改原始上传包。
- 不清除或重建巡检结果。
- 不修改 `created_at`、`completed_at`。

## 3. 查询单指标历史趋势

### 请求

`GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/history-trend`

#### Path

| 参数 | 说明 |
| --- | --- |
| `task_id` | 当前任务 ID。 |
| `rule_code` | 本期必须为 `kpi.measurement_units`。 |
| `measurement_unit_id` | 测量单元 ID。 |
| `metric_resource_id` | 指标 ID。 |

#### Query

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `object_key` | string | 是 | 行对象；无行对象传 `__all__`。 |
| `period_minutes` | integer（可选） | 是 | 周期分钟数；未提供或缺省时表示 `null`，即双方都无法识别周期的点。 |

### 响应

`200 MeasurementHistoryTrend`

```json
{
  "task_id": "task-example",
  "rule_code": "kpi.measurement_units",
  "measurement_unit_id": "MU_APP",
  "metric_resource_id": "ME_QPS",
  "device_id": "BCN-APP-01",
  "object_key": "app-1",
  "period_minutes": 15,
  "window": {
    "end_date": "2026-09-23",
    "start_date": "2026-09-17",
    "days": 7,
    "anchor_measured_at": "2026-09-23T10:00:00Z"
  },
  "match": {
    "status": "matched",
    "reason_code": null,
    "message": "已匹配 5 个历史任务"
  },
  "coverage": {
    "history_task_count": 5,
    "history_date_count": 5,
    "history_point_count": 480,
    "current_point_count": 96,
    "latest_history_date": "2026-09-22"
  },
  "current_points": [],
  "history_series": [],
  "baseline_points": [],
  "source_tasks": []
}
```

完整嵌套结构见 [data-model.md](../data-model.md)。

### 状态码

| 状态码 | 场景 |
| --- | --- |
| 200 | 找到当前指标；即使历史不可用，也返回降级投影。 |
| 400 | 查询参数无效。 |
| 404 | 任务、规则、测量单元或指标不存在。 |
| 422 | 参数绑定失败。 |

### 降级约定

- 无历史不是错误；`match.status=degraded` 或 `no_history`。
- 历史索引缺失返回 `history_index_missing`，不自动重建。
- 当前任务无有效 KPI 测量时间返回 `current_measurement_time_missing`。
- 当前任务设备 ID 缺失返回 `device_id_missing`。
- 行对象或周期不匹配时不混合数据。
- 样本不足时保留曲线和窗口，但基线 `significance=insufficient`。

## 4. OpenAPI 同步范围

实现阶段必须同步：

1. `Body_createTaskV2` 增加 `device_id`。
2. `TaskSummary` 增加 `device_id`。
3. 新增 `TaskDeviceIdUpdateRequest`。
4. 新增 `MeasurementHistoryTrend` 及嵌套 Schema。
5. 新增 `updateTaskDeviceIdV2` 和 `getMeasurementHistoryTrendV2` operation。
6. 执行项目契约校验和前端客户端生成命令。

## 5. 错误模型

沿用现有统一错误：

```json
{
  "code": "invalid_device_id",
  "message": "设备 ID 长度必须为 1-128",
  "detail": {}
}
```

所有错误消息使用中文；错误码和字段名使用英文。
