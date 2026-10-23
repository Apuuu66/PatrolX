# 阶段 1 契约增量：设备台账版本以 LST ME 执行时间为准

**输入**：[spec.md](../spec.md)、[data-model.md](../data-model.md) ｜ **日期**：2026-10-23

本特性只做**非破坏性增量**：不新增路径、不新增错误码、不改变既有字段含义的取值集合，仅在既有响应与证据结构中新增可选/补充字段。契约先行，`docs/api/openapi.yaml` 必须先落地再改实现与前端生成客户端。

## 1. `/api/v2/inventory/devices/{device_id}/observations`

`InventoryObservation` 新增：

```yaml
time_source:
  type: string
  enum: [lst_me, task]
  title: Time Source
  description: 观测时间来源；lst_me 为包内 LST ME 执行时间，task 为任务完成时间兜底。
time_source_reason:
  anyOf:
    - type: string
      enum: [header_time_missing, header_time_invalid, time_in_future]
    - type: 'null'
  title: Time Source Reason
  description: 回退为任务完成时间时的原因；来源为 lst_me 时为 null。
```

`observed_at` 字段含义收窄说明（写进 `description`，不改字段名与类型）：该时间优先取包内 `LST ME.txt` 头部记录的执行时间（UTC），无法解析或不可信时回退为任务完成时间。

## 2. `/api/v2/inventory/devices/{device_id}/version-history`

`InventoryVersionPoint` 新增：

```yaml
time_source:
  type: string
  enum: [lst_me, task]
  title: Time Source
```

版本点的 `observed_at` 与排序沿用 §1 的执行时间口径；`direction` 与 `has_gap` 语义不变。

## 3. `/api/v2/inventory/devices`、`/api/v2/inventory/devices/{device_id}`

`InventoryDevice` **不新增字段**，但字段语义按执行时间口径调整（写入对应 `description`）：

- `current_version_observed_at`：当前版本所在观测的执行时间。
- `first_seen_at` / `last_seen_at`：该设备最早/最近**执行时间**，不再是任务完成时间。

## 4. `/api/v2/inventory/quality-issues`

`InventoryQualityIssue.detected_at` 对观测类问题取该观测的执行时间；结构与筛选参数不变。

## 5. 任务详情台账证据

`TaskInventory` 新增 `execution_time`：

```yaml
execution_time:
  anyOf:
    - $ref: '#/components/schemas/TaskInventoryExecutionTime'
    - type: 'null'
TaskInventoryExecutionTime:
  type: object
  required: [status, source, per_file]
  properties:
    status:
      type: string
      enum: [ok, partial, missing]
    source:
      type: string
      enum: [lst_me, task]
    per_file:
      type: array
      items:
        $ref: '#/components/schemas/TaskInventoryExecutionTimeEntry'
TaskInventoryExecutionTimeEntry:
  type: object
  required: [source_file, line, status]
  properties:
    source_file:
      type: string
    raw_text:
      anyOf:
        - type: string
        - type: 'null'
    line:
      anyOf:
        - type: integer
        - type: 'null'
    parsed_at:
      anyOf:
        - type: string
          format: date-time
        - type: 'null'
    status:
      type: string
      enum: [ok, missing, invalid, time_in_future]
    reason:
      anyOf:
        - type: string
          enum: [header_time_missing, header_time_invalid, time_in_future]
        - type: 'null'
```

- `source` 表示归档实际使用的时间来源：全部来源文件成功解析为 `lst_me`，只要有一条回退即记 `task`；任务无 `LST ME.txt` 来源文件时返回 `{"status": "missing", "source": "task", "per_file": []}`。
- 字段为可空：历史任务（证据 `schema_version` 2）没有该段，接口必须返回 `null` 而不是报错。
- `parser_version` 值由 `3` 变为 `4`，`schema_version` 由 `2` 变为 `3`；两者在契约中仍是字符串/整数，无结构变化。

## 6. 兼容性判定

| 变更 | 兼容性 | 说明 |
| --- | --- | --- |
| 新增 `time_source` / `time_source_reason` | 非破坏 | 新增字段，旧客户端忽略即可 |
| 新增 `execution_time` 证据段 | 非破坏 | 可空字段，旧证据返回 `null` |
| `observed_at` 等时间字段语义调整 | 兼容性影响已声明 | 字段名、类型、方向（按时间排序）不变，仅时间来源更精确；在 `description` 中显式说明 |
| 错误码 | 无变化 | 不新增错误码，时间解析失败不产生接口错误 |

版本前缀策略：维持 `/api/v2`，不新开版本；若后续需要把"任务完成时间"单列展示，再评估独立字段。

## 7. 验收取证点

- `python build.py contract` 通过（OpenAPI 与 Pydantic 一致）。
- `python build.py gen-web-api` 后前端生成客户端包含新增字段。
- `tests/test_inventory_parser.py` 覆盖 `execution_time` 段结构与三种回退状态。
- `tests/test_inventory_ledger.py` 覆盖观测 `observed_at` 取执行时间、回退写 `time_source`、乱序补传当前版本不回退。
- `web/e2e/inventory-execution-time.spec.ts` 覆盖界面时间来源标识与任务详情台账面板展示。
