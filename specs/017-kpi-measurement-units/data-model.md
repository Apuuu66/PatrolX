# 数据模型

## KpiMeasurementResource

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| resource_id | string | PK | `MU_*` / `ME_*` / `UNIT_*` |
| kind | string | enum: mu/me/unit | 前缀派生 |
| name_zh | string | required | 中文描述 |
| name_en | string | required | 英文描述 |
| filename_fragment | string / null | required for mu | 英文名空格转 `_` |
| enabled | bool | default true | 仅 MU 参与开关 |
| created_at / updated_at | datetime UTC | required | 审计时间 |

## KpiMeasurementBinding

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | int | PK | 候选绑定 |
| metric_resource_id | string / null | FK-like | `ME_*`；未知列为 null |
| measurement_unit_id | string | FK-like | `MU_*` |
| raw_source_name | string | required | CSV 原始列名 |
| base_source_name | string | required | 去掉尾部单位括号 |
| display_unit | string / null | nullable | 括号内单位 |
| status | string | enum candidate/confirmed/conflict/ignored | 默认 candidate |
| enabled | bool | default true | confirmed + enabled 才巡检 |
| task_id / source_file / line_number | string / int / int | task provenance | 发现来源 |
| created_at / updated_at | datetime UTC | required | 审计时间 |

唯一性：`(measurement_unit_id, raw_source_name)`；一个 `ME` 只允许一个非 ignored 绑定。

## KpiMeasurementDerived

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | int | PK | 派生定义 |
| measurement_unit_id | string | FK-like | 归属 MU |
| metric_resource_id | string | required | 派生指标 ID |
| numerator_metric_id | string | required | 分子 ME |
| denominator_metric_id | string | required | 分母 ME |
| template | string | only success_rate | MVP 固定 |
| enabled | bool | default true | 开关 |

## Task File Discovery

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| source_file | string | 当前任务相对路径 |
| measurement_unit_id | string / null | 唯一归属 |
| filename_period | int / null | 文件名周期 |
| filename_timestamp | string / null | 文件名时间戳 |
| status | enum matched/unmatched/ambiguous/disabled/parse_error | 文件状态 |
| reason | string | 用户可读原因 |
| unknown_columns | list[object] | 未注册指标 |
| binding_candidates | list[object] | 候选绑定 |
| conflicts | list[object] | 绑定冲突 |

## Metric Observation

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| object_key | string | 第一维度列值或 `__all__` |
| metric_resource_id | string | 已确认 ME |
| row_count / valid_count / null_count / parse_error_count / zero_count | int | 覆盖统计 |
| min_value / max_value / avg_value | number / null | 基础统计 |
| read_status | enum ok/missing/null/parse_error | 可读状态 |
| value_pattern | enum normal/all_zero/unknown | 形态提示 |
| source_rows | list[object] | 文件与行号证据 |

状态规则：MU 无 confirmed 绑定为 `skip`；MU 停用为 `skip`；解析失败为 `error`；已确认指标缺失/空值/解析错误为 `fail`；其余 `pass`。
