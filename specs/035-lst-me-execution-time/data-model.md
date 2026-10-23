# 阶段 1 数据模型：设备台账版本以 LST ME 执行时间为准

**输入**：[spec.md](./spec.md)、[research.md](./research.md) ｜ **日期**：2026-10-23

## 1. 实体与字段变化

### 1.1 台账证据 `inventory.json` / `inventory_parse_results.snapshot`（扩展）

| 字段 | 变化 | 说明 |
| --- | --- | --- |
| `schema_version` | 2 → 3 | 证据结构版本 |
| `parser_version` | 3 → 4 | 解析逻辑版本（新增执行时间解析） |
| `execution_time` | **新增** | 文件级执行时间证据段，结构见 1.2 |

`execution_time` 结构：

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

- `status`：全部来源文件解析成功为 `ok`；部分成功为 `partial`；全部失败为 `missing`。
- `source`：`lst_me` 表示整体按文件时间归档，`task` 表示整体回退任务完成时间（用于任务详情概览）。
- `per_file[].raw_text`：命中的原始行文本（未命中为 `null`），用于回溯。
- `per_file[].parsed_at`：UTC 时间（ISO-8601，秒精度，按既有 `datetime.isoformat()` 约定输出 `+00:00` 偏移，例如 `2025-05-26T06:40:36+00:00`），未解析成功为 `null`。
- `per_file[].reason`：`header_time_missing` / `header_time_invalid` / `time_in_future` 之一，成功为 `null`。
- `source` 表示该任务归档**实际使用**的时间来源：全部来源文件成功解析为 `lst_me`，只要有一条回退即整体记 `task`（用于任务详情概览）。
- 任务没有 `LST ME.txt` 来源文件（如 `source_file_missing`、日志补充包等不解析台账的场景）时，`execution_time` 为 `{"status": "missing", "source": "task", "per_file": []}`。
- 历史证据（`schema_version < 3`）缺少该段时，读取方必须按"任务完成时间兜底"语义处理，不得报错。

### 1.2 设备观测 `inventory_observations`（扩展）

| 字段 | 类型 | 变化 | 说明 |
| --- | --- | --- | --- |
| `observed_at` | DATETIME(UTC) | **语义变更** | 由"任务完成时间"改为"设备执行时间"，不可解析时仍为任务完成时间 |
| `time_source` | `VARCHAR(16)` NOT NULL DEFAULT `'task'` | **新增** | `lst_me`（设备执行时间）/ `task`（任务完成时间兜底） |
| `time_source_reason` | `VARCHAR(32)` NULL | **新增** | `header_time_missing` / `header_time_invalid` / `time_in_future`；来源为 `lst_me` 时为 `NULL` |

- 迁移：沿用 `_ensure_*_columns` 幂等 `ALTER TABLE ADD COLUMN`；旧行 `time_source` 取默认值 `task`、`time_source_reason` 为 `NULL`（历史语义即任务完成时间）。
- 覆盖语义不变：`(task_id, device_id)` 唯一，重跑/重建覆盖同一观测并同时刷新 `observed_at` 与时间来源字段。
- 审计快照（`inventory_change_audits.before_snapshot/after_snapshot`）自动包含新增字段，无需改表。

### 1.3 设备投影 `inventory_devices`（语义变化，无字段变化）

| 字段 | 语义变化 |
| --- | --- |
| `first_seen_at` | 该设备全部 active 观测中**最早执行时间** |
| `last_seen_at` | 该设备全部 active 观测中**最近执行时间** |
| `current_version_observed_at` | 当前版本所在观测的**执行时间** |
| `current_version_raw` / `current_version_task_id` | 无变化：仍为最新有效版本观测的版本与任务 |

### 1.4 证据来源文件 `LST ME.txt`（新增解析输入）

- 头部区域：文件第一行至第一条设备记录行之前；文件无设备记录行时为全文。
- 取第一个行尾匹配 `\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*$` 的行。
- 每个来源文件独立解析一个执行时间；文件内全部设备记录共用该时间（用户确认 B）。
- 同一设备在同一任务内命中多个来源文件时，该设备的观测时间取这些文件中**最近的可解析执行时间**（与"执行时间最近即最新版本"一致）。
- 该行不参与键值字段解析，不产生设备记录、类型或版本候选。

## 2. 校验规则

1. **格式**：日期必须为 `YYYY-MM-DD`、时间必须为 `HH:MM:SS`；非法日期（如 `2025-02-30`）判 `header_time_invalid`。
2. **时区**：按固定 UTC+8 解释并转 UTC 存储，秒精度，微秒置 0。
3. **上界**：解析结果晚于任务完成时间 5 分钟以上判 `time_in_future`，回退任务完成时间。
4. **下界**：不设下限，历史包时间照常采用。
5. **回退不可中断**：任何时间解析失败都不得使任务失败、不得跳过观测归档，只影响 `observed_at` 与来源记录。
6. **冲突不参与**：同一任务内同设备版本冲突仍判 `conflict` 且不归档；时间解析不改变该判定。

## 3. 排序与裁决规则

| 场景 | 规则 |
| --- | --- |
| 设备当前版本 | active 观测按 `observed_at` 倒序，取第一条**有效版本**（`version_status=ok` 且版本非空）观测 |
| 最近观测 / 首次观测 | active 观测 `observed_at` 的最大值 / 最小值 |
| 观测列表 | `observed_at` 升/降序，次序相同时按 `task_id` 稳定排序 |
| 版本历史 | `observed_at` 升序；方向由相邻有效版本字符串序比较得出，缺口按 `has_gap` 标记 |
| 质量问题检测时间 | 观测相关问题的 `detected_at` 取该观测的 `observed_at` |
| 相同执行时间 | 以 `task_id` 稳定次序裁决，保证结果可重复 |
| 同设备多来源文件 | 该设备观测时间取命中文件中最近的可解析执行时间，其余文件的时间不影响该观测 |

## 4. 状态与生命周期

1. 任务完成 → 解析 `LST ME.txt` → 证据含 `execution_time` → 归档观测（`observed_at` = 设备执行时间或任务完成时间兜底，并写入 `time_source` / `time_source_reason`）。
2. 重跑 / 重建 → 重新解析并覆盖同一观测，时间字段随之刷新。
3. 单规则重跑（`verify-one`）→ 不触发台账重算，观测时间保持不变。
4. 日志补充包 → 不解析台账，不产生观测（`not_applicable`）。
5. 磁盘现场被清理 → 观测与证据快照仍在数据库，界面展示不受影响。

## 5. 兼容与迁移

- 旧观测（无 `time_source`）：迁移后为 `task`，语义与既有"任务完成时间"一致；排序与展示不出现错误或空白。
- 旧证据（`schema_version` 2）：任务详情台账面板不显示执行时间来源，按兜底时间展示。
- 不自动回填；重跑或重建后按新口径生效。
- KPI 数据、任务时间字段、留存清理策略、规则执行器均不受影响。
