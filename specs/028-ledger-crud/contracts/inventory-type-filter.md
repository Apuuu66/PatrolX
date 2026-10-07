# 网元类型筛选与任务台账证据契约

## 目标

`LST ME.txt` 中的一个文件可以包含多台设备。上传时用户可见的“网元类型”对应后端既有 `product` 字段，作为记录级筛选条件；只有记录网元类型与 `product` 规范化值相等的设备才进入台账。

## 解析规则

- `PARSER_VERSION=3`；`schema_version=2`。
- 一条设备记录由设备名行开启，后续键值行归属该记录，直到下一个设备名行。
- 支持别名：
  - 设备名：`NE name`、`ME name`、`网元名称`、`设备名称`
  - 网元类型：`ME type`、`NE type`、`网元类型`
  - 版本：`Software version`、`SW version`、`软件版本`
- 键值按冒号或等号分隔，去除两侧空白。
- 设备名和网元类型规范化为 NFC、去首尾空白、合并连续空白；不做大小写转换。
- `product` 与记录网元类型规范化后全等比较。
- 同一文件或同一任务可产生多台匹配设备；台账按设备分别建档和写观测。
- 只识别所选网元类型：不匹配的记录不进入 `records` 明细，只计入 `unmatched_count`。
- 同一任务内规范化设备名相同且匹配的多条记录合并为一台设备；版本一致时只写一条观测，版本不同时版本冲突且不归档。
- 设备名行之前的游离键值字段不归档，写入结构化错误或摘要。

## 响应增量

`TaskInventory` 保留既有 `site`、`device`、`version` 字段，新增可选字段：

```yaml
network_element_type_filter:
  type: object
  properties:
    requested:
      type: [string, 'null']
    normalized:
      type: [string, 'null']
    status:
      type: string
      enum: [ok, missing, no_match]
    matched_count:
      type: integer
    unmatched_count:
      type: integer
records:
  type: array
  items:
    $ref: '#/components/schemas/TaskInventoryRecord'
devices:
  type: array
  items:
    $ref: '#/components/schemas/TaskInventoryMatchedDevice'
archived:
  type: object
  properties:
    archived:
      type: boolean
    device_id:
      type: [string, 'null']
      description: 兼容旧客户端；仅单个归档设备时返回。
    observation_id:
      type: [string, 'null']
      description: 兼容旧客户端；仅单个归档设备时返回。
    reason:
      type: [string, 'null']
    devices:
      type: array
      items:
        $ref: '#/components/schemas/TaskInventoryArchivedDevice'
```

`TaskInventoryRecord` 至少包含：

```yaml
raw_name: string | null
normalized_name: string | null
raw_network_element_type: string | null
normalized_network_element_type: string | null
raw_version: string | null
matched: boolean
source_file: string | null
name_source_lines: array
type_source_lines: array
version_source_lines: array
```

`TaskInventoryMatchedDevice` 至少包含：

```yaml
status: string
raw_name: string | null
normalized_name: string
network_element_type: string | null
version:
  status: InventoryFieldStatus
  raw_version: string | null
source_file: string | null
```

## 归档结果

既有 `archived.device_id` / `archived.observation_id` 保持可空，不再表达多设备总集：

- 一个匹配设备时两个旧字段继续返回该设备。
- 多个匹配设备时旧字段为 `null`，使用 `archived.devices[]`。
- 没有匹配设备时 `archived=false`，`reason` 说明原因。

`TaskInventoryArchivedDevice` 至少包含：

```yaml
device_id: string
observation_id: string
normalized_name: string
network_element_type: string | null
```

## 归档规则

| 场景 | 任务 | `inventory.json` | 台账 |
| --- | --- | --- | --- |
| `product` 缺失 | 不失败 | `not_archived`，`network_element_type_filter_missing` | 不归档 |
| 记录缺网元类型 | 不失败 | 计入 `unmatched_count`，不进入 `records` | 不归档 |
| 无匹配网元类型 | 不失败 | `not_archived`，`network_element_type_no_match` | 不归档 |
| 多条不同设备匹配 | 不失败 | `archived`；`devices` 返回全部匹配设备 | 每台匹配设备写入一条观测 |
| 同名匹配记录版本一致 | 不失败 | `records` 保留多条匹配记录，`devices` 去重 | 只写入一条观测 |
| 同名匹配记录版本不同 | 不失败 | 该设备版本冲突，其他设备继续 | 冲突设备不归档 |
| 设备名行前游离字段 | 不失败 | 写入 `errors` 或未归属摘要 | 不归档 |
| 单条解析异常 | 不失败 | 其他记录继续；异常写入 `errors` | 只归档有效匹配记录 |

## 前端展示

- 上传表单和任务详情统一显示“网元类型”。
- 任务详情优先展示 `devices` 列表；每行显示设备名、网元类型、版本和来源行。
- 任务详情的记录明细只展示所选网元类型的记录；其它类型只显示未匹配数量。
- 多设备时不得把不同设备或版本聚合为一个虚假单一设备。
- 无匹配时展示明确中文原因和筛选值，不把任务显示为巡检失败。
