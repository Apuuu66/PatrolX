# 台账 API 契约设计

正式契约必须先落入 `docs/api/openapi.yaml`，再修改 FastAPI 实现并生成前端客户端。本文件记录新增边界和字段语义，不替代 OpenAPI。

## 版本原则

- `POST /api/v3/tasks` 为新创建语义；`/api/v2/tasks` 保持不变。
- 台账查询使用 `/api/v2/inventory/*`，因为全部是可选增量只读端点。
- 任务详情 `InspectionTask` 增加可选 `package_kind` 和 `inventory`，不改变既有字段含义。
- 所有错误沿用 `{code, message, detail}`；列表默认 `page_size=10`，最大 100。

## 创建任务

```yaml
/api/v3/tasks:
  post:
    operationId: createTaskV3
    requestBody:
      required: true
      content:
        multipart/form-data:
          schema:
            $ref: '#/components/schemas/Body_createTaskV3'
    responses:
      '202':
        description: 任务已受理
        headers:
          Location:
            schema:
              type: string
              example: /api/v2/tasks/{task_id}
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TaskCreated'
      '400':
        description: 任务类型或局点元数据校验失败
      '409':
        description: 同名任务已存在或 checksum 冲突
      '422':
        $ref: '#/components/schemas/HTTPValidationError'
```

`Body_createTaskV3`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `package_file` | binary | 是 | zip / tar.gz 上传包 |
| `name` | string \| null | 否 | 任务名；默认包名 |
| `package_kind` | string | 是 | `inspection` / `log_supplement` |
| `province` | string \| null | 条件 | 巡检包必填；日志补充包不允许非空 |
| `operator` | string \| null | 条件 | 巡检包必填；日志补充包不允许非空 |
| `product` | string \| null | 否 | 巡检包可选；日志补充包不允许非空 |

v3 请求不包含 `version` 和 `device_id`。巡检包版本只能由 `LST ME.txt` 解析；设备身份由解析出的设备名确定。

### 条件校验错误

| 错误码 | HTTP | 条件 |
| --- | --- | --- |
| `missing_province` | 400 | 巡检包省份为空 |
| `missing_operator` | 400 | 巡检包运营商为空 |
| `metadata_not_applicable` | 400 | 日志补充包传入非空省份、运营商或产品形态 |
| `package_checksum_conflict` | 409 | 任务名已存在但包 checksum 不同 |

## 台账枚举

### `PackageKind`

```yaml
type: string
enum:
  - inspection
  - log_supplement
```

### `InventoryParseStatus`

```yaml
type: string
enum:
  - archived
  - not_archived
  - not_applicable
  - failed
```

### `InventoryFieldStatus`

```yaml
type: string
enum:
  - ok
  - missing
  - conflict
  - error
  - not_applicable
```

### `VersionDirection`

```yaml
type: string
enum:
  - upgrade
  - downgrade
  - unchanged
```

### `InventoryQualityIssueType`

```yaml
type: string
enum:
  - missing_site
  - missing_device_identity
  - missing_version
  - version_conflict
  - device_identity_conflict
  - site_ownership_change
```

## 设备列表

```text
GET /api/v2/inventory/devices
```

Query：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 10，最大 100 |
| `province` | string | 否 | 过滤设备当前省份 |
| `operator` | string | 否 | 过滤设备当前运营商 |
| `quality_status` | string | 否 | `all` / `issue`；默认 `all` |

前端局点视图要求用户同时选择省份和运营商后才查询；API 本身保持过滤器可选，便于未来构建省份汇总。

Response：`InventoryDeviceList`

```yaml
InventoryDevice:
  type: object
  required:
    - device_id
    - province
    - device_name
    - site_key
    - operator
    - last_seen_at
    - observation_count
  properties:
    device_id:
      type: string
    province:
      type: string
    device_name:
      type: string
    site_key:
      type: string
    operator:
      type: string
    current_version:
      type: [string, 'null']
    current_version_observed_at:
      type: [string, 'null']
      format: date-time
    current_version_task_id:
      type: [string, 'null']
    first_seen_at:
      type: string
      format: date-time
    last_seen_at:
      type: string
      format: date-time
    observation_count:
      type: integer
    site_change_count:
      type: integer
    has_site_conflict:
      type: boolean
    quality_issue_types:
      type: array
      items:
        $ref: '#/components/schemas/InventoryQualityIssueType'
```

列表只返回 `current_site_key` 命中过滤条件的设备。历史局点设备不出在该局点列表。

## 设备详情

```text
GET /api/v2/inventory/devices/{device_id}
```

Response：`InventoryDevice`。额外返回最近观测摘要时使用可选字段 `latest_observation`，不改变设备列表复用的基础字段。

## 设备观测历史

```text
GET /api/v2/inventory/devices/{device_id}/observations
```

Query：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 10，最大 100 |
| `order` | string | 否 | `asc` / `desc`；默认 `desc` |
| `site_key` | string | 否 | 追溯历史局点时可选过滤 |

Response：`InventoryObservationList`

`InventoryObservation`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `observation_id` | string | 观测 ID |
| `task_id` | string | 来源任务 |
| `task_status` | string | 固定 `completed` |
| `observed_at` | string/date-time | 任务完成时间 |
| `province` | string | 观测时省份 |
| `operator` | string | 观测时运营商 |
| `site_key` | string | 观测时局点 |
| `device_name` | string | 规范化设备名 |
| `identity_status` | string | 固定 `ok` |
| `version_status` | string | `ok` / `missing` / `conflict` / `error` |
| `raw_version` | string \| null | 原始版本 |
| `version_source_files` | string[] | 版本来源文件 |
| `conflicts` | object[] | 身份、版本或局点冲突 |
| `snapshot` | object | 任务级解析证据摘要 |

退役观测不出现在观测历史接口；如需审计追溯，后续可单独新增审计只读端点。

## 设备版本历史

```text
GET /api/v2/inventory/devices/{device_id}/version-history
```

Query：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 10，最大 100 |

Response：`InventoryVersionHistory`

```yaml
InventoryVersionPoint:
  type: object
  required:
    - observed_at
    - task_id
    - version_status
  properties:
    observed_at:
      type: string
      format: date-time
    task_id:
      type: string
    version_status:
      $ref: '#/components/schemas/InventoryFieldStatus'
    raw_version:
      type: [string, 'null']
    direction:
      anyOf:
        - $ref: '#/components/schemas/VersionDirection'
        - type: 'null'
    has_gap:
      type: boolean
```

规则：

- 点按观测时间升序。
- `raw_version` 只在 `version_status=ok` 时非空。
- 第一个有效版本点 `direction=null`。
- 缺失、冲突或错误点保留但 `direction=null`。
- 当前版本在设备详情中显示 `current_version_observed_at` 和 `current_version_task_id`。

## 质量问题

```text
GET /api/v2/inventory/quality-issues
```

Query：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 10，最大 100 |
| `issue_type` | string | 否 | 见 `InventoryQualityIssueType` |
| `province` | string | 否 | 按任务或设备局点过滤 |
| `operator` | string | 否 | 按任务或设备局点过滤 |
| `task_id` | string | 否 | 追溯具体任务 |
| `device_id` | string | 否 | 追溯具体设备 |

Response：`InventoryQualityIssueList`

`InventoryQualityIssue`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `issue_id` | string | 确定性问题 ID |
| `issue_type` | string | 问题类型 |
| `message` | string | 中文业务说明 |
| `task_id` | string \| null | 可追溯任务 |
| `device_id` | string \| null | 可追溯设备 |
| `province` | string \| null | 局点省份 |
| `operator` | string \| null | 局点运营商 |
| `detected_at` | string/date-time | 证据写入或观测时间 |
| `detail` | object | 冲突值、来源文件或缺失原因 |

质量问题来自 `inventory_parse_results` 和 active 观测投影；日志补充包不生成质量问题。

## 契约同步

实现前必须修改 OpenAPI，并执行：

```bash
python build.py contract
python build.py gen-web-api
```

前端必须使用生成客户端调用，不允许手写与 OpenAPI 不一致的请求。
