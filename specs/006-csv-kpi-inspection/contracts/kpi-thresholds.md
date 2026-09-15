# 契约：KPI 规则与阈值配置

## 文件

`deploy/config/kpi_rules.yaml` 是第一版别名、容量口径、阈值和解析预算的唯一来源。规则代码不得硬编码呼叫成功率/失败率阈值。

## Schema

```yaml
version: 1
input_timezone: "Asia/Shanghai"
aliases:
  call:
    "呼叫请求次数": "call_attempts"
    "呼叫请求成功次数": "call_success_count"
    "呼叫请求失败次数": "call_failure_count"
    "呼叫成功率": "call_success_rate"
    "呼叫失败率": "call_failure_rate"
capacity_metrics:
  call:
    "统计峰值":
      metric: "stat_peak"
      semantics: "peak"
      status: "confirmed"
    "最大并发":
      metric: "max_concurrency"
      semantics: "concurrency"
      status: "confirmed"
limits:
  call:
    call_success_rate:
      label: "呼叫成功率"
      direction: "min"
      unit: "%"
      default: 99.0
      periods:
        "5": 99.0
        "15": 99.0
        "30": 99.0
        "60": 99.0
    call_failure_rate:
      label: "呼叫失败率"
      direction: "max"
      unit: "%"
      default: 1.0
budgets:
  max_file_bytes: 67108864
  max_rows_per_file: 100000
  max_columns_per_file: 256
  max_files_per_domain: 1000
  max_records_per_domain: 200000
```

## 字段

| 字段 | 约束 |
| --- | --- |
| `version` | 当前为 `1` |
| `input_timezone` | IANA 时区名；用于无时区 CSV 时间输入 |
| `aliases.<domain>` | 原始指标名到稳定 key 的映射；key 只能使用小写英文、数字和下划线 |
| `capacity_metrics.<domain>.<source_name>.metric` | 容量稳定 key，不得与普通别名 key 冲突 |
| `capacity_metrics.<domain>.<source_name>.semantics` | `peak`、`concurrency` 或 `gauge`；`status=confirmed` 时必填 |
| `capacity_metrics.<domain>.<source_name>.status` | `confirmed` 或 `unknown`；`unknown` 表示只展示，不生成阈值或派生比率 |
| `budgets.max_file_bytes` | 正整数；初始 `67108864` |
| `budgets.max_rows_per_file` | 正整数；初始 `100000` |
| `budgets.max_columns_per_file` | 正整数；初始 `256` |
| `budgets.max_files_per_domain` | 正整数；初始 `1000` |
| `budgets.max_records_per_domain` | 正整数；初始 `200000` |
| `limits.<domain>.<metric>.direction` | `min`：低于阈值越限；`max`：高于阈值越限 |
| `limits.<domain>.<metric>.unit` | 第一版成功/失败率为 `%` |
| `limits.<domain>.<metric>.default` | 数值，周期未显式配置时使用 |
| `limits.<domain>.<metric>.periods` | key 必须为字符串化的 `5/15/30/60` |

## 判定

- 成功率：`value < threshold` 时越限。
- 失败率：`value > threshold` 时越限。
- 缺失周期使用 `default`。
- 缺少指标配置时该指标不判阈值；呼叫第一版的两个受管指标都应存在。
- 配置文件缺失、YAML 非法、必填字段缺失、预算字段缺失或类型非法时，相关规则返回 `error`，不得静默使用内置值。
- 容量指标 `status=unknown` 时仍展示原始值，但不计算成功率、失败率或业务阈值；结果必须输出 `capacity_semantics_unknown`。
- 同一领域内别名 key 与容量 metric key 冲突属于配置错误。

## 配置来源

结果中相关 metric threshold 与 finding evidence 必须记录：

- `source`: `deploy/config/kpi_rules.yaml`
- `metric`
- `direction`
- `period_minutes`
- 实际使用的阈值和单位
