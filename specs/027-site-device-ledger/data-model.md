# 数据模型：局点设备台账

## 总览

台账使用四张 SQLite 表：

```text
inventory_devices          设备当前状态
1 ────────< inventory_observations            设备观测
                    1 ────────< inventory_change_audits   观测覆盖/退役审计

inventory_parse_results    任务级解析证据；通过 task_id 引用任务
```

`site` 不是独立表，而是由 `province + operator` 组合出的展示键：

```text
site_key = province:operator
```

所有 `*_at` 字段使用 UTC `DateTime(timezone=True)`。JSON 字段保存兼容 SQLite 的结构化快照；时间在 JSON 内使用 UTC ISO-8601 字符串。

## 任务增量字段

### `tasks.package_kind`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `package_kind` | `VARCHAR(32)` | 非空，默认 `inspection` | 任务包类型；旧任务迁移为 `inspection` |

`package_kind` 是任务生命周期元数据，不参与 `task_id` 派生。旧库迁移使用 `ALTER TABLE ... ADD COLUMN`，不得重建或清空任务表。

## `inventory_devices`

设备台账的当前状态表。一行代表一个设备身份。

| 字段 | 类型 | 约束 / 索引 | 说明 |
| --- | --- | --- | --- |
| `device_id` | `VARCHAR(64)` | PK | 稳定设备 ID；由省份和 `device_key` 确定性派生 |
| `device_key` | `VARCHAR(64)` | `UNIQUE(province, device_key)` | 规范化设备名摘要 |
| `province` | `VARCHAR(64)` | `UNIQUE(province, device_key)`；索引 | 设备身份省份 |
| `current_device_name` | `VARCHAR(256)` | 非空 | 当前规范化设备名 |
| `current_site_key` | `VARCHAR(160)` | 索引 | 最近一次有效观测的 `province:operator` |
| `current_operator` | `VARCHAR(64)` | 非空 | 最近一次有效观测的运营商 |
| `current_version_raw` | `VARCHAR(256)` | nullable | 最近一次成功解析版本的原始字符串 |
| `current_version_observed_at` | `DateTime` | nullable | 当前版本观测时间 |
| `current_version_task_id` | `VARCHAR(64)` | nullable | 当前版本来源任务 |
| `current_observation_id` | `VARCHAR(64)` | nullable，FK | 最近一次有效观测 |
| `first_seen_at` | `DateTime` | 非空 | 最早当前生效观测时间 |
| `last_seen_at` | `DateTime` | 非空 | 最近当前生效观测时间 |
| `latest_task_id` | `VARCHAR(64)` | 非空 | 最近当前生效观测的任务 |
| `latest_status` | `VARCHAR(32)` | 非空 | 最近观测状态：`archived` / `retired` |
| `observation_count` | integer | 非空，默认 0 | 当前生效观测数量 |
| `site_change_count` | integer | 非空，默认 0 | 当前生效观测中局点变化次数 |
| `has_site_conflict` | boolean | 非空，默认 false | 历史观测是否跨越不同运营商 |
| `created_at` | `DateTime` | 非空 | 设备首次建档时间 |
| `updated_at` | `DateTime` | 非空 | 设备状态最近重算时间 |

### 身份规则

```text
normalized_device_name = NFC(device_name).strip()
normalized_device_name = re.sub(r"\s+", " ", normalized_device_name)
device_key = sha256(normalized_device_name).hexdigest()
device_id  = sha256(f"{province}\n{device_key}").hexdigest()
```

`operator` 不参与 `device_key` 或 `device_id`。设备改名会被视为新设备；不做相似名称合并。

### 当前状态重算

设备当前状态只从该设备 `inventory_observations.status='active'` 的观测重算：

1. 最近观测按 `observed_at` 倒序，并以 `task_id` 升序作为稳定 tie-breaker。
2. `current_site_key`、`current_operator`、`last_seen_at`、`latest_task_id` 来自最近 `status='active'` 观测。
3. 当前版本来自最近 `status='active'` 且 `version_status='ok'` 的观测，可以早于最近一次缺版本观测。
4. `first_seen_at` 和 `observation_count` 只统计当前生效观测。
5. 局点变化和冲突按观测时间序列比较相邻 `operator`。

## `inventory_observations`

一次任务对一台设备的当前生效观测。同一 `task_id` 只允许一行。

| 字段 | 类型 | 约束 / 索引 | 说明 |
| --- | --- | --- | --- |
| `observation_id` | `VARCHAR(64)` | PK | 观测 ID；由 `task_id + device_id` 确定性派生 |
| `task_id` | `VARCHAR(64)` | UNIQUE；索引 | 来源任务；一个任务最多一条观测 |
| `device_id` | `VARCHAR(64)` | FK -> `inventory_devices.device_id`；索引 | 设备 |
| `province` | `VARCHAR(64)` | 非空 | 上传时省份 |
| `operator` | `VARCHAR(64)` | 非空 | 上传时运营商 |
| `site_key` | `VARCHAR(160)` | 非空 | `province:operator` |
| `observed_at` | `DateTime` | 非空 | 任务完成时间 |
| `task_status` | `VARCHAR(32)` | 非空 | 归档时的任务状态，固定 `completed` |
| `device_name` | `VARCHAR(256)` | 非空 | 规范化设备名 |
| `identity_status` | `VARCHAR(32)` | 非空 | `ok`；观测必须具备有效设备身份 |
| `version_status` | `VARCHAR(32)` | 非空 | `ok` / `missing` / `conflict` / `error` |
| `raw_version` | `VARCHAR(256)` | nullable | 成功解析时保存原始版本；冲突或缺失为 null |
| `version_key` | `VARCHAR(256)` | nullable | 词法排序键；第一版等于 `raw_version` |
| `version_source_files` | JSON | 非空 | 版本来源相对路径数组 |
| `device_snapshot` | JSON | 非空 | 设备名、规范化名、来源、证据和冲突详情 |
| `status` | `VARCHAR(32)` | 非空，默认 `active` | `active` / `retired` |
| `created_at` | `DateTime` | 非空 | 首次归档时间 |
| `updated_at` | `DateTime` | 非空 | 最近覆盖时间 |

### 观测状态

| 状态 | 含义 |
| --- | --- |
| `active` | 当前生效观测，参与设备状态和版本历史 |
| `retired` | 重跑后不再有效的历史观测；不参与状态重算，但保留审计 |

### 版本状态

| 状态 | 归档观测 | `raw_version` | 当前版本更新 |
| --- | --- | --- | --- |
| `ok` | 是 | 原始版本 | 是 |
| `missing` | 是 | null | 否 |
| `conflict` | 是 | null | 否；`device_snapshot.version.candidates` 保留冲突值 |
| `error` | 是 | null | 否；`device_snapshot.version.errors` 保留原因 |

## `inventory_parse_results`

任务级台账解析证据。一行代表一个任务的一次台账解析终态。

| 字段 | 类型 | 约束 / 索引 | 说明 |
| --- | --- | --- | --- |
| `task_id` | `VARCHAR(64)` | PK | 来源任务 |
| `package_kind` | `VARCHAR(32)` | 非空 | `inspection` / `log_supplement` |
| `status` | `VARCHAR(32)` | 非空，索引 | 见下方任务解析状态 |
| `parser_id` | `VARCHAR(64)` | 非空 | 固定 `site_device_lst_me`；日志补充包为 `none` |
| `parser_version` | `VARCHAR(32)` | 非空 | 解析器版本，初始 `1` |
| `schema_version` | integer | 非空 | `inventory.json` schema，初始 `1` |
| `site_status` | `VARCHAR(32)` | 非空 | `ok` / `missing` / `not_applicable` |
| `site_source` | `VARCHAR(32)` | 非空 | `upload_metadata` / `none` |
| `site_key` | `VARCHAR(160)` | nullable | 任务局点 |
| `province` | `VARCHAR(64)` | nullable | 上传省份 |
| `operator` | `VARCHAR(64)` | nullable | 上传运营商 |
| `device_status` | `VARCHAR(32)` | 非空 | `ok` / `missing` / `conflict` / `error` / `not_applicable` |
| `version_status` | `VARCHAR(32)` | 非空 | `ok` / `missing` / `conflict` / `error` / `not_applicable` |
| `source_files` | JSON | 非空 | 相对路径数组 |
| `conflicts` | JSON | 非空 | 身份、版本或局点冲突列表 |
| `errors` | JSON | 非空 | 解析错误列表 |
| `snapshot` | JSON | 非空 | 与 `inventory.json` 兼容的完整任务证据 |
| `created_at` | `DateTime` | 非空 | 首次写入时间 |
| `updated_at` | `DateTime` | 非空 | 最近写入时间 |

### 任务解析状态

| 状态 | 含义 |
| --- | --- |
| `archived` | 有效设备观测已归档 |
| `not_archived` | 巡检包未满足归档条件；任务仍完成 |
| `not_applicable` | 日志补充包不参与设备台账 |
| `failed` | 台账解析异常；任务不失败，但必须保留错误 |

### 质量状态映射

| `status` / 状态字段 | 质量问题 |
| --- | --- |
| `site_status=missing` | `missing_site` |
| `device_status=missing` | `missing_device_identity` |
| `version_status=missing` | `missing_version` |
| `version_status=conflict` | `version_conflict` |
| `device_status=conflict` | `device_identity_conflict` |
| 设备观测相邻 `operator` 不同 | `site_ownership_change` |
| `package_kind=log_supplement` | 不生成质量问题 |

## `inventory_change_audits`

观测新增、覆盖或退役的审计记录。审计只追加，不更新。

| 字段 | 类型 | 约束 / 索引 | 说明 |
| --- | --- | --- | --- |
| `audit_id` | `VARCHAR(64)` | PK | 审计 ID |
| `task_id` | `VARCHAR(64)` | 非空，索引 | 触发变更的任务 |
| `device_id` | `VARCHAR(64)` | 非空，索引 | 受影响设备 |
| `observation_id` | `VARCHAR(64)` | 非空 | 受影响观测 |
| `action` | `VARCHAR(32)` | 非空 | `create` / `update` / `retire` |
| `before_snapshot` | JSON | nullable | 覆盖或退役前观测快照；新增为 null |
| `after_snapshot` | JSON | 非空 | 变更后观测快照；退役时记录 retired 状态 |
| `changed_at` | `DateTime` | 非空 | UTC 审计时间 |

同一任务重复归档且前后快照一致时不新增审计。审计 ID 由 `task_id + observation_id + action + before/after 内容摘要` 确定性派生，避免重复重跑产生重复行。

## 版本历史模型

版本历史是 `inventory_observations` 的只读投影，不是独立表。

### 有效版本点

```text
status = 'active' AND version_status = 'ok'
```

按 `observed_at` 升序排列；同时间按 `task_id` 升序。相邻两个有效版本点之间计算：

| 比较 | `direction` |
| --- | --- |
| `current.raw_version > previous.raw_version` | `upgrade` |
| `current.raw_version < previous.raw_version` | `downgrade` |
| 相等 | `unchanged` |

### 观测缺口

`version_status` 为 `missing`、`conflict` 或 `error` 的 active 观测在时间线中保留：

| 状态 | 展示 |
| --- | --- |
| `missing` | `版本缺失` |
| `conflict` | `版本冲突`，并列出候选值和来源 |
| `error` | `版本解析失败`，并列出原因 |

两个有效版本之间存在缺口时返回 `has_gap=true`；缺口不参与方向判定。

## 归档状态机

### 巡检包

```text
任务 completed
  ├─ package_kind=inspection
  ├─ 解析 LST ME.txt
  ├─ site_status=ok?
  │     └─ 否 → parse_results=not_archived；无观测
  ├─ device_status=ok?
  │     ├─ 否 → parse_results=not_archived；既有 active 观测 retire + audit
  │     └─ 是 → upsert observation
  │             ├─ 无旧观测 → action=create
  │             ├─ 有旧观测且内容不同 → action=update
  │             └─ 有旧观测且内容相同 → 不新增审计
  └─ 重算 inventory_devices 当前状态
```

### 日志补充包

```text
任务 completed
  └─ package_kind=log_supplement
      → parse_results.status=not_applicable
      → site/device/version=not_applicable
      → 不写 inventory_observations
      → 不更新 inventory_devices
```

## 约束与保护

- 不建立 `sites` 表。
- 不允许人工版本输入；不把上传元数据 `version` 补入台账。
- 不从压缩包解析省份或运营商。
- 台账表不因任务输出清理而清空。
- `init_db()` 只增量建表和补列，不删除既有台账数据。
- 全量重跑覆盖观测必须在同一事务内完成观测写入与审计写入；设备状态重算在其后完成。
- 任务删除不作为本功能的台账删除入口；删除保留策略范围外。
