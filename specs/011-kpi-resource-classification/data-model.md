# 数据模型：KPI 资源全集登记与在线分类

## 资源指标库文件

路径：`deploy/config/kpi/resource_metrics.yaml`

```yaml
version: 1
revision: 3
updated_at: "2026-09-18T02:00:00Z"
metrics:
  me_21002:
    key: me_21002
    resource_id: ME_21002
    name_zh: 创建媒体资源请求次数
    name_en: Create Media Resource Request Count
    metric_type: count
    semantic_group: traffic
    display_role: context
    unit: 次
    source_type: raw
    aggregation:
      kind: sum
    domain: null
    imported_at: "2026-09-18T01:00:00Z"
    updated_at: "2026-09-18T02:00:00Z"
```

字段规则：

- `key`：全局唯一，小写资源 ID，必须满足现有 KPI metric key 正则。
- `resource_id`：保留资源系统原始大小写。
- `name_zh`：去除结尾单位括号后的中文名，非空。
- `name_en`：非空；占位或缺失时保存 `TODO: <中文指标名>`。
- `metric_type`：`count`、`rate`、`capacity`、`latency`、`gauge` 之一。
- `semantic_group`：`traffic`、`quality`、`latency`、`capacity`、`other` 之一。
- `display_role`：首版固定为 `context`。
- `source_type`：首版固定为 `raw`。
- `aggregation`：由基础指标类型推导，不包含公式。
- `domain`：`null`、`call`、`api` 或 `media`。
- `imported_at` / `updated_at`：UTC 时间，使用 `*_at` 命名。
- `revision`：每次成功导入或分类后递增，用于并发冲突检测。

## 分类请求

```json
{
  "metric_keys": ["me_21002", "me_21003"],
  "domain": "media",
  "expected_revision": 3
}
```

规则：

- `metric_keys` 不能为空，重复项只处理一次。
- `domain` 只能是 `call`、`api` 或 `media`。
- `expected_revision` 必填且必须等于当前资源库 revision，否则返回 409。
- 所有 key 必须已登记且未被公式/阈值引用冲突；否则整批失败。

## 导入报告

```json
{
  "revision": 3,
  "summary": {
    "row_count": 100,
    "new_metrics": 12,
    "updated_metrics": 5,
    "skipped_units": 2,
    "skipped_rows": 1,
    "invalid_rows": 1,
    "missing_registered": 0
  },
  "invalid_rows": [
    {"line_number": 12, "resource_id": "X_1", "reason": "unsupported_resource_id"}
  ]
}
```

规则：

- `new_metrics` + `updated_metrics` 之和为本次成功登记的 `ME_` 行数。
- `UNIT_` 行计入 `skipped_units`，不生成指标。
- `missing_registered` 表示本次 CSV 未出现但资源库中已存在的指标数量；这些指标不会被删除。
- 导入成功后返回资源库列表的最新分页或 revision，前端据此刷新。

## 域配置同步

- 未分类指标首次分类时，在目标域 `metrics` 列表追加一个可运行定义。
- 重新分类且无引用时，从旧域移除同一 key，并写入目标域。
- 公式的 numerator、denominator、`denominator_fallback_inputs` 引用某 key 时，禁止该 key 换域。
- `thresholds` 的 `metric` 引用某 key 时，禁止该 key 换域。
- 容量声明引用某 key 时，禁止该 key 换域。
- 同步失败时，资源和目标/来源域配置必须回滚到分类前内容。

## 审计文件

路径：`deploy/config/kpi/resource_metrics_audit.jsonl`

每行一个 JSON 对象：

```json
{
  "operated_at": "2026-09-18T02:00:00Z",
  "operation": "classification",
  "domain": "media",
  "metric_keys": ["me_21002"],
  "result": "success",
  "revision": 3
}
```

导入审计使用 `operation: "import"`，可包含 summary；失败操作也保留结果，便于排查但不包含 CSV 原始内容。
