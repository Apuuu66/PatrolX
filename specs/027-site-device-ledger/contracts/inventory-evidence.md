# 任务台账证据与详情增量契约

## `output/<task_id>/inventory.json`

`inventory.json` 是任务级可重建证据，不承担跨任务台账持久性。它必须在任务完成归档时原子写入；任务输出重建时可以重新生成。任务详情优先读取 SQLite `inventory_parse_results.snapshot`；若该表不可用或需要诊断原始现场，再读取 `inventory.json`。

### Schema

```json
{
  "schema_version": 1,
  "task_id": "task-example",
  "package_kind": "inspection",
  "status": "archived",
  "parser_id": "site_device_lst_me",
  "parser_version": "1",
  "site": {
    "status": "ok",
    "source": "upload_metadata",
    "province": "广东省",
    "operator": "移动",
    "site_key": "广东省:移动"
  },
  "device": {
    "status": "ok",
    "raw_names": ["GD-GZ-Core-01"],
    "normalized_name": "GD-GZ-Core-01",
    "source_lines": [7]
  },
  "version": {
    "status": "ok",
    "raw_version": "V900R021C10SPC100",
    "candidates": ["V900R021C10SPC100"],
    "source_lines": [11]
  },
  "source_files": ["config/LST ME.txt"],
  "conflicts": [],
  "errors": [],
  "archived": {
    "archived": true,
    "device_id": "deterministic-device-id",
    "observation_id": "deterministic-observation-id"
  },
  "created_at": "2026-09-27T02:20:31Z",
  "updated_at": "2026-09-27T02:20:31Z"
}
```

> 上述 `device_id` / `observation_id` 示例应为无空格的确定性十六进制 ID，实际值由数据模型定义派生。

### `source_files`

- 保存任务目录内以 `/` 归一化的相对路径。
- 一个任务可能存在多个候选路径；只要文件名精确匹配且内容可解析，全部路径都保留用于追溯。
- 文件缺失时为空数组 `[]`。

### `status`

| 状态 | 触发条件 |
| --- | --- |
| `archived` | 局点和设备身份有效，观测已写入台账 |
| `not_archived` | 巡检包缺少局点、缺少文件、无法解析设备身份或身份冲突 |
| `not_applicable` | 用户声明 `log_supplement` |
| `failed` | 解析或归档发生意外错误；任务不失败 |

### 日志补充包示例

```json
{
  "schema_version": 1,
  "task_id": "task-log-only",
  "package_kind": "log_supplement",
  "status": "not_applicable",
  "parser_id": "none",
  "parser_version": "0",
  "not_applicable_reason": "log_supplement_package",
  "site": null,
  "device": null,
  "version": null,
  "source_files": [],
  "conflicts": [],
  "errors": [],
  "archived": {
    "archived": false,
    "reason": "not_applicable"
  },
  "created_at": "2026-09-27T02:20:31Z",
  "updated_at": "2026-09-27T02:20:31Z"
}
```

### 普通巡检包缺少 `LST ME.txt`

```json
{
  "package_kind": "inspection",
  "status": "not_archived",
  "site": {
    "status": "ok",
    "source": "upload_metadata"
  },
  "device": {
    "status": "missing",
    "reason_code": "source_file_missing"
  },
  "version": {
    "status": "not_applicable"
  },
  "source_files": [],
  "not_archived_reason": "source_file_missing"
}
```

普通巡检包缺少来源文件不等同于日志补充包，任务详情必须展示“设备观测未归档：缺少 `LST ME.txt`”。

## 解析契约

### 来源匹配

- 分类规则增加 `^LST ME\.txt$`，确保文件名精确归入 `config`。
- 台账解析匹配任务目录下归一化相对路径：

```text
^config/(?:.*/)?LST ME\.txt$
```

- 文件名大小写不敏感匹配；写入 `source_files` 时保留实际相对路径。

### 文本读取

- 使用项目统一解码入口，至少兼容 UTF-8 和 GB18030。
- 解码失败返回结构化错误，不把乱码写入设备名或版本。
- 单个来源文件失败不影响其他来源文件尝试。

### 字段别名

| 字段 | 支持别名 |
| --- | --- |
| 设备名 | `NE name`、`ME name`、`网元名称`、`设备名称` |
| 版本 | `Software version`、`SW version`、`软件版本` |

解析器按冒号或等号分隔键值，去除键值两侧空白。重复相同值不冲突；重复不同值按冲突处理并保留行号和原始值。

### 设备名规范化

```text
1. Unicode NFC
2. 去除首尾空白
3. 连续空白合并为一个空格
4. 不做大小写转换
```

## 任务详情增量契约

`InspectionTask` 增加两个可选字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `package_kind` | `PackageKind` \| null | 旧任务为 `inspection`；接口未写入前可为 null |
| `inventory` | `TaskInventory` \| null | 任务完成后返回台账解析证据；进行中任务为 null |

`TaskInventory` 以 `inventory.json` 的核心字段为准，但不要求返回完整 `device_snapshot`；响应至少包含：

```yaml
TaskInventory:
  type: object
  required:
    - package_kind
    - status
  properties:
    package_kind:
      $ref: '#/components/schemas/PackageKind'
    status:
      $ref: '#/components/schemas/InventoryParseStatus'
    parser_id:
      type: string
    parser_version:
      type: string
    not_applicable_reason:
      type: [string, 'null']
    not_archived_reason:
      type: [string, 'null']
    site:
      anyOf:
        - $ref: '#/components/schemas/TaskInventorySite'
        - type: 'null'
    device:
      anyOf:
        - $ref: '#/components/schemas/TaskInventoryDevice'
        - type: 'null'
    version:
      anyOf:
        - $ref: '#/components/schemas/TaskInventoryVersion'
        - type: 'null'
    source_files:
      type: array
      items:
        type: string
    conflicts:
      type: array
      items:
        type: object
        additionalProperties: true
    errors:
      type: array
      items:
        type: object
        additionalProperties: true
    archived:
      $ref: '#/components/schemas/TaskInventoryArchive'
```

### `TaskInventorySite`

| 字段 | 类型 |
| --- | --- |
| `status` | `ok` / `missing` / `not_applicable` |
| `source` | `upload_metadata` / `none` |
| `province` | string \| null |
| `operator` | string \| null |
| `site_key` | string \| null |

### `TaskInventoryDevice`

| 字段 | 类型 |
| --- | --- |
| `status` | `ok` / `missing` / `conflict` / `error` / `not_applicable` |
| `raw_names` | string[] |
| `normalized_name` | string \| null |
| `reason_code` | string \| null |
| `source_lines` | integer[] |

### `TaskInventoryVersion`

| 字段 | 类型 |
| --- | --- |
| `status` | `ok` / `missing` / `conflict` / `error` / `not_applicable` |
| `raw_version` | string \| null |
| `candidates` | string[] |
| `source_lines` | integer[] |

### `TaskInventoryArchive`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `archived` | boolean | 是否已归档当前生效观测 |
| `device_id` | string \| null | 已归档设备 |
| `observation_id` | string \| null | 已归档观测 |
| `reason` | string \| null | 未归档原因 |

## 上传界面契约

### 巡检包

- 包类型：巡检包。
- 必填：省份、运营商。
- 可选：任务名、产品形态。
- 禁用/隐藏：人工版本、设备 ID。
- 提示：版本和设备名将从 `LST ME.txt` 解析。

### 日志补充包

- 包类型：日志补充包。
- 必填：压缩包；任务名可选。
- 不显示：省份、运营商、产品形态、版本、设备 ID。
- 提示：不涉及设备台账和版本历史。

### 提交动作

- 巡检包调用生成的 `createTaskV3`。
- 日志补充包同样调用 `createTaskV3`，`package_kind=log_supplement`。
- 保留现有 v2 API 生成客户端方法，但前端上传不再调用。
