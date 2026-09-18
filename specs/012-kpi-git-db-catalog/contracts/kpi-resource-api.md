# KPI 资源 API v3 契约

## GET /api/v3/kpi/resource-metrics

查询基础指标与当前分类状态。

### Query

| 名称 | 类型 | 约束 |
| --- | --- | --- |
| `search` | string | 可选，模糊匹配资源 ID、中文名、英文名 |
| `domain` | string | 可选：`unclassified`、`call`、`api`、`media` |
| `include_missing` | boolean | 可选，默认 `false`；为 true 时包含数据库中基础数据已移除的失效记录 |
| `page` | integer | `>=1`，默认 `1` |
| `page_size` | integer | `1..200`，默认 `20` |

### Response 200

```json
{
  "items": [
    {
      "key": "me_21002",
      "resource_id": "ME_21002",
      "name_zh": "创建媒体资源请求次数",
      "name_en": "Create Media Resource Request Count",
      "domain": "unclassified",
      "missing_from_base": false,
      "created_at": "2026-09-19T01:02:03Z",
      "updated_at": "2026-09-19T01:02:03Z"
    }
  ],
  "total": 1000,
  "page": 1,
  "page_size": 20,
  "base_data_version": "sha256:...",
  "classification_version": 12,
  "summary": {
    "unclassified": 900,
    "call": 40,
    "api": 50,
    "media": 10
  }
}
```

`summary` 只统计基础数据中存在的指标。`missing_from_base=true` 的失效分类记录不进入默认列表和 summary。

## PUT /api/v3/kpi/resource-metrics/classification

单批原子分类。

### Request

```json
{
  "metric_keys": ["me_21002", "me_21003"],
  "domain": "call",
  "operator": "alice"
}
```

- `metric_keys`：1..100 个唯一稳定 key。
- `domain`：`call`、`api`、`media` 或 `unclassified`。
- `operator`：非空字符串。
- 不包含 `expected_revision`；成功请求按完成顺序最后写入生效。

### Response 200

```json
{
  "classification_version": 13,
  "domain": "call",
  "metric_keys": ["me_21002", "me_21003"],
  "audited_count": 2
}
```

### Error

| 状态 | 场景 |
| --- | --- |
| 400 | 请求字段非法、重复 metric key、目标域非法、数据库不可用 |
| 404 | 任一 metric key 不在基础数据中 |
| 409 | 已分类且被公式、阈值或容量规则引用的指标试图换域或改回未分类 |
| 500 | 数据库写入或 Git 目录校验失败 |

任一指标校验或保存失败时整批回滚，不产生部分分类，也不产生部分审计。

## GET /api/v3/kpi/resource-metrics/classification-audits

查询分类审计记录。

### Query

| 名称 | 类型 | 约束 |
| --- | --- | --- |
| `metric_key` | string | 可选 |
| `operator` | string | 可选 |
| `domain` | string | 可选：`unclassified`、`call`、`api`、`media` |
| `page` | integer | `>=1`，默认 `1` |
| `page_size` | integer | `1..200`，默认 `20` |

### Response 200

```json
{
  "items": [
    {
      "id": 1,
      "metric_key": "me_21002",
      "operation": "classify",
      "operator": "alice",
      "from_domain": "unclassified",
      "to_domain": "call",
      "result": "success",
      "operated_at": "2026-09-19T01:02:03Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20
}
```

`from_domain` 为 `unclassified` 表示数据库历史状态中的空值。列表按 `operated_at` 倒序；同秒时按主键倒序。本地 CLI 审计的 `operator` 固定为 `cli`。

## 退役契约

以下 `/api/v2` 接口删除，不保留兼容层：

- `GET /api/v2/kpi/resource-metrics`
- `POST /api/v2/kpi/resource-metrics`
- `PUT /api/v2/kpi/resource-metrics/classification`

在线系统不提供资源 CSV 导入；资源 CSV 只能通过离线生成器转为 Git JSON。
