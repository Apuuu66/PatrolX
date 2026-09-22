# 数据模型：指标绑定批量确认

## KpiMeasurementBinding（复用）

| 字段 | 类型 | 本功能行为 |
| --- | --- | --- |
| `id` | `int` 主键 | 批量确认目标；请求重复时只处理一次。 |
| `metric_resource_id` | `str \| None` | 必须非空才能从候选确认为已确认；不修改。 |
| `measurement_unit_id` | `str` | 用于跨测量单元同指标冲突判断；不修改。 |
| `raw_source_name` | `str` | 不修改。 |
| `base_source_name` | `str` | 不修改。 |
| `display_unit` | `str \| None` | 不修改。 |
| `status` | `str` | 仅候选可更新为 `confirmed`；失败项保持原值。 |
| `enabled` | `bool` | 不因批量确认改变。 |
| `task_id` / `source_file` | `str` | 不修改，保留任务来源。 |
| `updated_at` | UTC 时间 | 仅候选成功确认时更新；幂等确认不更新。 |

## 关系

- 绑定通过 `metric_resource_id` 引用 ME 指标资源；本功能不校验或修改资源目录内容。
- 冲突约束是业务约束：同一 ME 指标不能同时确认到不同 `measurement_unit_id`。
- 同一测量单元内多条绑定可指向同一 ME 指标，不被本功能新增约束拒绝。

## 批量结果模型

- `total`：请求去重后的处理数量。
- `succeeded`：`outcome=confirmed` 或 `already_confirmed` 的数量。
- `failed`：`outcome=failed` 的数量。
- `items[]`：每个去重后的绑定 ID 一条结果；不返回重复 ID 的重复结果。
- `outcome`：
  - `confirmed`：本次从候选更新为已确认。
  - `already_confirmed`：请求前已是已确认，数据不变。
  - `failed`：本次被拒绝，数据不变。
- 失败结果携带 `error_code` 和 `message`；成功结果携带确认后的绑定 JSON。

## 状态转移

```text
candidate + metric_resource_id 非空 -> confirmed
confirmed -> already_confirmed（无数据变化）
candidate + metric_resource_id 为空 -> failed
conflict / ignored / 不存在 -> failed
```
