# 任务 KPI 配置快照 API 契约

## 文件契约

路径：`output/<task_id>/kpi/kpi_catalog_snapshot.json`

```json
{
  "schema_version": 1,
  "base_data_version": "sha256:...",
  "classification_version": 12,
  "captured_at": "2026-09-19T01:02:03Z",
  "metrics": [
    {
      "key": "me_21003",
      "resource_id": "ME_21003",
      "name_zh": "呼叫成功率",
      "name_en": "Call Success Rate",
      "domain": "call",
      "rule": {
        "metric_type": "rate",
        "semantic_group": "quality",
        "display_role": "highlight",
        "unit": "%",
        "source_type": "derived",
        "aggregation": {"kind": "ratio_from_inputs"},
        "formula": {"kind": "ratio", "numerator": "me_21002", "denominator": "me_21001", "scale": 100}
      }
    }
  ],
  "rules": {
    "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 2000, "max_records": 500000}},
    "thresholds": [],
    "capacity_rules": [],
    "display_rules": []
  }
}
```

约束：

- `captured_at` 为 UTC ISO-8601。
- `metrics` 是任务执行时的完整有效指标快照，不是只包含当前领域的子集。
- `rules` 是 Git JSON 中完整规则定义快照，可包含其他领域规则。
- 快照文件不会随后续 Git 或数据库变更重写。

## GET /api/v3/tasks/{task_id}/kpi/catalog-snapshot

### Response 200

返回上述快照 JSON，`Content-Type: application/json`。

### Error

| 状态 | 场景 |
| --- | --- |
| 404 | 任务不存在 |
| 409 | 任务存在但快照缺失 |
| 500 | 快照损坏或 JSON 校验失败 |

该接口只读取任务现场，不触发重新加载当前 Git 或数据库状态。
