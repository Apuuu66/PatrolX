# 阶段 0 研究：CSV KPI 离线巡检

## 1. 决策总览

| 主题 | 决策 | 理由 |
| --- | --- | --- |
| 规则粒度 | 新增 `kpi.api`、`kpi.media`、`kpi.call` 三条普通规则 | 三个领域独立执行、重跑和失败隔离 |
| 旧规则 | 下线 `kpi.threshold` | 其“metric,value”两列假设与两行表头/多列 KPI CSV 冲突，保留会重复巡检同一目录 |
| 共享能力 | 新增 `app/inspectors/kpi/common.py` 纯函数 helper | 避免复制解析逻辑；不新增公共 prepared 数据 |
| prepare | 第一版不使用私有 prepare | 数据量可控；直接解析避免缓存只校验 owner 文件 SHA 而漏检共享 helper/config 变化 |
| 阈值 | 新增 `deploy/config/kpi_rules.yaml` | 按领域、指标、周期维护阈值，不在核心调度器或规则代码内硬编码业务阈值 |
| API 契约 | 不修改 OpenAPI 和 Pydantic 公共字段 | 既有 `RuleResult.metadata` 和 `Metric.series` 可承载扩展明细 |
| 输入时区 | 默认 `Asia/Shanghai`，可在 `kpi_rules.yaml` 配置 | 样例使用中文测量名且无时区；naive 时间按配置时区转 UTC；带偏移/Z 的时间按原值转换 |
| 时间字段 | 内部与持久化结果使用 `start_at` / `end_at`，UTC | 遵守项目 UTC 与 `*_at` 命名约束 |
| 状态 | 无匹配文件 `skip`；解析失败或阈值越限 `fail`；仅数据自洽异常 `warn`；正常 `pass` | 明确区分“没有数据”“坏数据”“业务越限”和“数据自洽问题” |
| 明细展示 | `metadata.kpi_files` 保存文件/行级摘要与记录；前端规则详情可展示明细 | 不破坏公共契约，可满足容量指标展示和证据追溯 |

## 2. 文件识别与匹配

文件名模板固定为：

```text
kpi-<domain>-<period>.csv
```

有效取值：

- `domain`: `api`、`media`、`call`
- `period`: `5`、`15`、`30`、`60`

规则只匹配解压后 `kpi/` 分类目录内的命名文件，允许嵌套子包带来的中间目录：

```python
r"^kpi/(?:.*/)?kpi-api-(?:5|15|30|60)\.csv$"
r"^kpi/(?:.*/)?kpi-media-(?:5|15|30|60)\.csv$"
r"^kpi/(?:.*/)?kpi-call-(?:5|15|30|60)\.csv$"
```

执行器已通过 `re.fullmatch()` 匹配 POSIX 相对路径，并排除 `.main/` 与 prepared 目录。文件名大小写第一版按模板小写处理；未匹配到的其他 KPI 文件不进入这三条规则。

## 3. 分类优先级

`deploy/config/classify_rules.yaml` 中 `kpi.patterns` 已包含 `*kpi*`。`app/core/classify.py` 先按 `RuleCategory` 枚举顺序尝试名称模式：`log` 不命中后 `kpi` 会先于 `traffic` 命中，因此 `kpi-call-15.csv` 会进入 `kpi/`，不会被 `*call*` 的 traffic 模式抢占。

不修改分类配置，但需要增加测试证明：

- 根包内 `kpi/kpi-call-15.csv` 分类为 KPI；
- 嵌套包展开后的路径仍能被 `kpi.call` 匹配。

## 4. CSV 结构解析

### 4.1 布局

- 第 1 行：单列或首列文本，去除空白后作为 `measurement_set`；空值视为文件级错误。
- 第 2 行：表头/测量对象行，前 3 列固定为 `测量周期`、`开始时间`、`结束时间`，第 4 列起为指标名；至少 4 列才可处理。
- 第 3 行起：数据行。允许跳过空行；非空数据行的列数必须等于表头列数。
- CSV 使用 UTF-8 读取；解码失败按文件级错误处理，不使用 `errors="replace"` 静默继续。

### 4.2 数据字段

| CSV 列 | 内部字段 | 校验 |
| --- | --- | --- |
| 第 1 列 | `period_minutes` | 必须为整数且属于 `{5,15,30,60}`；必须等于文件名周期 |
| 第 2 列 | `start_at` | 可解析日期时间；naive 时间按配置输入时区转 UTC |
| 第 3 列 | `end_at` | 可解析日期时间；必须等于 `start_at + period` |
| 第 4 列起 | `values[measurement_object]` | 数值可解析；指标名不重复；列数与表头一致 |

数值保留为 `float`；整数值在证据中可按原始文本展示，避免丢失来源形态。指标值为空或不可解析时记录行级错误，不产生该指标值。

### 4.3 错误定位

每个错误至少包含：

- 相对路径 `path`
- CSV 行号 `line_number`
- 错误码 `error_code`
- 面向用户的中文 `message`
- 安全的原始片段/字段名；不包含敏感文件绝对路径或原始包路径

错误码建议：

- `missing_measurement_set`
- `missing_object_row`
- `invalid_period`
- `period_mismatch`
- `invalid_time`
- `time_range_mismatch`
- `column_count_mismatch`
- `invalid_value`
- `duplicate_object`
- `resource_limit_exceeded`

## 5. 指标名与稳定标识

公共契约 `outputs_metrics` 只使用固定 key，动态 CSV 指标不直接生成动态顶层 metric key。原始指标名保存在记录 `values` 和明细 `objects` 中。

呼叫领域建议映射：

| CSV 测量对象 | 稳定 key |
| --- | --- |
| 呼叫请求 | `call_attempts` |
| 请求成功 | `call_success_count` |
| 请求失败 | `call_failure_count` |
| 呼叫成功率 | `call_success_rate` |
| 呼叫失败率 | `call_failure_rate` |
| 统计峰值 | `stat_peak` |
| 最大并发 | `max_concurrency` |

映射写入 `deploy/config/kpi_rules.yaml`，避免规则源码散落别名。未映射的呼叫容量列仍按原始名展示；第一版只有映射为成功率/失败率的指标参与阈值。

API 和媒体领域第一版无固定业务指标假设：解析器保留 `objects` 和 `values`，结果只统计文件、记录、指标列和解析错误，明细按文件与时间展示。

## 6. 呼叫关联指标计算

### 6.1 成功率

优先级：

1. 若原始列存在 `呼叫成功率`，使用该值。
2. 否则若 `请求成功` 与 `呼叫请求` 存在且 `呼叫请求 > 0`，计算 `成功 / 呼叫请求 * 100`。
3. 否则该行成功率为不可用，不判越限。

### 6.2 失败率

优先级：

1. 若原始列存在 `呼叫失败率`，使用该值。
2. 否则若 `请求失败` 与 `呼叫请求` 存在且 `呼叫请求 > 0`，计算 `失败 / 呼叫请求 * 100`。
3. 否则该行失败率为不可用，不判越限。

### 6.3 自洽检查

当 `呼叫请求`、`请求成功`、`请求失败` 三者都存在时，检查：

```text
请求成功 + 请求失败 == 呼叫请求
```

不相等时计入 `consistency_error_count`，finding 保留三项原始值和差值。该检查不生成成功率或失败率阈值告警；是否同时触发阈值由派生/显式比率独立判断。

### 6.4 容量指标

`统计峰值`、`最大并发` 只展示原始值。配置中 `status=confirmed` 时记录已确认口径（`peak` / `concurrency`）；`status=unknown` 时同样展示，但输出 `capacity_semantics_unknown`。不为其构造成功/失败字段，不计算比率，不应用业务阈值。若未来需要容量阈值，必须新增领域/指标/周期配置，并升级规则版本。

## 7. 阈值配置

配置文件：`deploy/config/kpi_rules.yaml`。

建议结构：

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

约束：

- `aliases` 和 `capacity_metrics` 按领域配置；容量 `status` 只允许 `confirmed` 或 `unknown`。
- 容量 `status=unknown` 时仅展示原始值，并输出 `capacity_semantics_unknown`，不生成比率或阈值告警。
- 预算字段必须全部存在且为正整数。
- 周期键必须落在 `5/15/30/60`；缺失周期使用 `default`。
- `direction` 只允许 `min` / `max`。
- 成功率为百分比，默认下限 99%；失败率为百分比，默认上限 1%。
- 规则结果在每个受影响 metric 和 finding 中保留 `metric`、`direction`、阈值、配置来源路径。
- 配置缺失或非法时，规则返回 `error`，不得静默退回内置阈值。

## 8. 聚合与多文件处理

- 同一领域、同周期可有多个 CSV，也允许一个规则匹配四个周期。
- 规则结论是领域级一个 `RuleResult`；每个文件的 `path`、`measurement_set`、`period_minutes`、状态、记录数和错误保留在 `metadata.kpi_files[]`。
- 明细按文件再按时间顺序排序；排序键为 `path`、`start_at`。
- `file_count` 表示匹配并尝试处理的文件数。
- `record_count` 表示成功解析的数据行数。
- `parse_error_count` 是文件级和行级错误总数。
- 呼叫额外聚合成功率最小值、失败率最大值、两类越限行数和自洽异常数。
- 一个文件失败不阻断其他文件；同文件一行失败不阻断其他行。

## 9. 状态判定

| 场景 | 状态 |
| --- | --- |
| 领域未匹配到文件 | `skip`，原因说明没有该领域 KPI 文件 |
| 任一文件/行解析失败、资源预算超限 | `fail`，即使其他文件正常 |
| 呼叫任一成功率或失败率越限 | `fail` |
| 无解析失败、无阈值越限，但存在数据自洽异常 | `warn` |
| 无解析失败、无阈值越限、无自洽异常 | `pass` |

同一行同时出现解析错误和业务越限时，只根据解析错误生成数据质量 finding；不使用不完整值判阈值。同一行成功率和失败率同时越限时，可合并为一个呼叫质量 finding，但 evidence 必须同时列出两项阈值与派生值。

## 10. Finding 设计

- `finding_id` 必须确定性生成，保证同一输入和规则版本重跑一致。
- 解析错误：`kpi.<domain>:parse-error:<path_sha256>:<line_number>`。
- 自洽异常：`kpi.call:consistency:<path_sha256>:<line_number>`。
- 阈值异常：`kpi.call:threshold:<path_sha256>:<line_number>`。
- `source_file` 使用任务内相对路径。
- `evidence` 使用中文说明指标、原始值、派生值、阈值和周期。
- `recommendation` 使用规则元数据建议；阈值 finding 可补充对应周期和指标名。

## 11. 输出契约

### 11.1 API / 媒体固定 metrics

| key | label | unit |
| --- | --- | --- |
| `file_count` | 文件数 | 个 |
| `record_count` | 记录数 | 条 |
| `metric_count` | 指标列数 | 项 |
| `parse_error_count` | 解析错误数 | 条 |

### 11.2 呼叫固定 metrics

| key | label | unit |
| --- | --- | --- |
| `file_count` | 文件数 | 个 |
| `record_count` | 记录数 | 条 |
| `parse_error_count` | 解析错误数 | 条 |
| `consistency_error_count` | 自洽异常数 | 条 |
| `success_rate_min` | 成功率最小值 | % |
| `failure_rate_max` | 失败率最大值 | % |
| `success_breach_count` | 成功率越限行数 | 条 |
| `failure_breach_count` | 失败率越限行数 | 条 |
| `capacity_metric_count` | 容量指标列数 | 项 |
| `capacity_unknown_count` | 口径未知容量列数 | 项 |

若某行比率不可用，不纳入 min/max；完全没有可用比率时 `success_rate_min` / `failure_rate_max` 输出 `"N/A"` 字符串。执行器只校验 metric key/unit，不会因此判为契约错误。

### 11.3 明细

`metadata.kpi_files[]` 示例骨架见 `data-model.md`。`Metric.series` 可用于时间趋势；第一版至少保证 `metadata.kpi_files[].records[]` 可追溯每个时间点、指标名和数值。

## 12. 资源预算

解压阶段继续复用现有归档预算与路径安全防护。KPI 解析阶段增加显式上限：

| 项 | 初始上限 |
| --- | --- |
| 单个 KPI CSV | 64 MiB |
| 单文件数据行 | 100,000 |
| 单文件列数 | 256 |
| 单规则匹配文件数 | 1,000 |
| 单规则处理记录数 | 200,000 |

超限时停止继续解析超出部分，将该文件或规则标记为包含 `resource_limit_exceeded` 的 `fail` 结果；不得静默截断。CSV 解析使用流式逐行读取，避免 `read_text()` 后一次性构造全部对象。

## 13. 旧规则迁移

- 删除 `app/inspectors/kpi/threshold.py`，使注册表不再出现 `kpi.threshold`。
- 更新 `tests/test_baseline_pipeline.py`、`tests/test_rules.py`、baseline/rerun 等测试中的规则计数和 fixture。
- 现有样例中的 `kpi/kpi.csv` 不属于新命名模板，新规则自然不匹配；代表旧格式能力由新领域样例替代。
- OpenAPI 不包含具体规则代码清单，不需要接口版本升级；前端不应硬编码 `kpi.threshold`，需检查并替换为规则列表驱动。

## 14. 前端展示

- `RuleDetailPage` 继续通过 OpenAPI 生成客户端读取结果。
- 可新增只读 KPI 明细表组件，从 `RuleResult.metadata.kpi_files` 渲染：文件、周期、时间、指标名、值、错误。
- 不把 `metadata` 内容作为新的强类型 API 字段；前端对未知 metadata 做防御式渲染。
- 若实现阶段发现必须把 `series` 扩展为 `label/metric/file` 等字段，则先同步 OpenAPI、Pydantic、测试和生成客户端，再修改前端。

## 15. 备选方案

| 方案 | 结论 |
| --- | --- |
| 保留旧 `kpi.threshold` 并兼容两种 CSV | 拒绝：一个规则处理两种格式会掩盖领域边界，且容易重复巡检 |
| 使用一条 KPI 规则解析三个领域 | 拒绝：违反领域独立执行、独立重跑和故障隔离要求 |
| 为每个领域私有 prepare 并缓存 JSON | 暂缓：无法避免共享 helper/config 变化导致的缓存陈旧，第一版直接解析更简单 |
| 用 pandas 解析 | 暂缓：该依赖不在默认运行路径中，标准库 `csv` 足够且减少内存/依赖风险 |
| 把每个动态 CSV 指标生成顶层 metric key | 拒绝：执行器要求实际 metrics 与声明契约完全一致，动态 key 会破坏契约稳定性 |
