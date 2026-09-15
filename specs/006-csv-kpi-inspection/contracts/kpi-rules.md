# 契约：KPI 巡检规则

## 规则代码

| code | name | priority |
| --- | --- | --- |
| `kpi.api` | API KPI 巡检 | P1 |
| `kpi.media` | 媒体统计 KPI 巡检 | P1 |
| `kpi.call` | 呼叫 KPI 巡检 | P1 |

```python
# kpi.api
r"^kpi/(?:.*/)?kpi-api-(?:5|15|30|60)\.csv$"

# kpi.media
r"^kpi/(?:.*/)?kpi-media-(?:5|15|30|60)\.csv$"

# kpi.call
r"^kpi/(?:.*/)?kpi-call-(?:5|15|30|60)\.csv$"
```

三条规则均为普通规则、`category=kpi`、`severity=medium`、`rule_version=1.0.0`，注册后由现有执行器调度。规则之间不导入、不调用、不读取彼此结果。

## 输出指标契约

### `kpi.api` / `kpi.media`

```text
file_count, record_count, metric_count, parse_error_count
```

### `kpi.call`

```text
file_count, record_count, parse_error_count, consistency_error_count,
success_rate_min, failure_rate_max, success_breach_count,
failure_breach_count, capacity_metric_count,
capacity_unknown_count
```

`pass` / `warn` / `fail` 结果必须包含上述全部 key，且 unit 与规则声明一致。当无可用比率时，`success_rate_min` / `failure_rate_max` 输出 `"N/A"` 字符串占位；这不构成容量指标的派生成功率或失败率。

## 状态

| 状态 | 条件 |
| --- | --- |
| `skip` | 未匹配本领域 KPI 文件 |
| `fail` | 任一文件/行解析失败、资源预算超限，或呼叫阈值越限 |
| `warn` | 无解析失败且无阈值越限，但存在呼叫数量自洽异常 |
| `pass` | 处理成功且无异常 |
| `error` | 规则执行异常或阈值配置缺失/非法 |

## 呼叫计算

- 成功率：优先使用显式 `呼叫成功率`，否则 `呼叫请求成功次数 / 呼叫请求次数 * 100`。
- 失败率：优先使用显式 `呼叫失败率`，否则 `呼叫请求失败次数 / 呼叫请求次数 * 100`。
- 分母为 0 或缺少字段时，对应比率不可用，不判越限。
- 三项呼叫数量都存在时检查 `呼叫请求成功次数 + 呼叫请求失败次数 == 呼叫请求次数`；不一致计入自洽异常。
- `统计峰值`、`最大并发` 只展示；不构造成功/失败率，不做业务阈值判断。当 CSV 仅包含容量列时，固定 metric 契约仍要求输出全部 key，其中比率字段为 `"N/A"` 占位。

## Finding

- 所有 finding 必须有任务内相对路径 `source_file` 和 `evidence`。
- 解析错误、自洽异常和阈值异常使用确定性 `finding_id`。
- 阈值 finding 必须包含指标、方向、阈值、周期、原始值/派生值和配置来源。
- 同一行成功率和失败率同时越限可合并为一个 finding，但 evidence 必须完整列出两项。
