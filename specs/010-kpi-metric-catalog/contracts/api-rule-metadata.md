# KPI RuleResult Metadata 契约

## 公共契约原则

- 既有 `/api/v2` 资源路径和字段不删除、不改语义。
- `RuleResultV2.metadata` 继续是开放对象；新增 KPI key 属于兼容新增。
- OpenAPI 必须新增 KPI 元数据 component schema、字段描述和示例，但不得把所有规则通用 `metadata` 收窄为 KPI 专用 schema。
- 前端 API 客户端只通过 `python build.py gen-web-api` 更新；页面内的 KPI 类型可基于生成客户端类型做窄化。

## metadata 根字段

新执行或单规则重跑产生的 KPI 结果：

```json
{
  "version": 2,
  "domain": "call",
  "config_source": "deploy/config/kpi",
  "input_timezone": "Asia/Shanghai",
  "metric_catalog": [],
  "kpi_results": [],
  "unclassified_metrics": [],
  "kpi_files": []
}
```

历史结果保持：

```json
{
  "version": 1,
  "domain": "call",
  "config_source": "deploy/config/kpi_rules.yaml",
  "input_timezone": "Asia/Shanghai",
  "kpi_files": []
}
```

前端以 `version >= 2` 且 `metric_catalog` 存在作为目录式视图条件。

## metric_catalog item

```json
{
  "key": "call_success_rate",
  "name_zh": "呼叫成功率",
  "name_en": "Call Success Rate",
  "aliases": [
    {"language": "zh", "value": "呼叫成功率"}
  ],
  "metric_type": "rate",
  "semantic_group": "quality",
  "display_role": "highlight",
  "unit": "%",
  "source_type": "derived",
  "aggregation": {
    "kind": "ratio_from_inputs"
  },
  "formula": {
    "kind": "ratio",
    "numerator": "call_success_count",
    "denominator": "call_attempts",
    "denominator_fallback": {
      "kind": "sum",
      "inputs": ["call_success_count", "call_failure_count"]
    },
    "scale": 100
  }
}
```

## kpi_result item

```json
{
  "key": "call_success_rate",
  "main_value": 99.58333333333333,
  "value_available": true,
  "unavailable_reason": null,
  "display_status": "pass",
  "unit": "%",
  "aggregation": "ratio_from_inputs",
  "threshold": {
    "key": "call_success_rate",
    "direction": "min",
    "unit": "%",
    "default": 99.0,
    "periods": {"15": 99.0}
  },
  "breach_count": 1,
  "series": [
    {
      "period_minutes": 15,
      "start_at": "2026-09-01T02:00:00Z",
      "end_at": "2026-09-01T02:15:00Z",
      "value": 98.0,
      "status": "fail"
    }
  ],
  "source_files": ["kpi/kpi-call-15.csv"],
  "provenance": {
    "source_type": "derived",
    "formula": "call_success_count / call_attempts * 100",
    "inputs": [
      {"key": "call_success_count", "value": 1195, "aggregation": "sum"},
      {"key": "call_attempts", "value": 1200, "aggregation": "sum"}
    ],
    "missing_inputs": [],
    "direct_cross_reference": [],
    "denominator_zero": false,
    "fallback_used": false
  }
}
```

不可用样例：

```json
{
  "key": "call_success_rate",
  "main_value": null,
  "value_available": false,
  "unavailable_reason": "公式必要输入缺失: call_attempts",
  "display_status": "unavailable",
  "unit": "%",
  "aggregation": "ratio_from_inputs",
  "threshold": null,
  "breach_count": 0,
  "series": [],
  "source_files": [],
  "provenance": {
    "source_type": "derived",
    "formula": "call_success_count / call_attempts * 100",
    "inputs": [],
    "missing_inputs": ["call_attempts"],
    "direct_cross_reference": [
      {"source_name": "呼叫成功率", "source_files": ["kpi/kpi-call-15.csv"], "values": [80.0]}
    ],
    "denominator_zero": false,
    "fallback_used": false
  }
}
```

## unclassified_metrics item

```json
{
  "source_name": "new_vendor_metric",
  "source_files": ["kpi/kpi-api-15.csv"],
  "record_count": 3,
  "sample_values": [1.0, 2.0, 3.0],
  "reason": "metric_not_registered"
}
```

## OpenAPI 更新要求

实现阶段必须：

1. 新增 `KpiMetricCatalogItemV2`、`KpiMetricResultV2`、`KpiProvenanceV2`、`KpiUnclassifiedMetricV2` schema。
2. 在 `RuleResultV2.metadata.description` 中说明 KPI 领域可能携带这些 key。
3. 保持 `additionalProperties: true`，避免影响非 KPI 规则。
4. 同步错误响应、分页约定和示例。
5. 运行 `python build.py contract` 和 `python build.py gen-web-api`。
