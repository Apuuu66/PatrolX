# 阶段 0 研究：设备台账版本以 LST ME 执行时间为准

**输入**：[spec.md](./spec.md) ｜ **日期**：2026-10-23

## R1 时间行的定位与匹配规则

**Decision**：在每个 `LST ME.txt` 来源文件的**头部区域**取第一个"行尾匹配日期时间"的行作为执行时间，匹配即停止扫描。

- 行尾模式：`(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s*$`，`\s` 覆盖多空格与制表符。
- 头部区域 = 文件第一行到**第一条设备记录行**（设备名别名行，如 `NE name` / `网元名称`）之前；文件中不存在设备记录行时，头部区域为全文。
- 命中的行同时记录原始文本与行号；该行不参与键值字段解析（它不属于设备记录字段）。

**Rationale**：用户确认（回答 B）整个文件只有顶部一行时间行，文件内所有设备共用；行尾锚定可避免把正文中的其他日期误判为执行时间；"设备记录之前"的边界让大型清单文件只需扫描极少数行。

**Alternatives considered**：
1. 只检查第一行——真实文件首行存在 `%%LST ME:;%%` 一类命令回显噪声时会漏解析。
2. 全文扫描取第一个匹配——可能命中正文时间，且失去"文件只扫头部"的性能保证。
3. 每个设备块各取一行（原 A 方案）——与用户确认的现场事实不符。

## R2 时区与时间粒度

**Decision**：头部时间按固定 UTC+8 偏移解释（`datetime.timezone(timedelta(hours=8))`），转换为 UTC 后落库，微秒置 0；粒度到秒。

**Rationale**：设备现场输出的是北京时间且不带时区标记；中国自 1991 年起无夏令时，固定偏移足够；不依赖 `zoneinfo`/`tzdata`（Windows 默认无 tz 数据库，缺失时 `zoneinfo` 会抛错，与 008 的 Windows 适配目标冲突）。宪法要求 UTC 存储，转换在解析边界完成。

**Alternatives considered**：
1. `zoneinfo.ZoneInfo("Asia/Shanghai")`——无新增依赖时在 Windows 上不可用。
2. 按服务器本地时区解释——部署环境时区不确定，会产生隐式依赖。
3. 保留原始字符串不做时区换算——违反 UTC 存储约束，无法与任务时间比较。

## R3 时间可信性校验

**Decision**：满足以下任一条件即判定不可信，回退任务完成时间并记录原因：

| 情况 | `time_source` | `time_source_reason` |
| --- | --- | --- |
| 头部无匹配行 | `task` | `header_time_missing` |
| 匹配到但日期时间非法（如 2025-02-30） | `task` | `header_time_invalid` |
| 解析结果晚于任务完成时间 5 分钟以上 | `task` | `time_in_future` |
| 正常解析 | `lst_me` | `null` |

**Rationale**：设备与服务器存在小幅时钟偏差，5 分钟容差避免把正常数据误判；不设时间下限，因为补传历史包（数月甚至更早）是合法场景。上界校验防止错误日期把某个版本永久顶在"最新"。

**Alternatives considered**：
1. 不做上界校验——错误年份会长期污染版本裁决。
2. 严格禁止晚于完成时间——时钟偏差会造成无谓回退。
3. 设时间下限（如不早于 2010 年）——真实历史包时间无法先验界定。

## R4 观测时间与来源的落库形态

**Decision**：`inventory_observations` 新增两列并在 API 暴露：

- `time_source`：`lst_me` / `task`，非空，默认 `task`（旧行迁移后即为 `task`）。
- `time_source_reason`：`header_time_missing` / `header_time_invalid` / `time_in_future` / `NULL`。

**Rationale**：FR-004 要求来源可查询、界面可区分；来源与原因拆两列职责单一，与既有 `status` + `reason_code` 风格一致。单列混合枚举会把"来源"和"原因"耦合在一个字段里，前端与统计都难以消费。仅存 JSON 快照则列表/详情接口需要逐条反序列化，契约上也不可见。

**Alternatives considered**：
1. 复用 `version_source_files` 之类的 JSON 字段——语义不符，无法索引与过滤。
2. 只在证据文件里保留——磁盘现场可能被清理，而界面数据必须来自数据库。

## R5 证据结构与兼容读取

**Decision**：`inventory.json` 与 `inventory_parse_results.snapshot` 新增顶层 `execution_time` 段：

```json
{
  "status": "ok | partial | missing",
  "source": "lst_me | task",
  "per_file": [
    {
      "source_file": "config/LST ME.txt",
      "raw_text": "+++    CSP/*xx*/     2025-05-26  14:40:36",
      "line": 1,
      "parsed_at": "2025-05-26T06:40:36+00:00",
      "status": "ok | missing | invalid | time_in_future",
      "reason": null
    }
  ]
}
```

`schema_version` 2 → 3，`parser_version` 3 → 4。读取侧兼容：历史证据缺少该段时，按"任务完成时间"语义处理，不报错、不出现空白。

**Rationale**：时间按来源文件独立记录，可在界面上解释"这条观测的时间来自哪个文件的哪一行"；保留 `raw_text` 满足"可追溯回原始数据"的宪法要求；schema 版本递增沿用 027 的兼容策略。

**Alternatives considered**：
1. 每条设备记录内各存一份时间——多设备文件重复冗余，且无法表达"文件级解析失败"。
2. 直接改 `schema_version` 语义但不加段——旧证据无法区分，违反可追溯。

## R6 排序与"当前版本"的裁决点

**Decision**：执行时间写入既有 `observed_at` 列，查询侧排序口径不变（`observed_at` 升/降序 + `task_id` 稳定次序）：`_recalculate_device`、`list_observations`、`get_version_history`、`list_quality_issues` 因此自动按执行时间工作。"当前版本"仍取最新的**有效版本**观测，较新的无版本观测不会清空当前版本，只影响最近观测与缺口标记。

**Rationale**：把口径变化收敛在写入侧，避免查询侧双口径；时间相同时用 `task_id` 保证结果可重复（同一任务同一设备只有一条观测）。

**Alternatives considered**：
1. 查询时实时读取证据文件时间——磁盘现场可能已被清理，且每行 JSON 解析带来性能与一致性风险。
2. 新增独立的版本时间列——两套时间并存会让"最近观测"与"当前版本"不一致。

## R7 版本方向与冲突语义保持不变

**Decision**：版本历史的 `upgrade` / `downgrade` / `unchanged` 仍按字符串序比较相邻**有效版本**，`has_gap` 保持既有语义；同一任务内同设备多版本值仍判 `conflict` 且不归档，不参与时间裁决。

**Rationale**：用户明确"同一站点版本不会来回变化"，时间口径已解决"谁是当前版本"的问题；现场未提供版本号解析规则，自造比较器风险高于收益，且会改动既有契约字段含义。

**Alternatives considered**：
1. 解析 `VxxxRxxxCxxSPCxx` 生成可比版本键——无现场规则依据，容易误判。
2. 取消方向标记只保留时间序列——改动既有契约与 UI，收益有限。

## R8 存量数据与重跑语义

**Decision**：不自动回填存量观测；旧证据、旧观测按"任务完成时间"语义继续参与排序与展示。任务重跑或重建时按新口径重新解析并覆盖观测（含 `observed_at` 与 `time_source`）。

**Rationale**：磁盘现场可能已被留存策略清理（034），无法可靠回填；重跑/重建是既有的显式恢复路径。避免为一次性数据迁移引入不可验证的猜测逻辑。

**Alternatives considered**：
1. 启动时扫描 `output/**/inventory.json` 与现场文件回填——现场可能缺失，且解析器版本差异会造成部分回填。
2. 依据任务 `last_run_at` 猜测——与真实执行时间无关，属于错误数据源。
