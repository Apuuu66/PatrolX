# 契约：KPI 按类型拆分配置

本契约描述 Git 内的权威配置文件集合。API 契约暂不变化；任务快照继续以 `docs/api/openapi.yaml` 和 `KpiTaskCatalogSnapshot` 为准。

## 目录契约

```text
deploy/data/kpi/
  base/
    metrics.json
    units.json
  rules/
    common.json
    metric-rules.json
    thresholds.json
    capacity-rules.json
    display-rules.json
```

- 这七个路径固定；不允许动态发现其他配置文件。
- 所有 JSON 必须使用 UTF-8 和 LF。
- 解析使用严格 JSON：拒绝重复对象字段。
- 加载器不得回退读取旧 `deploy/data/kpi_catalog.json`。

## 公共字段

| 文件 | 顶层字段 |
| --- | --- |
| `metrics.json` | `schema_version`, `source_csv_sha256`, `metrics` |
| `units.json` | `schema_version`, `units` |
| `common.json` | `schema_version`, `input_timezone`, `budgets` |
| `metric-rules.json` | `schema_version`, `metric_rules` |
| `thresholds.json` | `schema_version`, `thresholds` |
| `capacity-rules.json` | `schema_version`, `capacity_rules` |
| `display-rules.json` | `schema_version`, `display_rules` |

- `schema_version` 当前必须为 `1`。
- 未知顶层字段禁止出现。
- `schema_version` 不作为业务配置版本，只用于结构迁移。

## 资源 CSV 到基础文件

`python -m app.tools.kpi_catalog generate --csv <path> --data-dir deploy/data/kpi`：

| 输入状态 | 行为 |
| --- | --- |
| CSV 有效 | 完整重写 `metrics.json` 和 `units.json` |
| CSV 中没有旧指标 | 从 `metrics.json` 移除旧指标 |
| 被移除指标仍被规则引用 | 生成或聚合校验失败，规则文件不变 |
| CSV 缺失、格式错误或重复 | 整个命令失败，不写任何目标文件 |
| 规则文件损坏或引用错误 | 聚合校验失败，不写任何目标文件 |

单位资源只登记。当前不解析 `ME_*` 名称括号中的单位，不建立 `ME_* -> UNIT_*` 强制映射，也不把单位用于阈值或换算。

## 目录加载错误

错误必须包含：

1. 相对文件路径；
2. JSON 数组下标或字段路径；
3. 错误原因，例如缺少字段、重复 key、非法引用、公式循环或文件缺失。

示例：

```text
deploy/data/kpi/rules/thresholds.json: thresholds[0].metric_key: 引用未知基础指标 me_call_success_rate
deploy/data/kpi/base/metrics.json: metrics[2]: 资源 ID 或稳定 key 重复
deploy/data/kpi/rules/metric-rules.json: metric_rules[key=me_xxx]: 公式依赖形成循环
```

加载失败时不创建新任务快照，不回退旧配置，不静默跳过。

## 内容指纹

既有字段 `base_data_version` 继续保留，值为拆分配置集的确定性 SHA-256：

```text
sha256(concat(
  "base/metrics.json" + 0x00 + file_bytes + 0x00,
  "base/units.json" + 0x00 + file_bytes + 0x00,
  "rules/common.json" + 0x00 + file_bytes + 0x00,
  "rules/metric-rules.json" + 0x00 + file_bytes + 0x00,
  "rules/thresholds.json" + 0x00 + file_bytes + 0x00,
  "rules/capacity-rules.json" + 0x00 + file_bytes + 0x00,
  "rules/display-rules.json" + 0x00 + file_bytes + 0x00
))
```

固定顺序、固定路径和固定分隔符必须写入测试。该指纹只用于诊断和既有快照字段，不是用户维护的版本。

## 快照写入与重跑

| 场景 | 行为 |
| --- | --- |
| 新任务首次需要 KPI 配置 | 读取并校验拆分目录，组合 SQLite 分类后写快照 |
| 快照存在且可解析 | 复用快照；不读取当前配置重建 |
| 配置变化后创建新任务 | 新任务生成包含新配置的快照 |
| 全量重跑且快照存在 | 复用快照 |
| 指定规则重跑且快照缺失 | 拒绝执行 |
| 快照损坏 | 拒绝执行，不回退当前配置 |
