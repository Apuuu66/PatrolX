# 数据模型：KPI 当前判定与昨日趋势

**功能：** `040-kpi-daily-health`  
**日期：** 2026-11-05

## 1. 枚举

### 当前判定 `CurrentHealthStatus`

| 值 | 含义 | 是否可作为正常 |
| --- | --- | --- |
| `normal` | 数据、方向、阈值和口径完整且满足通过条件 | 是 |
| `warn` | 触发预警阈值 | 否 |
| `fail` | 触发失败阈值 | 否 |
| `pending_config` | 缺少方向、阈值、聚合方式、零值语义或派生公式 | 否 |
| `unable_to_judge` | 无有效数据、读取失败、依赖缺失或对象匹配失败 | 否 |
| `not_applicable` | 分母为零或明确配置为业务未触发 | 否 |

### 较昨日 `TrendHealthStatus`

| 值 | 含义 |
| --- | --- |
| `improved` | 按方向和容差判断为改善 |
| `stable` | 在容差内，或方向中性且未超容差 |
| `worsened` | 按方向和容差判断为恶化 |
| `observe` | 方向中性且变化超过容差，或无法定义相对变化但确实变化 |
| `no_baseline` | 无昨日同对象同周期有效值 |

### 其他枚举

- `MetricRole`: `base` / `derived`
- `DailyAggregation`: `latest` / `mean` / `sum` / `max` / `min`
- `ZeroSemantics`: `unknown` / `expected_zero` / `business_not_triggered`
- `ObjectMatchMode`: `exact`（本期唯一实现）
- `ConfigSource`: `custom` / `default` / `legacy_resource` / `missing`

## 2. SQLite 表

### `kpi_metric_maintenance_configs`（新增）

| 字段 | 类型 | 约束/默认 | 含义 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK autoincrement | 主键 |
| `measurement_unit_id` | VARCHAR(128) | NOT NULL | 测量单元 |
| `metric_resource_id` | VARCHAR(128) | NOT NULL | 指标 |
| `role` | VARCHAR(16) | NOT NULL default `base` | `base`/`derived` |
| `daily_aggregation` | VARCHAR(16) | NOT NULL default `latest` | 基础指标日聚合 |
| `daily_change_threshold` | FLOAT | NULL | 日变化容差；NULL 使用默认 |
| `daily_change_threshold_unit` | VARCHAR(16) | NOT NULL default `auto` | `pp`/`relative`/`auto` |
| `is_percentage` | BOOLEAN | NOT NULL default false | 百分比语义 |
| `zero_semantics` | VARCHAR(32) | NOT NULL default `unknown` | 全零处理 |
| `consistency_tolerance` | FLOAT | NOT NULL default 0.2 | 原始成功率一致性容差（pp） |
| `object_match_mode` | VARCHAR(16) | NOT NULL default `exact` | 对象匹配口径 |
| `enabled` | BOOLEAN | NOT NULL default true | 配置启用 |
| `created_at` | DATETIME | NOT NULL | UTC |
| `updated_at` | DATETIME | NOT NULL | UTC |

**唯一约束：** `(measurement_unit_id, metric_resource_id)`。

### `kpi_metric_maintenance_audits`（新增）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | INTEGER PK | 审计序号 |
| `config_id` | INTEGER NULL | 配置 ID；纯资源阈值修改时可为 NULL |
| `measurement_unit_id` | VARCHAR(128) | 测量单元 |
| `metric_resource_id` | VARCHAR(128) | 指标 |
| `actor` | VARCHAR(128) | 认证用户名；系统迁移用 `system` |
| `changed_fields` | JSON | 变更字段名列表 |
| `before_values` | JSON | 变更前有效配置摘要 |
| `after_values` | JSON | 变更后有效配置摘要 |
| `created_at` | DATETIME | UTC |

### `kpi_measurement_derived`（已有，迁移）

新增唯一索引 `ux_kpi_measurement_derived_unit_metric (measurement_unit_id, metric_resource_id)`。

迁移步骤：

1. 读取重复键按 `(measurement_unit_id, metric_resource_id)` 分组。
2. 每组保留 `updated_at DESC, id DESC` 的最新行。
3. 合并保留行：若存在 `enabled=true` 的行，保留行为启用；否则保留最新行。
4. 删除其余行。
5. `CREATE UNIQUE INDEX IF NOT EXISTS`。

**安全边界：** 迁移只删除派生配置重复定义，不删资源、绑定、任务结果或 KPI 点；执行前后记录数量和保留 ID。

## 3. `metadata.daily_health`（规则结果新增字段）

```json
{
  "schema_version": 1,
  "timezone": "Asia/Shanghai",
  "data_date": "2026-11-01",
  "previous_date": "2026-10-31",
  "latest_measured_at": "2026-11-01T23:45:00+08:00",
  "legacy_fallback": null,
  "current_counts": {
    "normal": 1,
    "warn": 0,
    "fail": 0,
    "pending_config": 70,
    "unable_to_judge": 4,
    "not_applicable": 2
  },
  "trend_counts": {
    "improved": 0,
    "stable": 1,
    "worsened": 0,
    "observe": 0,
    "no_baseline": 76
  },
  "scope": {
    "enabled_measurement_unit_count": 4,
    "confirmed_binding_metric_count": 75,
    "expected_metric_count": 77,
    "out_of_scope_file_count": 12,
    "unconfirmed_binding_count": 2,
    "out_of_scope_reason_counts": {"disabled_unit": 10, "unconfirmed_binding": 2}
  },
  "metrics": [
    {
      "measurement_unit_id": "MU_EXAMPLE",
      "measurement_unit_name_zh": "示例测量单元",
      "measurement_unit_enabled": true,
      "metric_resource_id": "ME_EXAMPLE",
      "metric_resource_name_zh": "示例指标",
      "metric_resource_enabled": true,
      "binding_confirmed": true,
      "role": "base",
      "importance": "P1",
      "direction": "higher_better",
      "display_unit": "%",
      "is_percentage": true,
      "current_status": "normal",
      "current_reason": "阈值满足",
      "today_value": 99.1,
      "today_display": "99.1%",
      "yesterday_value": 98.8,
      "yesterday_display": "98.8%",
      "delta": 0.3,
      "delta_display": "+0.3pp",
      "trend_status": "improved",
      "trend_reason": "高于昨日 0.3pp，超过默认 0.2pp",
      "current_threshold": {
        "direction": "higher_better",
        "warning_threshold": 99.0,
        "critical_threshold": 98.0,
        "source": "legacy_resource"
      },
      "change_threshold": {
        "value": 0.2,
        "unit": "pp",
        "source": "default"
      },
      "daily_aggregation": "mean",
      "aggregation_source": "custom",
      "zero_semantics": "unknown",
      "consistency": {
        "status": "not_checked",
        "tolerance_pp": 0.2,
        "difference_pp": null
      },
      "objects": [
        {
          "object_key": "pod-a",
          "period_minutes": 15,
          "current_status": "normal",
          "today_value": 99.1,
          "yesterday_value": 98.8,
          "trend_status": "improved",
          "numerator": null,
          "denominator": null,
          "valid_count": 96,
          "first_measured_at": "2026-11-01T00:00:00+08:00",
          "last_measured_at": "2026-11-01T23:45:00+08:00",
          "source_files": ["example.csv"],
          "reason": "阈值满足"
        }
      ]
    }
  ]
}
```

**首屏边界：** `metrics[].objects` 不再携带全量 7 日点；如果实现阶段为 UI 便利保留对象摘要，则每个对象/周期只保留当前/昨日证据。7 日点由详情接口返回。

**旧任务：** 没有上述对象时保留 `legacy_fallback: {code, message}`；不补造状态。

## 4. 单指标详情响应

```json
{
  "task_id": "task-example",
  "rule_code": "kpi.measurement_units",
  "measurement_unit_id": "MU_EXAMPLE",
  "metric_resource_id": "ME_EXAMPLE",
  "metric": {
    "name_zh": "示例成功率",
    "role": "derived",
    "data_date": "2026-11-01",
    "previous_date": "2026-10-31",
    "daily_aggregation": "formula",
    "formula": "numerator_sum / denominator_sum * 100",
    "current_status": "warn",
    "trend_status": "worsened",
    "current_threshold": {
      "direction": "higher_better",
      "warning_threshold": 99.0,
      "critical_threshold": 98.0,
      "source": "legacy_resource"
    },
    "change_threshold": {"value": 0.2, "unit": "pp", "source": "default"},
    "consistency": {
      "status": "within_tolerance",
      "tolerance_pp": 0.2,
      "difference_pp": 0.03
    }
  },
  "groups": [
    {
      "object_key": "pod-a",
      "period_minutes": 15,
      "today": {
        "value": 98.2,
        "numerator": 982,
        "denominator": 1000,
        "valid_count": 96,
        "first_measured_at": "2026-11-01T00:00:00+08:00",
        "last_measured_at": "2026-11-01T23:45:00+08:00"
      },
      "yesterday": {
        "value": 99.4,
        "numerator": 994,
        "denominator": 1000,
        "valid_count": 96
      },
      "current_status": "warn",
      "trend_status": "worsened",
      "evidence": {"source_files": ["example.csv"], "reason": "低于昨日 1.2pp"}
    }
  ],
  "seven_day_trend": [
    {"date": "2026-10-26", "value": 99.2, "numerator": 992, "denominator": 1000, "status": "ok"},
    {"date": "2026-10-27", "value": null, "numerator": null, "denominator": null, "status": "no_data"}
  ],
  "legacy_fallback": null
}
```

## 5. 维护配置响应/请求

### 响应

```json
{
  "measurement_unit_id": "MU_EXAMPLE",
  "metric_resource_id": "ME_EXAMPLE",
  "name_zh": "示例指标",
  "role": "base",
  "direction": "higher_better",
  "warning_threshold": 99.0,
  "critical_threshold": 98.0,
  "daily_aggregation": "mean",
  "daily_change_threshold": 0.2,
  "daily_change_threshold_unit": "pp",
  "is_percentage": true,
  "zero_semantics": "expected_zero",
  "consistency_tolerance": 0.2,
  "object_match_mode": "exact",
  "enabled": true,
  "config_source": "custom",
  "updated_at": "2026-11-05T01:00:00Z"
}
```

### PATCH 请求

所有字段可选；至少一个字段。`role=derived` 必须已有独立 `measurement-derived` 定义。对象匹配本期只允许 `exact`。`daily_change_threshold >= 0`，`consistency_tolerance >= 0`。

## 6. 状态与配置有效性

| 输入情况 | 当前判定 | 原因码 |
| --- | --- | --- |
| 无有效今日数据 | `unable_to_judge` | `no_current_data` |
| 解析错误/不可读 | `unable_to_judge` | `data_unreadable` |
| 派生依赖缺失 | `unable_to_judge` | `dependency_missing` |
| 分子/分母对象周期无法对应 | `unable_to_judge` | `object_period_mismatch` |
| 分母为 0 | `not_applicable` | `zero_denominator` |
| 全零且语义未知 | `pending_config` | `all_zero_unconfirmed` |
| 无方向 | `pending_config` | `direction_missing` |
| 无阈值 | `pending_config` | `threshold_missing` |
| 聚合方式缺失（不可用） | `pending_config` | `aggregation_missing` |
| 原始成功率超容差 | `pending_config` 或 `warn` | `consistency_exceeded` |
| 触发预警/失败阈值 | `warn` / `fail` | `warning_threshold` / `critical_threshold` |
| 全部有效组满足阈值 | `normal` | `threshold_satisfied` |

## 7. 查询与性能边界

- 首屏：只读 `metadata.daily_health`，最多 77 指标行。
- 详情：最多 7 个自然日 × 该指标对象周期数；只查单任务/单测量单元/单指标/依赖指标。
- 维护配置列表：分页，默认 20、最大 200。
- 审计列表：按配置分页，默认 20、最大 200。
- 所有时间字段为 UTC（`*_at`）或显式日期（`data_date`、`previous_date`）；展示时转换为 UTC+8。
