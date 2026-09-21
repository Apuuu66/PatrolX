# API 契约草案：在线派生指标

本文件是 plan 阶段的契约草案；实现前必须同步写入唯一契约源 `docs/api/openapi.yaml`，并运行契约生成。以下均为 `/api/v4` 新增资源，不修改既有字段含义。

## 通用

- 安全：`BearerAuth` + `require_role("admin")`。
- 操作人：服务端取认证会话 username；请求体不携带 `operator`。
- 错误：统一 `ErrorV2`，错误码覆盖 key 冲突、输入未登记/未分类/跨域、公式非法、引用保护和数据库不可用。

## Paths

### `GET /api/v4/kpi/config/derived-metrics`

- Query：`search`、`domain`、`enabled`、`page`、`page_size`。
- Response 200：`KpiDerivedMetricPageV4`。

### `POST /api/v4/kpi/config/derived-metrics`

- Request：`KpiDerivedMetricCreateRequestV4`。
- Response：`202` + `Location: /api/v4/kpi/config/derived-metrics/{metric_key}`，body 为 `KpiDerivedMetricV4`。
- 400：公式或输入非法；409：key 重复或基础资源冲突。

### `GET /api/v4/kpi/config/derived-metrics/{metric_key}`

- Response 200：`KpiDerivedMetricV4`；404：不存在。

### `PUT /api/v4/kpi/config/derived-metrics/{metric_key}`

- Request：`KpiDerivedMetricUpdateRequestV4`。
- Response 200：`KpiDerivedMetricV4`。
- 400：校验失败；404：不存在；409：配置冲突。

### `DELETE /api/v4/kpi/config/derived-metrics/{metric_key}`

- Response 200：`KpiConfigDeleteResultV4`，`entity_type=derived_metric`。
- 404：不存在；409：被阈值、容量规则或展示规则引用。

## Schemas

### `KpiDerivedMetricCreateRequestV4`

Required：`metric_key`, `name_zh`, `name_en`, `domain`, `metric_type`, `semantic_group`, `display_role`, `unit`, `enabled`, `formula`。

```text
metric_key: string
name_zh: string
name_en: string
domain: KpiRegisteredDomainV4
metric_type: KpiMetricTypeV4
semantic_group: KpiSemanticGroupV4
display_role: KpiDisplayRoleV4
unit: string
description: string | null
enabled: boolean
formula: KpiDerivedFormulaRequestV4
```

### `KpiDerivedMetricUpdateRequestV4`

与 create 相同，但不含 `metric_key`。

### `KpiDerivedFormulaRequestV4`

Required：`kind`, `numerator`, `denominator`, `scale`。

```text
kind: ratio | inverse_ratio
numerator: string
denominator: string
denominator_fallback_inputs: string[]
scale: number
```

### `KpiDerivedMetricV4`

Required：`metric_key`, `name_zh`, `name_en`, `domain`, `metric_type`, `semantic_group`, `display_role`, `unit`, `enabled`, `formula`, `updated_at`, `rule_config_version`。

### `KpiDerivedMetricPageV4`

Required：`items`, `total`, `page`, `page_size`, `rule_config_version`。

## 既有契约扩展

- `KpiConfigEntityTypeV4` 增加 `derived_metric`。
- `KpiTaskCatalogSnapshotV3.schema_version` 增加 `3`，对象新增可选 `derived_metrics` 数组。
- KPI 指标定义的 `formula` 仍为对象；其 `kind` 新增值 `inverse_ratio`。
- 不改变 `KpiFormulaRequestV4` 的既有 `ratio`-only 语义；反向比率使用新的派生指标请求 schema。
