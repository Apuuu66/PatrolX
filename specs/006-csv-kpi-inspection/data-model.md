# 阶段 1 数据模型：CSV KPI 离线巡检

## 1. 范围

本文件定义规则内部输入、配置、结果 metadata 和 finding 的数据形状。公共 API 仍使用既有 `RuleResult`、`Metric`、`Finding` 契约，不新增接口字段。

## 2. 原始输入

### KpiCsvFile

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `path` | `str` | 任务内 POSIX 相对路径，如 `kpi/kpi-call-15.csv` |
| `domain` | `"api" \| "media" \| "call"` | 从文件名识别 |
| `period_minutes` | `5 \| 15 \| 30 \| 60` | 从文件名识别 |
| `measurement_set` | `str \| null` | CSV 第 1 行；解析失败时为空 |
| `status` | `"ok" \| "failed"` | 文件级处理状态 |
| `errors` | `KpiError[]` | 文件级与行级错误 |
| `objects` | `str[]` | CSV 第 2 行第 4 列起的原始指标名 |
| `records` | `KpiRecord[]` | 成功解析的数据行 |

### KpiRecord

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `line_number` | `int` | CSV 物理行号，从 1 开始 |
| `period_minutes` | `5 \| 15 \| 30 \| 60` | 来自第 1 列 |
| `start_at` | `datetime` | UTC；ISO 8601 序列化 |
| `end_at` | `datetime` | UTC；ISO 8601 序列化 |
| `values` | `dict[str, float]` | 原始指标名到数值；空值/错误值不写入 |
| `errors` | `KpiError[]` | 行内字段级错误；为空表示该行成功 |
| `derived` | `dict[str, float] \| null` | 呼叫领域派生值；可为空 |
| `capacity_values` | `KpiCapacityValue[] \| null` | 识别出的容量型指标值；无容量列时为空 |

### KpiCapacityValue

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_name` | `str` | CSV 原始指标名，如 `统计峰值` |
| `metric` | `str` | 配置映射后的稳定 key，如 `stat_peak` |
| `value` | `float` | 原始容量值 |
| `status` | `"confirmed" \| "unknown"` | `confirmed` 表示统计口径已配置确认；`unknown` 表示仅展示 |
| `semantics` | `"peak" \| "concurrency" \| "gauge" \| null` | 已确认口径；unknown 时为空 |
| `reason` | `str \| null` | `unknown` 时必须为 `capacity_semantics_unknown` |

### KpiError

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | `str` | 稳定英文错误码，如 `invalid_period` |
| `line_number` | `int \| null` | 文件级错误为空 |
| `column` | `str \| null` | 相关 CSV 列名或字段名 |
| `message` | `str` | 中文用户可读信息 |
| `value` | `str \| float \| null` | 安全展示的原始文本或数值 |

### 呼叫派生字段

当可计算时，`derived` 可包含：

| key | 类型 | 说明 |
| --- | --- | --- |
| `call_success_rate` | `float` | 百分比 |
| `call_failure_rate` | `float` | 百分比 |
| `call_count_difference` | `float` | `请求成功 + 请求失败 - 呼叫请求`，仅三项都存在时输出 |

派生值不是新增公共 API 字段，只保存在规则结果 `metadata`。

## 3. 阈值配置

配置文件：`deploy/config/kpi_rules.yaml`。

```yaml
version: 1
input_timezone: "Asia/Shanghai"
aliases:
  call:
    "呼叫请求": "call_attempts"
    "请求成功": "call_success_count"
    "请求失败": "call_failure_count"
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

### KpiAliasConfig

| 字段 | 约束 |
| --- | --- |
| `aliases.<domain>` | `dict[str, str]`；原始指标名到稳定 key 的映射；稳定 key 只能使用小写英文、数字和下划线 |
| `aliases.call` | 必须包含呼叫请求、请求成功、请求失败、呼叫成功率、呼叫失败率第一版别名 |

### KpiCapacityConfig

| 字段 | 约束 |
| --- | --- |
| `capacity_metrics.<domain>.<source_name>.metric` | 非空稳定 key，且不得与普通别名 key 冲突 |
| `capacity_metrics.<domain>.<source_name>.semantics` | `peak`、`concurrency` 或 `gauge`；`status=confirmed` 时必填 |
| `capacity_metrics.<domain>.<source_name>.status` | `confirmed` 或 `unknown`；`unknown` 表示无法确认统计口径，只展示原始值 |

### KpiBudgetConfig

| 字段 | 类型 | 初始值 |
| --- | --- | --- |
| `max_file_bytes` | 正整数 | `67108864`（64 MiB） |
| `max_rows_per_file` | 正整数 | `100000` |
| `max_columns_per_file` | 正整数 | `256` |
| `max_files_per_domain` | 正整数 | `1000` |
| `max_records_per_domain` | 正整数 | `200000` |

### KpiThreshold

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `label` | `str` | 展示名 |
| `direction` | `"min" \| "max"` | `min` 表示低于阈值越限；`max` 表示高于阈值越限 |
| `unit` | `str` | 第一版成功/失败率均为 `%` |
| `default` | `float` | 周期未显式配置时的默认值 |
| `periods` | `dict[str, float]` | 周期到阈值的映射，key 为字符串 |

### KpiThresholdView

写入结果 evidence / metric threshold 的展开形式：

```json
{
  "metric": "call_success_rate",
  "label": "呼叫成功率",
  "direction": "min",
  "unit": "%",
  "period_minutes": 15,
  "value": 99.0,
  "source": "deploy/config/kpi_rules.yaml"
}
```

## 4. 规则结果 metadata

### 4.1 领域结果通用字段

```json
{
  "version": 1,
  "domain": "api",
  "config_source": "deploy/config/kpi_rules.yaml",
  "input_timezone": "Asia/Shanghai",
  "periods": [15],
  "files": []
}
```

`domain` 取 `api`、`media` 或 `call`。

### 4.2 `metadata.kpi_files[]`

```json
{
  "path": "kpi/kpi-call-15.csv",
  "domain": "call",
  "period_minutes": 15,
  "measurement_set": "呼叫会话统计",
  "status": "ok",
  "objects": [
    "呼叫请求",
    "请求成功",
    "请求失败",
    "统计峰值",
    "最大并发"
  ],
  "record_count": 5,
  "parse_error_count": 0,
  "errors": [],
  "records": [
    {
      "line_number": 3,
      "period_minutes": 15,
      "start_at": "2026-09-14T02:00:00Z",
      "end_at": "2026-09-14T02:15:00Z",
      "values": {
        "呼叫请求": 1200,
        "请求成功": 1170,
        "请求失败": 30,
        "统计峰值": 100,
        "最大并发": 88
      },
      "derived": {
        "call_success_rate": 97.5,
        "call_failure_rate": 2.5,
        "call_count_difference": 0
      },
      "capacity_values": [
        {
          "source_name": "统计峰值",
          "metric": "stat_peak",
          "value": 100,
          "status": "confirmed",
          "semantics": "peak",
          "reason": null
        },
        {
          "source_name": "最大并发",
          "metric": "max_concurrency",
          "value": 88,
          "status": "confirmed",
          "semantics": "concurrency",
          "reason": null
        }
      ],
      "errors": []
    }
  ]
}
```

示例中的 UTC 时间假设 CSV naive 时间为 `Asia/Shanghai`。

### 4.3 metadata 增长控制

- `metadata.kpi_files` 保存全部可追溯记录；如果达到 research 中的记录预算，规则返回失败并说明截断/停止原因。
- HTML/API 序列化后体积显著增长时，前端明细表应分页或按文件折叠；第一版不新增查询接口。

## 5. 固定输出指标

### 5.1 `kpi.api` / `kpi.media`

| key | label | unit | value |
| --- | --- | --- | --- |
| `file_count` | 文件数 | 个 | 尝试处理文件数 |
| `record_count` | 记录数 | 条 | 成功解析数据行数 |
| `metric_count` | 指标列数 | 项 | 所有文件对象数求和 |
| `parse_error_count` | 解析错误数 | 条 | 文件级 + 行级错误数 |

### 5.2 `kpi.call`

| key | label | unit | value |
| --- | --- | --- | --- |
| `file_count` | 文件数 | 个 | 尝试处理文件数 |
| `record_count` | 记录数 | 条 | 成功解析数据行数 |
| `parse_error_count` | 解析错误数 | 条 | 文件级 + 行级错误数 |
| `consistency_error_count` | 自洽异常数 | 条 | 三项呼叫数量不相等的行数 |
| `success_rate_min` | 成功率最小值 | % | 可用成功率最小值或 `"N/A"` |
| `failure_rate_max` | 失败率最大值 | % | 可用失败率最大值或 `"N/A"` |
| `success_breach_count` | 成功率越限行数 | 条 | 低于周期下限的行数 |
| `failure_breach_count` | 失败率越限行数 | 条 | 高于周期上限的行数 |
| `capacity_metric_count` | 容量指标列数 | 项 | 配置映射的容量指标列数，包含 `confirmed` 与 `unknown` 状态 |
| `capacity_unknown_count` | 口径未知容量列数 | 项 | `status=unknown` 的容量指标列数 |

## 6. Finding

| 类型 | finding_id 模板 | severity |
| --- | --- | --- |
| 解析错误 | `kpi.<domain>:parse-error:<path_sha256>:<line_number>` | `MEDIUM` |
| 数据自洽异常 | `kpi.call:consistency:<path_sha256>:<line_number>` | `MEDIUM` |
| 阈值异常 | `kpi.call:threshold:<path_sha256>:<line_number>` | `MEDIUM` |
| 容量口径未知 | `kpi.<domain>:capacity-unknown:<path_sha256>:<line_number>` | `LOW` |

`path_sha256` 使用任务内相对路径的 SHA-256 前 16 位，避免 finding id 暴露完整路径且保持确定性。

## 7. 不新增的模型

- 不新增公共 Pydantic 模型。
- 不新增数据库表；规则结果仍由现有任务/规则持久化机制保存。
- 不新增公共 prepared 数据模型。
- 不为动态 CSV 指标扩展 `outputs_metrics`。
