# 维护配置与派生配置 API 契约

**日期：** 2026-11-05  
**基础路径：** `/api/v5/kpi`

## 1. 维护配置列表

```http
GET /api/v5/kpi/metric-maintenance-configs?measurement_unit_id=&metric_resource_id=&enabled=&page=1&page_size=20
```

- 认证：读取无需额外角色；与现有测量资源列表保持一致。
- `page` 默认 1；`page_size` 默认 20、最大 200。
- 返回 `total`、`items`。
- 结果按测量单元 ID、指标显示顺序、指标 ID 稳定排序。

```json
{
  "total": 77,
  "items": [
    {
      "measurement_unit_id": "MU_CALL",
      "metric_resource_id": "ME_RATE",
      "name_zh": "呼叫成功率",
      "role": "derived",
      "direction": "higher_better",
      "warning_threshold": 99.0,
      "critical_threshold": 98.0,
      "daily_aggregation": "sum",
      "daily_change_threshold": 0.2,
      "daily_change_threshold_unit": "pp",
      "is_percentage": true,
      "zero_semantics": "unknown",
      "consistency_tolerance": 0.2,
      "object_match_mode": "exact",
      "enabled": true,
      "config_source": "custom",
      "updated_at": "2026-11-05T01:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 20
}
```

## 2. 维护配置详情

```http
GET /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}
```

- 不存在或指标未绑定到该测量单元：`404 kpi_metric_config_not_found`。
- 资源存在但无扩展配置：返回有效配置，`config_source=legacy_resource`，扩展字段使用安全默认值。

## 3. 更新维护配置

```http
PATCH /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}
Authorization: Bearer <admin>
Content-Type: application/json
```

```json
{
  "role": "derived",
  "direction": "higher_better",
  "warning_threshold": 99.0,
  "critical_threshold": 98.0,
  "daily_aggregation": "sum",
  "daily_change_threshold": 0.2,
  "daily_change_threshold_unit": "pp",
  "is_percentage": true,
  "zero_semantics": "unknown",
  "consistency_tolerance": 0.2,
  "object_match_mode": "exact",
  "enabled": true
}
```

规则：

- 至少提交一个字段。
- `role=derived` 必须已有 `kpi_measurement_derived` 配置。
- `object_match_mode` 本期只接受 `exact`。
- `daily_change_threshold >= 0`、`consistency_tolerance >= 0`。
- 方向与阈值写入既有 `KpiMeasurementResource`，扩展字段写入维护配置。
- 同一事务写入审计；任何一步失败全部回滚。
- 成功返回更新后的完整有效配置（200）。

错误码：

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | `kpi_metric_config_empty_update` | 请求体没有可更新字段 |
| 404 | `kpi_metric_config_not_found` | 测量单元/指标/绑定不存在 |
| 409 | `kpi_metric_role_requires_derived` | 设为聚合角色但没有派生定义 |
| 409 | `kpi_metric_object_match_unsupported` | 请求了本期不支持的对象匹配 |
| 422 | `kpi_metric_config_invalid` | 阈值、方向或聚合方式非法 |

## 4. 审计列表

```http
GET /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}/audits?page=1&page_size=20
```

返回：

```json
{
  "total": 1,
  "items": [
    {
      "id": 1,
      "measurement_unit_id": "MU_CALL",
      "metric_resource_id": "ME_RATE",
      "actor": "admin",
      "changed_fields": ["daily_aggregation", "zero_semantics"],
      "before_values": {"daily_aggregation": "latest", "zero_semantics": "unknown"},
      "after_values": {"daily_aggregation": "sum", "zero_semantics": "unknown"},
      "created_at": "2026-11-05T01:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 20
}
```

审计不保存原始指标值、CSV 行、上传包内容或任务现场绝对路径。

## 5. 派生配置读取

```http
GET /api/v5/kpi/measurement-derived?measurement_unit_id=&enabled=&page=1&page_size=20
GET /api/v5/kpi/measurement-derived/{id}
```

返回现有 `KpiMeasurementDerived` 字段，另加 `metric_resource_name_zh`、`numerator_metric_name_zh`、`denominator_metric_name_zh`、`created_at`、`updated_at`。列表按测量单元 ID、指标 ID、id 稳定排序。

## 6. 派生配置更新

```http
PATCH /api/v5/kpi/measurement-derived/{id}
Authorization: Bearer <admin>
Content-Type: application/json
```

```json
{
  "numerator_metric_id": "ME_SUCCESS",
  "denominator_metric_id": "ME_TOTAL",
  "template": "success_rate",
  "enabled": true
}
```

规则：

- 只允许更新已有派生配置；不存在返回 `404 kpi_measurement_derived_not_found`。
- 分子/分母必须在该测量单元已确认启用绑定。
- `metric_resource_id` 和 `measurement_unit_id` 不可修改。
- 变更写维护审计，`changed_fields` 包含派生字段名。
- 唯一键由 `(measurement_unit_id, metric_resource_id)` 保证。

## 7. 兼容性

- 不替换既有 `POST /api/v5/kpi/measurement-derived`；其响应语义保持不变。
- 新列表/详情/更新接口为增量能力。
- 旧消费者继续读取现有资源和派生字段。
