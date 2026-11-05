# Phase 1 数据模型：KPI 巡检结果判读工作台

**功能**：`041-kpi-result-workbench`
**日期**：2026-11-05
**输入**：[spec.md](./spec.md)、[research.md](./research.md)、[plan.md](./plan.md)
**实现状态**：规划模型，尚未修改 `app/models/db.py` 或数据库。

## 1. 模型目标

本模型把五个原本混在一起的概念拆开：

1. **任务**：一个包、一个 `task_id`、一个输出目录。
2. **网元类型作用域**：`network_element_type` 是 UMF、CSP 及未来运行时类型的隔离边界。
3. **巡检范围**：测量单元 `inspection_enabled` 是唯一日常启停粒度；绑定、派生和维护口径的 `enabled` 不再作为执行门禁。
4. **团队关注**：按网元类型共享的查看选择，不改变任务结果或报告。
5. **任务快照**：任务真正开始时冻结规则集合/版本、归属 revision、KPI 配置与指标集合，解释历史结果为何如此。

## 2. 全局不变量

- 所有 v6 业务表的主业务键必须显式包含 `network_element_type`，不得用 NULL、空字符串、`*` 或 `COMMON` 表示公共范围。
- 一个测量单元只属于一个网元类型；UMF 和 CSP 可拥有相同 `measurement_unit_id`、`metric_resource_id`，二者不是同一对象。
- 团队关注唯一身份为 `(network_element_type, measurement_unit_id, metric_resource_id)`；不包含 `device_id`、`task_id` 或用户名。
- 业务规则没有公共范围；零条归属记录即 `unassigned`，必须停止参与后续任务。
- 任务一旦冻结快照，后续关注、启停、规则归属和配置修改不得影响该任务已生成的结果。
- 任务 KPI 结果、证据和报告发布后不可原地改写；rerun/rebuild 只能通过新的发布事务替换指定范围。
- 所有时间字段以 UTC 存储并以 `_at` 结尾；接口输出使用 ISO 8601 UTC。
- v5 KPI 表、v5 规则状态与既有任务结果保留只读兼容，不作为 v6 巡检事实来源。

## 3. 关系总览

```text
tasks
├── task_rule_scope_snapshots 1 ── N task_rule_scope_items
├── task_kpi_scope_snapshots  1 ── N task_kpi_scope_items
├── task_kpi_metric_results_v6 1 ── N task_kpi_points_v6
└── kpi_legacy_recovery_audits / kpi_pending_attributions

kpi_v6_measurement_resources
└── kpi_v6_measurement_units
    ├── kpi_v6_measurement_bindings
    ├── kpi_v6_measurement_derived
    └── kpi_v6_metric_maintenance_configs

kpi_team_focus_revisions 1 ── N kpi_team_focus_items

kpi_rule_assignment_states 1 ── N kpi_rule_network_assignments
└── kpi_rule_assignment_audits
```

## 4. 表族与字段

### 4.1 `kpi_v6_measurement_resources`

**用途**：按网元类型隔离的测量单元/指标/单位资源目录。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，自增 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `resource_id` | VARCHAR(128) | 非空；同一网元类型内唯一 |
| `kind` | VARCHAR(8) | `mu` / `me` / `unit` |
| `name_zh` | VARCHAR(256) | 非空 |
| `name_en` | VARCHAR(256) | 非空 |
| `filename_fragment` | VARCHAR(256) | 可空 |
| `display_order` | INTEGER | 可空，非负 |
| `metric_group` | VARCHAR(64) | 可空 |
| `direction` | VARCHAR(16) | `higher_better` / `lower_better` / `neutral` / NULL |
| `importance` | VARCHAR(16) | `P0` / `P1` / `P2` / `normal` / NULL |
| `warning_threshold` | FLOAT | 可空 |
| `critical_threshold` | FLOAT | 可空 |
| `source` | VARCHAR(16) | `preset` / `discovered` / `manual` |
| `origin_task_id` | VARCHAR(64) | 可空，仅追溯 |
| `origin_file` | VARCHAR(512) | 可空 |
| `legacy_source_key` | VARCHAR(256) | 可空，迁移幂等键 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(network_element_type, resource_id)
UNIQUE(network_element_type, legacy_source_key) WHERE legacy_source_key IS NOT NULL
```

**校验**

- `resource_id` 不得为空或只包含空白。
- `kind=me` 时应具备可展示名称；阈值仅作指标目录默认值，最终判定以任务 KPI 配置快照为准。
- 该表没有 `enabled` 执行门禁；资源是否进入巡检由所属测量单元和绑定/派生定义决定。

### 4.2 `kpi_v6_measurement_units`

**用途**：保存测量单元巡检状态和配置来源；是唯一日常启停控制。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空，索引 |
| `name_zh` / `name_en` | VARCHAR(256) | 非空 |
| `inspection_enabled` | BOOLEAN | 非空，默认 TRUE |
| `revision` | INTEGER | 非空，默认 0，乐观锁 |
| `config_fingerprint` | VARCHAR(64) | 非空，SHA-256；配置变化时更新 |
| `source` | VARCHAR(16) | `preset` / `discovered` / `manual` |
| `origin_task_id` | VARCHAR(64) | 可空 |
| `legacy_source_key` | VARCHAR(256) | 可空 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(network_element_type, measurement_unit_id)
UNIQUE(network_element_type, legacy_source_key) WHERE legacy_source_key IS NOT NULL
```

**状态转换**

```text
inspection_enabled=false → true   # 后续任务纳入全部已配置指标
inspection_enabled=true → false   # 只影响后续任务，配置/关注/历史均保留
```

**校验**

- 启停操作不得删除绑定、派生、维护口径、关注或历史结果。
- `revision` 仅用于配置并发；每次启停或纳入配置变化递增。
- 基础指标数、派生指标数通过查询按当前定义计算，不持久化冗余计数。

### 4.3 `kpi_v6_measurement_bindings`

**用途**：自动入库发现的来源列与指标资源绑定。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空，索引 |
| `raw_source_name` | VARCHAR(256) | 非空 |
| `base_source_name` | VARCHAR(256) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 可空，异常时可为空 |
| `display_unit` | VARCHAR(64) | 可空 |
| `binding_state` | VARCHAR(16) | `candidate` / `confirmed` / `conflict` / `ignored` |
| `source_file` | VARCHAR(512) | 非空 |
| `origin_task_id` | VARCHAR(64) | 非空 |
| `revision` | INTEGER | 非空，默认 0 |
| `legacy_source_key` | VARCHAR(256) | 可空 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(network_element_type, measurement_unit_id, raw_source_name)
UNIQUE(network_element_type, legacy_source_key) WHERE legacy_source_key IS NOT NULL
```

**校验**

- 正常入库直接写 `confirmed`；前端不提供批量确认。
- `binding_state=conflict` 允许单条异常修正并记录 revision 变化；`ignored` 不进入有效指标集合。
- 该表没有 `enabled` 列，不能成为第二套巡检门禁。

### 4.4 `kpi_v6_measurement_derived`

**用途**：已定义的本地派生指标。源包直接提供的指标（包括成功率）必须先按 `base` 指标入库，不得在此重复定义或由 PatrolX 重算。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空，索引 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `numerator_metric_id` | VARCHAR(128) | 非空 |
| `denominator_metric_id` | VARCHAR(128) | 非空 |
| `template` | VARCHAR(32) | `success_rate` / `reverse_success_rate` |
| `definition_state` | VARCHAR(16) | `incomplete` / `defined` |
| `revision` | INTEGER | 非空，默认 0 |
| `legacy_source_key` | VARCHAR(256) | 可空 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(network_element_type, measurement_unit_id, metric_resource_id)
UNIQUE(network_element_type, legacy_source_key) WHERE legacy_source_key IS NOT NULL
```

**校验**

- 只有 `definition_state=defined` 的派生指标进入“已定义派生指标”集合。
- 分子/分母必须属于同一测量单元的指标资源；缺失时不阻止其他指标巡检，派生指标显示待配置。
- 该表没有 `enabled` 列；配置不完整由状态表达，不由启停字段排除。

### 4.5 `kpi_v6_metric_maintenance_configs`

**用途**：任务判定时冻结的指标维护口径。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `role` | VARCHAR(16) | `base` / `numerator` / `denominator` |
| `direction` | VARCHAR(16) | 可空 |
| `warning_threshold` / `critical_threshold` | FLOAT | 可空 |
| `daily_aggregation` | VARCHAR(16) | `latest` / `avg` / `sum` / `max` / `min` / 既有枚举 |
| `daily_change_threshold` | FLOAT | 可空，非负 |
| `daily_change_threshold_unit` | VARCHAR(16) | `pp` / `relative` / `auto` |
| `is_percentage` | BOOLEAN | 非空 |
| `zero_semantics` | VARCHAR(32) | 既有零值语义枚举 |
| `consistency_tolerance` | FLOAT | 非负 |
| `object_match_mode` | VARCHAR(32) | 既有对象匹配枚举 |
| `config_state` | VARCHAR(16) | `incomplete` / `ready` |
| `revision` | INTEGER | 非空，默认 0 |
| `legacy_source_key` | VARCHAR(256) | 可空 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(network_element_type, measurement_unit_id, metric_resource_id)
UNIQUE(network_element_type, legacy_source_key) WHERE legacy_source_key IS NOT NULL
```

**校验**

- `config_state=incomplete` 仍进入任务 KPI 范围，显示 `needs_config` / `unjudgeable`。
- 该表没有 `enabled` 列；旧 `enabled=false` 不阻断巡检。
- 维护配置更新写既有维护审计，并更新所在测量单元 `config_fingerprint` 和 revision。

### 4.6 `kpi_team_focus_revisions`

**用途**：每个网元类型一份共享关注的乐观锁版本。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `network_element_type` | VARCHAR(32) | 主键 |
| `revision` | INTEGER | 非空，默认 0，`CHECK(revision >= 0)` |
| `updated_at` | DATETIME | 非空，UTC |

**规则**

- 初始无关注项时 revision 为 0。
- 每次成功 PATCH 恰好递增 1；失败的冲突或校验不改变 revision。
- 不迁移旧 `enabled`；升级后所有网元类型初始关注为空。

### 4.7 `kpi_team_focus_items`

**用途**：团队按网元类型共享的关注选择。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `added_by` | VARCHAR(128) | 非空 |
| `added_at` | DATETIME | 非空，UTC |

**唯一约束**

```text
UNIQUE(network_element_type, measurement_unit_id, metric_resource_id)
```

**校验**

- 不包含 `task_id`、`device_id`、`username` 作为身份。
- 加入时要求指标属于指定任务当前可关注范围；移出可按数据库既有身份执行。
- 当前任务不存在的项保留，现有任务响应以 `availability=unavailable` 和 `reason` 展示。
- 删除/写关注不得触碰任务结果、报告、规则快照或测量单元启停。

### 4.8 `kpi_rule_assignment_states`

**用途**：保存每条规则的归属集合 revision，使“未归属”也有可并发校验的版本。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `rule_code` | VARCHAR(128) | 主键 |
| `revision` | INTEGER | 非空，默认 0，`CHECK(revision >= 0)` |
| `assignment_state` | VARCHAR(16) | `unassigned` / `assigned` |
| `updated_by` | VARCHAR(128) | 非空 |
| `updated_at` | DATETIME | 非空，UTC |

**规则**

- 规则首次注册不插入归属；读取时 `revision=0, state=unassigned`。
- 任意写入（包括清空最后归属）递增该规则 revision。
- 规则代码必须在当前注册表中存在；已下线历史规则不可重新归属。

### 4.9 `kpi_rule_network_assignments`

**用途**：业务规则到网元类型的运行时共享归属。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `rule_code` | VARCHAR(128) | 非空，索引 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `rule_revision` | INTEGER | 非空；属于该规则当前 revision |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(rule_code, network_element_type)
```

**校验**

- 一个规则可有多行；零行表示未归属。
- 不存在公共范围、全类型通配或由规则 Python 声明的默认类型。
- 同一规则所有行的 `rule_revision` 必须一致；由服务层事务保证。
- 清空最后一行前必须显式 `confirm_unassign=true`；审计必须保留变更前集合。

### 4.10 `kpi_rule_assignment_global_state`

**用途**：任务快照使用的全局归属 revision。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，固定为 1 |
| `revision` | INTEGER | 非空，默认 0 |
| `updated_at` | DATETIME | 非空，UTC |

**规则**

- 任意成功规则归属写入后递增 1；一次批量写入包含多条规则时，全局 revision 只递增 1。
- 任务冻结时记录当前值；不要求后续读当前值解释历史。
- 单规则更新、批量更新和清空归属都在同一事务内同时更新规则 revision 和全局 revision。

### 4.11 `kpi_rule_assignment_audits`

**用途**：规则归属变更的追加审计。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `audit_id` | VARCHAR(64) | 主键，服务端稳定 ID |
| `rule_code` | VARCHAR(128) | 非空，索引 |
| `before_network_element_types` | JSON | 变更前有序唯一数组 |
| `after_network_element_types` | JSON | 变更后有序唯一数组 |
| `rule_revision` | INTEGER | 非空 |
| `global_revision` | INTEGER | 非空 |
| `actor` | VARCHAR(128) | 非空 |
| `source` | VARCHAR(32) | `ui` / `api` / `migration` |
| `result` | VARCHAR(16) | `success` / `failed` |
| `error_code` | VARCHAR(64) | 可空 |
| `idempotency_key` | VARCHAR(128) | 可空 |
| `created_at` | DATETIME | 非空，UTC |

**唯一约束**

```text
UNIQUE(idempotency_key) WHERE idempotency_key IS NOT NULL
```

**规则**

- 审计不可更新或删除。
- 失败写入也必须保留 actor、请求集合和错误码；不得改变 assignment 表。

### 4.12 `task_rule_scope_snapshots`

**用途**：冻结任务真正开始时的普通业务规则范围。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `task_id` | VARCHAR(64) | 主键，FK `tasks.task_id` |
| `network_element_type` | VARCHAR(32) | 可空，仅日志包未指定规则类型时为空 |
| `assignment_revision` | INTEGER | 非空 |
| `registry_fingerprint` | VARCHAR(64) | 非空，SHA-256 |
| `trigger` | VARCHAR(32) | `api` / `cli` / `rerun` / `rebuild` |
| `source` | VARCHAR(32) | 触发入口 |
| `frozen_at` | DATETIME | 非空，UTC |
| `snapshot_state` | VARCHAR(16) | `frozen` / `invalid` / `completed` |

**规则**

- 一个任务只有一条快照；全量重建替换该任务快照，不新建任务。
- `network_element_type IS NULL` 且任务为日志补充包时，`task_rule_scope_items` 必须为空。
- 该表存在与否是 v6 读取新任务的必要条件；旧任务无此表行时返回 `task_result_requires_rebuild`。

### 4.13 `task_rule_scope_items`

**用途**：快照内每条普通业务规则的版本与执行元数据。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `task_id` | VARCHAR(64) | 非空，FK |
| `rule_code` | VARCHAR(128) | 非空 |
| `rule_version` | VARCHAR(64)/INTEGER | 与规则注册元数据类型一致 |
| `category` | VARCHAR(32) | 非空 |
| `priority` | INTEGER | 非空 |
| `execution_order` | INTEGER | 非空 |
| `assignment_snapshot` | JSON | 冻结时归属集合/来源 |

**唯一约束**

```text
UNIQUE(task_id, rule_code)
```

**规则**

- 只包含当前任务网元类型命中的普通规则；未归属/不匹配规则不得写入。
- 隐藏解压/分类单元不在此表。
- 单规则重跑前校验 `rule_code` 存在且当前注册表版本等于 `rule_version`。

### 4.14 `task_kpi_scope_snapshots`

**用途**：冻结任务 KPI 范围的整体配置指纹和版本。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `task_id` | VARCHAR(64) | 主键，FK |
| `network_element_type` | VARCHAR(32) | 空任务可空；有 KPI 结果时非空 |
| `team_focus_revision` | INTEGER | 冻结时关注 revision，仅解释查看上下文，不决定执行范围 |
| `config_fingerprint` | VARCHAR(64) | 非空，SHA-256 |
| `data_date` | DATE | 可空；无点时为空 |
| `frozen_at` | DATETIME | 非空，UTC |
| `snapshot_payload` | JSON | 任务级计量上下文、时间来源、范围说明 |

**规则**

- 测量单元、绑定、派生和维护口径的当前配置变化不会改写历史快照。
- 团队关注后续变更不改变该任务的指标结果；只影响当前查看时的关注集合。
- 快照必须记录启用单位集合和配置指纹，以便解释为何某指标进入/未进入任务。

### 4.15 `task_kpi_scope_items`

**用途**：冻结任务应巡检的测量单元/指标集合及配置。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `task_id` | VARCHAR(64) | 非空，FK |
| `network_element_type` | VARCHAR(32) | 非空 |
| `measurement_unit_id` | VARCHAR(128) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `metric_kind` | VARCHAR(16) | `base` / `derived` |
| `config_snapshot` | JSON | 阈值、方向、聚合、零值语义、分子分母等 |
| `scope_status` | VARCHAR(16) | `ready` / `needs_config` / `unjudgeable` |

**唯一约束**

```text
UNIQUE(task_id, measurement_unit_id, metric_resource_id)
```

**规则**

- 只包含冻结时启用测量单元下的已确认基础指标和已定义派生指标。
- `scope_status` 为 `needs_config` / `unjudgeable` 的项仍须存在。
- 不包含已停用测量单元、未确认绑定或未定义派生；这些项在任务快照中不得伪造为 `skip`。

### 4.16 `task_kpi_metric_results_v6`

**用途**：冻结每个指标的最终判定与证据摘要，供工作台和报告稳定读取。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `task_id` | VARCHAR(64) | 非空，索引 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `measurement_unit_id` | VARCHAR(128) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `source_rule_code` | VARCHAR(128) | 可空 |
| `decision` | VARCHAR(16) | `pass` / `warn` / `fail` / `unjudgeable` / `needs_config` / `not_applicable` |
| `special_state` | VARCHAR(24) | 可空；`no_action` / `not_applicable` / `no_baseline` / `all_zero` / `zero_denominator` / `no_data` / `unavailable` |
| `yesterday_trend` | VARCHAR(16) | 可空；`improved` / `stable` / `worsened` / `observe` / `no_baseline` |
| `needs_attention_group` | VARCHAR(24) | 可空；`failure` / `warning` / `trend_degraded` / `unjudgeable` / `needs_config` |
| `today_value` / `yesterday_value` / `change` | FLOAT | 可空 |
| `unit` | VARCHAR(64) | 可空 |
| `importance` | VARCHAR(16) | 可空 |
| `reason` | TEXT | 非空，展示原因 |
| `effective_point_count` | INTEGER | 非负 |
| `result_payload` | JSON | 完整证据快照 |
| `result_fingerprint` | VARCHAR(64) | 非空 |
| `published_at` | DATETIME | 非空，UTC |

**唯一约束**

```text
UNIQUE(task_id, network_element_type, measurement_unit_id, metric_resource_id)
UNIQUE(task_id, result_fingerprint)
```

**规则**

- `needs_attention_group` 唯一；有多信号时由服务端按固定优先级生成。
- `all_zero`、`zero_denominator`、`no_baseline` 等状态不得被折叠成 `pass`。
- 单规则重跑只替换其 `source_rule_code` 产生的指标结果；其他规则/指标保留。
- 该表与 `task_kpi_points_v6` 在同一发布事务写入。

### 4.17 `task_kpi_points_v6`

**用途**：任务 KPI 历史点的 v6 复合作用域镜像。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `task_id` | VARCHAR(64) | 非空，索引 |
| `network_element_type` | VARCHAR(32) | 非空，索引 |
| `source_rule_code` | VARCHAR(128) | 可空 |
| `measurement_unit_id` | VARCHAR(128) | 非空 |
| `metric_resource_id` | VARCHAR(128) | 非空 |
| `object_key` | VARCHAR(256) | 默认 `__all__` |
| `period_minutes` | INTEGER | 可空 |
| `measured_at` | DATETIME | 非空，UTC，索引 |
| `value` | FLOAT | 可空 |
| `source_file` | VARCHAR(512) | 可空 |
| `line_number` | INTEGER | 可空 |
| `point_fingerprint` | VARCHAR(64) | 非空 |

**唯一约束**

```text
UNIQUE(task_id, point_fingerprint)
INDEX(task_id, network_element_type, measurement_unit_id, metric_resource_id, measured_at)
```

**`point_fingerprint` 组成**

```text
SHA-256(
  task_id | network_element_type | source_rule_code | measurement_unit_id |
  metric_resource_id | object_key | period_minutes | measured_at(UTC) |
  canonical value | source_file | line_number
)
```

**规则**

- 所有读取必须带 `network_element_type`；禁止沿用只按 measurement unit/metric 的查询。
- `measured_at` 统一 UTC；输入时区解析在服务层完成。
- 发布使用幂等指纹，避免单规则重跑或重启重复插入。

### 4.18 `kpi_legacy_recovery_audits`

**用途**：记录历史指标/绑定/派生 `enabled=false` 的语义恢复。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `source_table` | VARCHAR(64) | 非空 |
| `source_record_id` | VARCHAR(128) | 非空 |
| `source_key` | VARCHAR(256) | 非空，稳定幂等键 |
| `network_element_type` | VARCHAR(32) | 可空，未归属时为空 |
| `measurement_unit_id` | VARCHAR(128) | 可空 |
| `metric_resource_id` | VARCHAR(128) | 可空 |
| `object_kind` | VARCHAR(16) | `metric` / `binding` / `derived` |
| `before_snapshot` | JSON | 非空 |
| `result` | VARCHAR(16) | `pending` / `running` / `recovered` / `failed` / `skipped` |
| `error_code` | VARCHAR(64) | 可空 |
| `attempt_count` | INTEGER | 非负 |
| `actor` | VARCHAR(128) | 可空 |
| `source` | VARCHAR(32) | `migration` / `ui` / `api` |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(source_key)
```

**状态转换**

```text
pending → running → recovered
                  ↘ failed → running(重试)
                  ↘ skipped(无需恢复)
```

**规则**

- 一个对象一条审计，支持部分成功与重试。
- 恢复只改变“该历史停用是否继续抑制巡检”的语义，不改写既有任务结果或 v5 行。
- 恢复不得自动启用测量单元，也不得自动生成团队关注。

### 4.19 `kpi_pending_attributions`

**用途**：迁移时无法唯一证明网元类型的配置，等待人工指定。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `source_table` | VARCHAR(64) | 非空 |
| `source_record_id` | VARCHAR(128) | 非空 |
| `source_key` | VARCHAR(256) | 非空，稳定幂等键 |
| `source_payload` | JSON | 原记录快照 |
| `candidate_network_element_types` | JSON | 候选数组，可为空 |
| `reason` | VARCHAR(64) | `missing_product` / `ambiguous_product` / `orphan_reference` |
| `resolution_state` | VARCHAR(16) | `pending` / `assigned` / `materialized` / `failed` |
| `assigned_network_element_type` | VARCHAR(32) | 可空 |
| `attempt_count` | INTEGER | 非负 |
| `last_error` | TEXT | 可空 |
| `idempotency_key` | VARCHAR(128) | 非空 |
| `created_at` / `updated_at` | DATETIME | UTC |

**唯一约束**

```text
UNIQUE(source_key)
UNIQUE(idempotency_key)
```

**状态转换**

```text
pending → assigned → materialized
                    ↘ failed → assigned(重试)
```

**规则**

- 未完成归属的配置不进入任何 v6 巡检范围。
- 指定类型后重新生成 v6 资源/绑定/派生/维护配置；不默认 UMF 或 CSP。
- 部分成功保留成功项，失败项可重试。

## 5. 任务范围快照状态

### 5.1 规则快照

```text
任务受理(pending)
  → 真正开始执行
  → 事务冻结 global assignment revision + 当前类型规则集
  → frozen
  → 执行成功/失败 → completed
```

- 排队期间不生成最终规则集。
- 快照内规则版本不匹配时标记 `invalid`，任务失败并提示全量重建。
- 单规则/增量重跑只允许读取 frozen/completed 快照中的规则。

### 5.2 KPI 快照

```text
任务开始
  → 解析启用测量单元
  → 收集已确认基础指标 + 已定义派生指标
  → 快照维护口径与配置指纹
  → 写入 task_kpi_scope_items
  → INSPECT
  → 写 task_kpi_metric_results_v6 + task_kpi_points_v6
```

- KPI 范围不随关注 revision 改变；关注只决定工作台默认视图。
- 无冻结 KPI 快照的旧任务不能被 v6 读取。

## 6. 团队关注操作事务

```text
BEGIN
  SELECT revision FROM kpi_team_focus_revisions WHERE network_element_type=:type
  IF expected_revision != revision → 409, ROLLBACK
  VALIDATE add[] 属于 task_id 当前可关注范围
  DEDUPE add/remove identities
  DELETE WHERE identity IN remove[]
  INSERT ... ON CONFLICT DO NOTHING FOR add[]
  UPDATE revision = revision + 1, updated_at = now(UTC)
COMMIT
```

- `remove[]` 可删除当前任务不可用但数据库存在的关注项。
- 同一 identity 同时出现在 add/remove 时请求无效（400），不得由顺序决定结果。
- 失败不得递增 revision。

## 7. 规则归属操作事务

```text
BEGIN
  LOAD rule state (default revision=0, unassigned)
  IF expected_revision != state.revision → 409 rule_assignment_revision_conflict
  VALIDATE all network types active in runtime dictionary
  IF new set empty AND confirm_unassign != true → 400 rule_unassign_confirmation_required
  DELETE old assignment rows
  INSERT new assignment rows with next rule revision
  UPSERT state + global revision
  APPEND success audit
COMMIT
```

- 规则不存在、隐藏规则或平台技术单元不可归属。
- 批量写入逐条校验 revision，并在一个事务中全成或全败；审计逐规则追加。
- 任一操作不得读取 `RuleState.enabled` 或 `scan_rules.disabled_rules`。

## 8. 发布与查询约束

### 8.1 发布

- 新任务/全量重建：在事务内替换该 `task_id` 的全部 v6 指标结果与点，再更新任务摘要。
- 单规则/增量重跑：只替换对应 `source_rule_code` 的结果与点，保留其他规则和 KPI 行。
- 发布前校验每个结果行的 `network_element_type`、测量单元和指标属于该任务 KPI 快照。
- `task_kpi_metric_results_v6` 与 `task_kpi_points_v6` 同事务提交；任一失败不得留下半套结果。

### 8.2 查询

- 工作台汇总、列表、证据都必须以 `task_id` 取快照并按 `network_element_type` 查询。
- “全部指标”来自 `task_kpi_scope_items`，不是关注表。
- “团队关注”来自 `kpi_team_focus_items` 与任务快照的交集；不可用项仍展示。
- “需处理”在服务端用 `needs_attention_group IS NOT NULL` 过滤，前端不重新判定。
- 证据或技术分析查询失败只返回局部错误，不影响 summary/list。

## 9. 迁移与幂等

### 9.1 迁移输入

- `kpi_measurement_resources`
- `kpi_measurement_bindings`
- `kpi_measurement_derived`
- `kpi_metric_maintenance_configs`
- `task_kpi_points`
- `rules` / `rule_states` / 任务元数据中的 product

### 9.2 归属推断

只允许“可证明唯一”：

1. 资源带有唯一 `origin_task_id`，且该任务的 `product` 明确；
2. 绑定来源任务的 `product` 唯一；
3. 配置通过同一测量单元的已证明资源链推导出唯一类型；
4. 同一源记录的所有证据指向同一类型。

以下情况进入待归属：

- 无 product；
- 多个候选 product；
- 关联任务缺失或产品冲突；
- 按复合键可能同时落到 UMF/CSP。

不得用“先到先得”、默认 UMF/CSP、任务列表首项或空公共值兜底。

### 9.3 迁移幂等键

```text
resource:   resource:<source_key>
unit:       unit:<source_key>
binding:    binding:<source_key>
derived:    derived:<source_key>
maintenance: maintenance:<source_key>
recovery:   recovery:<source_table>:<source_record_id>
pending:    pending:<source_table>:<source_record_id>
```

- 重复启动时已存在记录不得覆盖人工修正结果。
- 迁移写入的审计必须标记 `source=migration`。
- v5 表不清空、不重命名字段、不改变既有 API 含义。

### 9.4 启动顺序

```text
legacy rebuild (仅旧结构)
  → create_all (含 v6 表)
  → 既有增量列/约束
  → task.rule_network_element_type 列
  → migrate_kpi_v6()
  → ensure_backfilled()
```

## 10. 数据校验汇总

| 校验 | 错误行为 |
| --- | --- |
| `network_element_type` 不在运行时字典 | 400 `invalid_network_element_type` |
| 同一请求跨网元类型引用测量单元/指标 | 400 `cross_network_element_scope` |
| 关注 revision 不匹配 | 409 `team_focus_revision_conflict` |
| 规则归属 revision 不匹配 | 409 `rule_assignment_revision_conflict` |
| 规则不存在/不可归属 | 404 `rule_not_found` / 400 `rule_not_assignable` |
| 清空最后归属未确认 | 400 `rule_unassign_confirmation_required` |
| 旧任务无 v6 快照 | 409 `task_result_requires_rebuild` |
| 重跑规则不在快照 | 409 `rule_not_in_task_scope` |
| 快照规则版本与当前注册表不一致 | 409 `rule_snapshot_version_mismatch` |
| 日志包非法规则类型 | 400 `invalid_rule_network_element_type` |
| 巡检包携带规则类型 | 400 `metadata_not_applicable` |
| 同名日志包规则类型不同 | 409 `package_rule_network_element_type_conflict` |

## 11. 不保留的数据语义

以下字段/能力不得出现在 v6 执行路径：

- 公共规则或公共 KPI 归属；
- 指标、绑定、派生、维护配置的 `enabled` 巡检门禁；
- 个人关注、任务局部关注、设备级关注；
- 全局规则启停与新网元归属并存的第二套开关；
- 旧健康分、风险排序、单任务趋势一级入口；
- 旧任务兼容快照或从 v5 即时推导 v6 结果。
