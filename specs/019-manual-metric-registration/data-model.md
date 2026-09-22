# 数据模型：人工注册指标

## KpiMeasurementResource（复用）

| 字段 | 类型 | 本功能行为 |
| --- | --- | --- |
| `resource_id` | `str` 主键，最大 128 | 人工资源由系统生成：`ME__MANUAL_` + 唯一后缀；不可修改。 |
| `kind` | `str` | 人工注册只创建 `me`。 |
| `name_zh` | `str`，最大 256 | 必填；同类 ME 资源内唯一。 |
| `name_en` | `str`，最大 256 | 可为空字符串；后续可编辑。 |
| `filename_fragment` | `str \| None` | 人工注册不设置；不可编辑。 |
| `enabled` | `bool` | 默认启用；可编辑。 |
| `created_at` / `updated_at` | UTC 时间 | 创建/更新时维护。 |

## KpiMeasurementBinding（复用）

| 字段 | 类型 | 本功能行为 |
| --- | --- | --- |
| `id` | `int` 主键 | 注册入口的目标绑定。 |
| `metric_resource_id` | `str \| None` | 注册成功后从空变为新人工 ME ID 或用户选择的既有 ME ID。 |
| `measurement_unit_id` | `str` | 不修改。 |
| `raw_source_name` | `str` | 不修改；用于展示原始列名。 |
| `base_source_name` | `str` | 不修改；用于注册表单预填中文名。 |
| `display_unit` | `str \| None` | 不修改；用于注册表单预填展示单位。 |
| `status` | `str` | 注册/改绑后保持 `candidate`。 |
| `enabled` | `bool` | 不因注册自动变化。 |
| `task_id` / `source_file` | `str` | 保留来源追溯信息，不修改。 |

## 关系

- 一个未注册绑定最多关联一个 ME 资源：`binding.metric_resource_id -> resource.resource_id`。
- 一个 ME 资源可被多个任务或测量单元的绑定引用。
- 人工注册只更新当前绑定；相同原始列名在其他任务中的绑定不批量更新。

## 状态规则

- 资源创建：`kind=me`，`resource_id` 唯一，`name_zh` 同类唯一。
- 资源编辑：只允许 `ME__MANUAL_` 前缀；中文名冲突拒绝。
- 绑定注册：目标绑定必须缺 `metric_resource_id`，成功后状态仍为 `candidate`。
- 绑定巡检：只有人工确认且启用的绑定参与现有 KPI 巡检。
