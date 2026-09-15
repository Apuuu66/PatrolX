# KPI 配置契约（部署侧静态配置）

## 目录契约

```text
deploy/config/kpi/
├── common.yaml
├── call.yaml
├── api.yaml
└── media.yaml
```

- 目录中只能出现上述公共文件和已注册领域文件。
- 加载器必须拒绝未知 YAML 文件，避免维护者误新增后静默不生效。
- 本版注册领域固定为 `call`、`api`、`media`。
- `deploy/config/kpi_rules.yaml` 在实现阶段移除；不保留双读兼容。

## common.yaml

```yaml
version: 2
input_timezone: "Asia/Shanghai"
budgets:
  max_file_bytes: 67108864
  max_rows_per_file: 100000
  max_columns_per_file: 256
  max_files_per_domain: 1000
  max_records_per_domain: 200000
```

## 领域文件结构

```yaml
domain: call

metrics:
  - key: call_attempts
    name_zh: 呼叫请求次数
    name_en: Call Attempts
    metric_type: count
    semantic_group: traffic
    display_role: context
    unit: 次
    source_type: raw
    aggregation:
      kind: sum
    aliases:
      - language: zh
        value: 呼叫请求次数

  - key: call_success_rate
    name_zh: 呼叫成功率
    name_en: Call Success Rate
    metric_type: rate
    semantic_group: quality
    display_role: highlight
    unit: "%"
    source_type: derived
    aggregation:
      kind: ratio_from_inputs
    aliases:
      - language: zh
        value: 呼叫成功率
    formula:
      kind: ratio
      numerator: call_success_count
      denominator: call_attempts
      denominator_fallback:
        kind: sum
        inputs:
          - call_success_count
          - call_failure_count
      scale: 100

thresholds:
  call_success_rate:
    label: 呼叫成功率
    direction: min
    unit: "%"
    default: 99.0
    periods:
      "5": 99.0
      "15": 99.0
      "30": 99.0
      "60": 99.0

capacity_metrics:
  统计峰值:
    metric: stat_peak
    semantics: peak
    status: confirmed
```

## 领域配置要求

1. `domain` 必须与文件名和注册领域一致。
2. `metrics[].key` 必须唯一且匹配 `[a-z][a-z0-9_]*`。
3. 每个用于源数据识别的叫法必须登记在对应指标的 `aliases[]`。
4. 归一化后的别名在同一领域内不得冲突。
5. `thresholds` 的 key 必须是已登记指标。
6. `capacity_metrics[].metric` 必须是已登记指标。
7. 派生公式只能引用同领域指标，且依赖图无环。
8. 当前必需兼容指标继续存在：呼叫请求次数、成功次数、失败次数、成功率、失败率；对应必需阈值继续存在。
9. `api.yaml` 和 `media.yaml` 允许指标为空；领域文件仍必须存在且声明正确 `domain`。

## 归一化规则

对参与比较的名称执行：

1. Unicode `NFKC`。
2. 去除首尾空白。
3. 将连续空白折叠为单个空格。
4. `casefold()`。
5. 完全相等才视为同一叫法。

不做模糊匹配、拼音匹配、语义匹配或自动去重。

## 校验错误要求

配置错误必须包含稳定上下文，例如：

- `common.version`
- `call.metrics[].key`
- `call.metrics[key=call_success_rate].formula.denominator`
- `call.aliases[normalized=呼叫成功率]`

规则收到 `KpiConfigError` 后返回 `RuleStatus.ERROR`，`metadata.error` 保留原始错误信息；不得降级为 `skip` 或静默通过。
