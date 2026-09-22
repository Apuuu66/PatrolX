# KPI 原始记录查询契约

## 目标

为详情抽屉提供按需、分页、可过滤的 KPI 原始记录查询，同时保持既有规则结果接口默认行为不变。

## 兼容性扩展

### 既有规则结果接口

```http
GET /api/v2/tasks/{task_id}/rules/{rule_code}?exclude_records=true
```

- `exclude_records` 是可选 boolean query 参数。
- 默认 `false`，响应结构与现在一致。
- `true` 时，若规则结果为 KPI 元数据，`metadata.kpi_files[].records` 投影为空数组；文件摘要、错误汇总和目录保留。
- 旧结果也支持该参数；无法识别的 metadata 保持原样。
- OpenAPI 必须同步新增该参数。

## 新增记录查询端点

```http
GET /api/v2/tasks/{task_id}/rules/{rule_code}/kpi/records
```

### Query Parameters

| 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `metric_key` | string | 否 | 稳定指标 key。 |
| `source_file` | string | 否 | 任务内相对路径。 |
| `period_minutes` | integer | 否 | `5/15/30/60`。 |
| `status` | string | 否 | `pass`、`warn`、`fail`、`neutral`、`unavailable`。 |
| `page` | integer | 否 | 默认 `1`，最小 `1`。 |
| `page_size` | integer | 否 | 默认 `10`，最小 `1`，最大 `200`。 |

### 响应

```json
{
  "total": 120,
  "page": 1,
  "page_size": 10,
  "items": [
    {
      "metric_key": "call_success_rate",
      "metric_name_zh": "呼叫成功率",
      "source_file": "kpi/kpi-call-15.csv",
      "line_number": 4,
      "period_minutes": 15,
      "start_at": "2026-09-01T02:00:00Z",
      "end_at": "2026-09-01T02:15:00Z",
      "value": 98.0,
      "status": "fail",
      "errors": []
    }
  ]
}
```

### 错误

- `404 task_not_found`
- `404 rule_result_not_found`
- `400 invalid_query`
- 非 KPI 或旧 metadata 缺少可查询记录时，`items=[]`、`total=0`，不返回错误。

## 查询语义

1. 服务层从 `output/<task_id>/rules/<rule_code>.json` 读取规则结果。
2. 使用 `metadata.version >= 2` 的目录和结果状态解释记录。
3. 每条记录按登记指标展开；一个记录周期包含多个指标时产生多行。
4. `metric_key` 精确匹配稳定 key。
5. `source_file` 精确匹配任务内相对路径。
6. `period_minutes` 精确匹配。
7. `status` 匹配记录级阈值状态或不可用状态。
8. 排序：`source_file` 升序 → `line_number` 升序 → `metric_key` 升序。
9. 分页在过滤和排序后执行。

## 契约更新

实现前必须同步 `docs/api/openapi.yaml`：

- `getRuleResultV2` 增加 `exclude_records`。
- 新增 `listKpiRecordsV2` operationId。
- 新增 `KpiRecordPageV2`、`KpiRecordItemV2` schema。
- 错误响应复用统一 `{code,message,detail}`。
