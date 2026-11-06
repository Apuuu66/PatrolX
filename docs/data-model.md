# PatrolX 契约数据模型

本文档说明巡检输出的四层契约结构、SQLite 持久化角色与磁盘现场组织。机器可读契约以
[`docs/api/openapi.yaml`](api/openapi.yaml) 为准；界面展示数据的唯一来源是 SQLite，
`output/` 文件是执行期现场（见第 13 节）。

## 1. 层级结构

```text
InspectionTask
└── SystemInspection
    └── RuleResult
        ├── Metric
        └── Finding[]
```

| 层级 | 模型 | 说明 |
| --- | --- | --- |
| 任务 | `InspectionTask` | 一次巡检执行，对应一个压缩包 |
| 系统 | `SystemInspection` | 一个包的完整巡检上下文 |
| 规则 | `RuleResult` | 一条规则的结果、指标和发现 |
| 发现 | `Finding` | 具体问题点，含证据、影响和建议 |

## 2. InspectionTask

核心字段：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 任务 ID |
| `name` | 任务名 |
| `mode` | `local` / `online` |
| `status` | `pending` / `running` / `completed` / `failed` |
| `trigger` | `api` / `cli` / `rerun` |
| `created_at` | 创建时间，UTC；不随重跑/重建变化 |
| `completed_at` | 最近一次运行的完成时间，UTC |
| `last_run_at` | 最近一次运行的开始时间，UTC；从未运行为 `null` |
| `duration_ms` | 最近一次运行的耗时（毫秒）；仅终态写入，运行中与从未运行为 `null` |
| `stats` | 跨系统状态汇总 |
| `system` | 单系统巡检结果；当前模型为 1:1 |

状态机：

```text
pending → running → completed
                 ↘ failed
```

`InspectionTask.stats.systems` 表示系统数量。单系统任务下，其余状态统计与系统
`summary` 一致。

## 3. SystemInspection

核心字段：

| 字段 | 说明 |
| --- | --- |
| `package_file` | 原始包文件名 |
| `package_checksum` | 原始包校验和 |
| `version` | 可选版本信息 |
| `status` | `completed` / `failed` |
| `summary` | 规则状态统计 |
| `rules[]` | 规则结果列表 |
| `customer{}` | 可选省份/运营商/网元类型等扩展字典；展示名统一为“网元类型”，后端字段为 `product` |

统计口径：

```text
summary.total = pass + warn + fail + error + skip
```

`total` 只统计进入 `system.rules` 的活动普通规则结果（包括 `skip`）。隐藏的 `pkg.extract.main` 和 `pkg.extract.classification` 不进入普通规则结果或该统计。

## 4. RuleResult

核心字段：

| 字段 | 说明 |
| --- | --- |
| `code` | 规则 code，如 `kpi.measurement_units` |
| `name` | 展示名 |
| `category` | `log` / `kpi` / `traffic` / `alarm` / `config` / `resource` / `other` |
| `priority` | P0=0，P1=1，P2=2 |
| `execution_order` | 实际执行顺序 |
| `status` | `pass` / `warn` / `fail` / `error` / `skip` |
| `severity` | 规则严重程度 |
| `summary` | 一句话结果 |
| `skip_reason` | `status=skip` 时必填 |
| `executed_at` | 执行时间，UTC |
| `duration_ms` | 执行耗时 |
| `metrics[]` | 指标列表 |
| `findings[]` | 发现列表 |
| `metadata{}` | 规则自定义扩展数据 |

`RuleCategory` 的完整枚举保留用于历史结果、分类落位和契约兼容，不代表每类都有活动规则。当前活动普通规则仅 `kpi.measurement_units`；已删除规则的持久化结果仍可通过规则结果接口只读获取，但不能重跑或重建。隐藏的 `pkg.extract.main` 与 `pkg.extract.classification` 不进入普通规则目录或规则结果展示。

状态语义：

| 状态 | 语义 | 前端色 |
| --- | --- | --- |
| `pass` | 通过 | 绿 |
| `warn` | 告警 | 黄 |
| `fail` | 失败 | 红 |
| `error` | 执行异常 | 灰 |
| `skip` | 跳过 | 蓝 |

输出契约要求：

- `pass` / `warn` / `fail` 必须产出声明中的 metrics。
- `skip` / `error` 豁免输出契约校验。
- `skip` 必须提供原因。
- `error` 应尽量记录异常和错误码。
- 规则逻辑变化必须升级 `rule_version`。

## 5. Metric

| 字段 | 说明 |
| --- | --- |
| `key` | 契约级稳定标识 |
| `label` | 展示名 |
| `value` | 当前值 |
| `unit` | 单位 |
| `threshold{}` | 阈值，如 `max` / `min` |
| `baseline` | 基线 |
| `series[]` | 趋势数据 |

约束：

- `key` 必须稳定，跨任务、跨系统趋势聚合依赖它。
- 修改 metric 含义属于破坏性契约变更。
- 单位变化必须同步契约与展示层。

## 6. Finding

| 字段 | 说明 |
| --- | --- |
| `finding_id` | 单规则结果内唯一 |
| `title` | 问题标题 |
| `severity` | 问题严重程度 |
| `source_file` | 来源文件或包内路径 |
| `evidence` | 截断后的证据 |
| `details` | 详细说明 |
| `recommendation` | 处理建议 |
| `metrics[]` | 关联指标 |

要求：

- 必须能通过 `source_file` 和 `evidence` 追溯。
- evidence 默认截断，完整上下文保留在源文件。
- 告警、错误、资源异常等结论应尽量携带触发值或阈值。

## 7. Source Patterns 与 Prepared Data

规则不消费中间产物契约，也不依赖其他规则实现。

- `source_patterns[]` 是 Python regex，执行器对 `TaskFileCatalog` 中的 `/` 归一化相对路径执行 `re.fullmatch()`。
- 路径分隔符统一为 `/`，模式不得造成路径穿越或逃逸任务目录。
- 执行器把匹配到的相对路径交给规则；当前活动示例为 `^kpi/.*\.csv$`、`^traffic/.*\.csv$`。
- 分类目录仍保留 `logs/`、`alarm/` 等物理结构，用于安全保存证据和读取历史结果，但当前没有对应活动普通规则。
- 普通规则可以声明至多一个私有 prepare；prepare 继承 owner 的 `source_patterns` 和 priority。
- prepared 数据只保存在 `output/<task_id>/prepared/<owner_code>/`，只有 owner 规则可读取，不写入规则契约，也不作为公共输入。
- 无匹配文件、格式不适用或解析失败时必须返回 `skip` 和非空原因。

## 8. Manifest v5 与分类审计

`output/<task_id>/manifest.json` 是分类现场唯一发布凭据。目录扫描、临时文件、旧版清单和规则目录都不是分类事实。

### 发布模型

```text
原始包（只读）
  └─ pkg.extract.main
       └─ .main/ 证据现场
            └─ pkg.extract.classification
                 ├─ .classification.staging/ 目标根 + catalog 构建
                 ├─ 目标根交换（可逆）
                 └─ manifest.json 原子发布
```

- 分类只读取 `.main/`，不得重新消费外部输入。
- staging 摘要复核通过后才交换目标根；manifest 使用 `os.replace()` 原子发布。
- 发布失败按目标根交换的逆序回滚；成功后只清理 allowlist 内的 legacy 分类根。
- 发布不得修改 `.main/`、`prepared/`、`rules/`、`reports/`、`task.json` 或 `execution.log`。

### 顶层结构

顶层严格键集合：

```text
version
main
product
classification
path_limit
entries
ignored
conflicts
failures
catalog
summary
```

| 字段 | 说明 |
| --- | --- |
| `version` | 固定为 `5`；v1-v4 一律不可复用 |
| `main` | 原始包 checksum、证据路径、文件数、evidence fingerprint 和本次是否复用 |
| `product` | 巡检包为 `UMF`/`CSP`；日志补充包为 `null` |
| `classification` | package kind、profile、ruleset、配置/发布/path-limit 指纹、scene root、目标根和固定预算 |
| `path_limit` | 快照、fingerprint 与统一路径上限 |
| `entries[]` | 成功落位记录：来源、成员、route、product、category、target、action、status、reason、size 和 SHA-256 |
| `ignored[]` | 规则或 selection 明确忽略的来源/成员，必须带稳定 reason |
| `conflicts[]` | 目标重名且已按来源摘要稳定消歧的记录，不覆盖既有文件 |
| `failures[]` | 单归档/成员局部失败，使用稳定 error code 和非空 reason |
| `catalog[]` | 普通规则唯一可见的成功落位文件清单 |
| `summary` | entries/ignored/conflicts/failures/catalog 计数，以及按 route/category/action/status 的稳定汇总 |

### 复用与重建矩阵

| 条件 | 处理 |
| --- | --- |
| manifest v5 有效，checksum/product/kind/配置指纹/发布指纹/path-limit/evidence fingerprint/target roots/catalog 摘要全部一致 | 复用分类现场 |
| 仅 YAML 注释、空白、映射键顺序或 route 顺序变化 | fingerprint 不变，复用 |
| 任一有效 route、target、profile、action、预算或 path limit 语义变化 | 从 `.main/` 全量重建分类现场 |
| product 或 package kind 变化 | 从 `.main/` 全量重建分类现场 |
| manifest 缺失、损坏、版本低于 v5、summary 不一致或 catalog 摘要不符 | 从 `.main/` 全量重建 |
| `.main/` 缺失、含链接/非普通文件、指纹不可计算或不一致 | 复核原包 checksum 后重建证据现场，再重建分类现场 |
| 原始包 checksum 冲突 | 拒绝复用/重建并返回稳定冲突错误，不修改原包 |

单成员损坏、预算拒绝或目标失败写 `failures[]`，classification 为 `WARN`，其他合法文件继续发布。
配置无效、证据不可建立、catalog 预校验失败或原子发布失败为 `ERROR`，prepare/inspect 不得执行。
同一包、同一元数据和同一有效配置重复执行必须复用或产生完全相同的目标、audit 和 catalog。

## 9. TaskFileCatalog

`TaskFileCatalog` 是执行期内存清单，不属于 API、SQLite 或磁盘契约。

- 构建时机：`pkg.extract.main` 与 `pkg.extract.classification` 到达终态后；单规则重跑先确保 v5 现场可复用。
- 唯一来源：有效 manifest v5 的 `catalog[]`，不得扫描分类目录或回退旧 manifest。
- 路径形式：相对 `output/<task_id>/` 的 POSIX 路径，稳定排序、去重。
- 摘要校验：每个 catalog 项必须是普通文件，size 和 SHA-256 与磁盘一致，summary 与数组一致。
- 排除范围：`.main/`、manifest、staging、`prepared/`、任务元数据、规则结果、报告和执行日志。
- 安全约束：拒绝符号链接、越界路径、非法正则、路径穿越和不一致 catalog。

## 10. 文件组织

```text
output/<task_id>/
├── task.json
├── system.json
├── manifest.json
├── .main/
├── alarm/
├── basic/
├── chr/
├── debug/
├── host-debug/
├── host-system/
├── kpi/
├── logs/
├── mml/
├── operation-log/
├── other/
├── status/
├── rules/<rule_code>.json
├── report.html
└── execution.log
```

`.classification.staging/` 只在分类执行期间存在，不得作为已发布现场读取。目标根是 manifest
`classification.target_roots[]` 与配置模板的交集；目录存在本身不证明分类有效。

规则结果文件：

```text
output/<task_id>/rules/<code>.json
```

支持单规则重跑后原地更新。

规则私有 prepared 数据目录：

```text
output/<task_id>/prepared/<owner_code>/
```

该目录属于内部运行时数据，不进入公共 API 契约。

现场与数据库的角色边界：

- `output/<task_id>/` 是执行期现场，不是界面查询依据；规则结果、KPI 历史点、任务元数据在任务终态时同步快照到 SQLite。
- 现场按留存策略只保留最近 50 个任务；被清理后上述数据仍可从 DB 完整读取，规则结果文件缺失不影响规则详情、发现与指标展示。
- 执行日志（`execution.log`）与报告（`report.html`）只存在于现场，不入库；现场缺失时对应接口返回 410 `scene_cleaned`。

## 11. 示例

以下为 `RuleResult` 结构示例，不代表存在多类活动规则。

```json
{
  "task_id": "task-20260909-001",
  "status": "completed",
  "stats": {
    "systems": 1,
    "pass": 8,
    "warn": 2,
    "fail": 1,
    "error": 0,
    "skip": 1
  },
  "system": {
    "package_file": "customer_a.tar.gz",
    "version": "R12",
    "status": "completed",
    "summary": {
      "total": 12,
      "pass": 8,
      "warn": 2,
      "fail": 1,
      "error": 0,
      "skip": 1
    },
    "rules": [
      {
        "code": "kpi.measurement_units",
        "name": "KPI 测量单元检查",
        "category": "kpi",
        "priority": 1,
        "execution_order": 3,
        "status": "warn",
        "severity": "medium",
        "summary": "KPI 测量单元检查完成：1 个文件未归属测量单元",
        "metrics": [
          {
            "key": "matched_files",
            "label": "匹配文件数",
            "value": 3,
            "unit": "个"
          },
          {
            "key": "unmatched_files",
            "label": "未匹配文件数",
            "value": 1,
            "unit": "个"
          },
          {
            "key": "skipped_files",
            "label": "周期跳过文件数",
            "value": 0,
            "unit": "个"
          },
          {
            "key": "measurement_units",
            "label": "测量单元数",
            "value": 2,
            "unit": "个"
          }
        ],
        "findings": [
          {
            "finding_id": "f-001",
            "title": "KPI 文件未归属测量单元",
            "severity": "medium",
            "source_file": "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv",
            "evidence": "测量开始时间,测量结束时间,周期(分钟),...",
            "recommendation": "确认测量单元与指标绑定"
          }
        ]
      }
    ]
  }
}
```

## 12. KPI v6 作用域、快照与结果工作台

KPI 数据按三个维度隔离：`network_element_type` 是网元类型边界，测量单元是巡检启停粒度，`task_id` 是结果与证据边界。
任务结果、团队关注和规则归属都不使用“公共”范围兜底。

### 12.1 表族

| 表 | 用途 |
| --- | --- |
| `kpi_v6_measurement_resources` | 按网元类型隔离的测量单元、指标和单位资源目录 |
| `kpi_v6_measurement_units` | 测量单元及唯一巡检开关 `inspection_enabled`、revision、配置指纹 |
| `kpi_v6_measurement_bindings` | 原始指标列到指标资源的自动绑定、冲突与单条修正 |
| `kpi_v6_measurement_derived` | 受控成功率/反向成功率派生定义 |
| `kpi_v6_metric_maintenance_configs` | 日聚合、方向、阈值、零值语义、一致性等判定口径 |
| `kpi_team_focus_revisions` | 每个网元类型一份共享关注的乐观锁 revision |
| `kpi_team_focus_items` | 共享关注项 |
| `kpi_rule_assignment_states` / `kpi_rule_network_assignments` | 业务规则逐条归属与 revision |
| `kpi_rule_assignment_global_state` / `kpi_rule_assignment_audits` | 任务快照使用的全局 revision 与追加审计 |
| `task_rule_scope_snapshots` / `task_rule_scope_items` | 任务启动时冻结的规则集合、版本和归属 |
| `task_kpi_scope_snapshots` / `task_kpi_scope_items` | 任务启动时冻结的 KPI 配置指纹和指标集合 |
| `task_kpi_metric_results_v6` / `task_kpi_points_v6` | v6 指标最终判定与历史点 |
| `kpi_legacy_recovery_audits` / `kpi_pending_attributions` | v5 历史停用恢复、待归属迁移与重试状态 |
| `kpi_maintenance_operations` | 恢复和待归属解析的幂等异步操作 |

### 12.2 身份与作用域不变量

- 所有 v6 业务表的主业务键显式包含 `network_element_type`；禁止 NULL、空字符串、`*`、`COMMON`、
  `PUBLIC` 或 `GENERIC` 表示公共范围。
- 一个测量单元只属于一个网元类型；UMF 与 CSP 可拥有相同 `measurement_unit_id` 和
  `metric_resource_id`，但二者不是同一对象。
- 团队关注唯一身份为
  `(network_element_type, measurement_unit_id, metric_resource_id)`，不包含 `device_id`、`task_id`
  或用户名；同一网元类型内共享，不同网元类型完全隔离。
- 测量单元启用后，其全部已确认基础指标和 `definition_state=defined` 的派生指标进入范围。
  指标、绑定、派生和维护配置没有可抑制巡检的 `enabled` 列。
- 业务规则归属唯一键为 `(rule_code, network_element_type)`；零行即“未归属”，不执行且不生成 `skip`。
- 所有时间字段按 UTC 存储，并以 `_at` 结尾。

### 12.3 配置语义

`kpi_v6_measurement_units.inspection_enabled` 是后续任务的唯一日常启停控制。启停保留绑定、派生、维护配置和团队关注，
只改变后续任务或显式重建的 KPI 范围；已完成任务和报告不被改写。

绑定正常入库直接写 `binding_state=confirmed`，异常状态为 `candidate` / `conflict` / `ignored`。
`conflict` 支持单条人工修正并递增 revision；旧 v5 批量确认接口只保留 `deprecated` 兼容，不进入新流程。

派生指标只有 `definition_state=defined` 才进入任务范围；配置不完整时显示待配置，不从范围中删除。
源包直接提供的成功率（包括媒体资源创建、修改、删除及数据通道资源更新成功率）必须作为 `base` 指标读取，
源值即最终值；不得在 PatrolX 内重算、回填或拆成第二个派生指标。源值为空时保持缺失。

维护配置 `config_state=incomplete` 的指标仍属于任务范围，并输出 `needs_config` / `unjudgeable`，
不能被当作正常，也不能通过修改 `enabled` 隐藏。历史 v5 指标、绑定或派生的 `enabled=false` 只进入
`kpi_legacy_recovery_audits`；恢复不改写既有任务结果，也不自动生成关注。

### 12.4 团队关注

`kpi_team_focus_revisions` 每个网元类型一行，初始 revision 为 0；每次成功 PATCH 递增 1。
`kpi_team_focus_items` 保存 `added_by`、`added_at`，初始为空，不从旧 `enabled=true` 迁移。

当前任务中的关注可用性由任务 KPI 范围与当前测量单元状态共同解释：

- 测量单元停用：`unavailable` + `measurement_unit_disabled`；
- 指标不在该任务快照：`unavailable` + `not_in_task_scope`；
- 其余为 `available`。

不可用项必须保留配置并展示原因，不得自动删除。团队关注只影响结果页查看范围，不进入任务执行计划，
不改变报告、指标结果或历史点。

### 12.5 规则归属与任务规则快照

业务规则不提供公共范围。`kpi_rule_network_assignments` 为一条规则保存一个或多个网元类型，
`kpi_rule_assignment_audits` 追加记录变更前后集合、actor、来源、结果和 revision。
清空最后一条归属前需要显式二次确认。

任务真正开始时写入 `task_rule_scope_snapshots` 和 `task_rule_scope_items`：

- 快照记录任务网元类型、全局归属 revision、注册表指纹、触发方式、冻结时间和状态。
- `task_rule_scope_items` 只包含当前任务网元类型命中的普通业务规则，记录规则版本、category、priority、
  执行顺序和归属快照；隐藏解压/分类单元不进入该表。
- 标准巡检任务使用 `product`；日志补充包新增可空 `tasks.rule_network_element_type`，最多一个值。
  未指定类型的日志包规则快照为空，只执行内部技术单元，页面必须显示范围说明。
- 规则归属或注册表在任务执行中变化，当前快照不变。单规则/增量重跑只接受快照内规则，分别返回
  `rule_not_in_task_scope` 与 `rule_snapshot_version_mismatch`。

### 12.6 任务 KPI 快照与结果发布

`task_kpi_scope_snapshots` 冻结任务 KPI 配置指纹、数据日期、团队关注 revision 和范围说明。
`task_kpi_scope_items` 只包含冻结时启用测量单元下的已确认基础指标和已定义派生指标；
`scope_status=needs_config` / `unjudgeable` 的项仍保留。

`task_kpi_metric_results_v6` 保存每个指标最终判定与证据摘要，`task_kpi_points_v6` 保存复合作用域历史点。
二者在同一发布事务中按 `task_id` 整批替换，并写入指标结果、摘要和审计所需的一致状态；任一失败不得留下半套结果。
结果快照发布后不可原地改写，显式重建必须重新冻结范围和配置。

工作台读取规则：

- 无 v6 规则/KPI 快照的旧任务固定返回 `409 task_result_requires_rebuild`，不从 v5 即时推导、降级或回退。
- “全部指标”来自 `task_kpi_scope_items`；“团队关注”来自关注项与任务范围的有效交集；
  “需处理 + 无需处理 = 当前任务可用关注数”；“全部指标”是独立全集。
- 证据读取必须同时带 `task_id`、`network_element_type`、`measurement_unit_id` 和
  `metric_resource_id`，不得只按测量单元或指标名称查询。
- 7 日趋势、跨任务历史和版本对比只在按需技术分析中读取；不参与首屏汇总、需处理分组或排序。

### 12.7 判定与证据字段

`task_kpi_metric_results_v6.decision` 取 `pass` / `warn` / `fail` / `unjudgeable` /
`needs_config` / `not_applicable`；`needs_attention_group` 取
`failure` / `warning` / `trend_degraded` / `unjudgeable` / `needs_config`，
多个信号由服务端按固定优先级选取一个。`special_state` 可表达
`no_action` / `not_applicable` / `no_baseline` / `all_zero` / `zero_denominator` / `no_data` / `unavailable`。

日健康证据固定使用 `Asia/Shanghai` 自然日解释，锚点为任务内最新有效测量时间，存储仍为 UTC。
当前判定与昨日趋势分离；无数据、依赖缺失、待配置、分母为零和全零待确认均不得折叠为正常。
派生成功率按同一任务、测量单元、指标、对象、周期和测量时间配对分子/分母，日值为分子总和除以分母总和；
一致性超差保留证据并阻止误报正常。

### 12.8 v5 冻结与旧任务

`deploy/data/kpi/` 基础目录、v3/v4 配置中心与 v5 KPI 表保留历史兼容；v5 字段语义不得原地改变，
也不得作为 v6 工作台的读取、写入或回退来源。`POST /api/v5/kpi/measurement-bindings/batch-confirm`
与 `/api/v2/inspector-states*` 只标记 `deprecated`，物理删除另行规划。

旧任务无 v6 快照时，唯一升级方式是在任务列表行内全量重建：保持同一 `task_id`，按当前规则归属和
KPI 配置生成新快照，原始上传包只读。现场清理提示重新上传同名包（`410 scene_cleaned`），原包缺失返回
`409 package_missing`；不得修改旧 JSON、伪造重建成功或展示 v5 兼容面板。

## 13. 局点设备台账

台账把任务证据和跨任务资产分层保存。

### 包类型

| 包类型 | 语义 |
| --- | --- |
| `inspection` | 标准巡检包；完成后尝试解析并归档设备观测。 |
| `log_supplement` | 日志补充包；不要求局点元数据，不解析、不归档设备观测，也不产生台账质量问题。 |

日志补充包内即使存在 `LST ME.txt`，该文件仍按普通待检文件参与规则匹配，但不进入台账解析结果。

### 执行时间与观测口径

- `LST ME.txt` 头部区域（第一条网元记录之前）行尾可携带 `YYYY-MM-DD  HH:MM:SS`，例如
  `+++    CSP/*xx*/     2026-09-01  10:00:00`。每个来源文件只取第一个匹配行，文件内全部设备共用该时间。
- 时间按固定 UTC+8 解释并转为 UTC 存储，秒精度；晚于任务完成时间 5 分钟以上视为不可信。
- 设备观测时间取该设备命中来源文件中最近的可解析执行时间；无有效文件时间时回退任务完成时间，
  并在 `inventory_observations.time_source_reason` 记录 `header_time_missing`、`header_time_invalid` 或
  `time_in_future`。
- `observed_at` 及由其派生的当前版本观测时间、首次/最近观测时间、版本历史顺序和质量问题检测时间
  统一按执行时间口径；相同时间按 `task_id` 稳定排序。执行时间相同时仍按字符串序判断版本方向，
  版本冲突语义不变。

### 身份、网元类型与版本

- 局点：上传巡检包时选择的 `province + operator`。
- 设备身份：省份 + 规范化设备名。
- 网元类型：`LST ME.txt` 的记录级属性；上传 `product` 只作为记录筛选条件。规范化后相等的记录才匹配、归档并保留明细；不相等记录只计入 `unmatched_count`。
- 当前版本：只来自 `LST ME.txt`；保存原始版本、来源行号和来源文件。
- 版本方向：按字典序比较，`upgrade` / `downgrade` / `unchanged`；首个有效版本没有方向。

### 存储分层

```text
output/<task_id>/inventory.json            # 可重建的任务级证据
inventory_devices                          # 跨任务设备资产
inventory_observations                     # 跨任务设备观测
inventory_parse_results                    # 任务解析证据快照
inventory_change_audits                    # 覆盖、重建和变更审计
```

任务证据记录局点、设备、版本、来源文件、冲突、错误、归档状态和 UTC 时间。`schema_version=3` 起，
任务证据新增 `execution_time` 段，保存每个来源文件的原始时间文本、行号、解析结果、状态与回退原因；
`inventory_observations` 同时持久化 `time_source`（`lst_me` / `task`）与 `time_source_reason`。旧证据
（`schema_version < 3`）不自动回填，读取时按任务完成时间兜底语义处理。任务失败不等于台账失败；
台账解析或归档失败不改变巡检任务结果。任务目录删除后，跨任务台账资产仍然保留。

### 台账维护

- 设备档案由巡检任务观测写入，不提供手动建档和备注编辑接口。
- `DELETE /api/v2/inventory/devices/{device_id}`：管理员执行物理删除；同事务删除设备档案、全部观测和版本历史聚合，写入删除审计。任务原始包、任务详情和 `inventory.json` 不被修改；相同设备身份再次巡检时重新建账。

## 14. 扩展规则

新增能力时：

- 新增规则使用新 `code`。
- 新增指标使用新 `metric.key`。
- 规则私有结构放入 `metadata{}`。
- 不修改既有字段语义。
- 新类别必须同步：
  - Pydantic 模型。
  - OpenAPI 契约。
  - 前端生成客户端。
  - 分类规则表。
  - 目录处理逻辑。
  - 测试样例。

## 15. 任务数据持久化与磁盘留存

### 13.1 数据角色

| 数据 | 存储位置 | 生命周期 | 界面读取 |
| --- | --- | --- | --- |
| 任务元数据、运行字段、`stats`、准备摘要 | SQLite `tasks` | 长期保留（人工删除除外） | DB |
| 规则结果（含隐藏规则）、发现、指标 | SQLite `task_rule_results`（契约 JSON）+ `output/<task_id>/rules/*.json`（现场副本） | DB 长期；文件随现场清理 | DB |
| KPI 历史点 | SQLite `task_kpi_points` + `output/<task_id>/kpi/history/index.jsonl`（现场副本） | DB 长期；文件随现场清理 | DB |
| 原始上传包 | `uploads/<task_id>/<package_file>` | 最近 50 个任务 | 不展示 |
| 解压数据、prepared、执行日志、报告、`task.json` / `system.json` | `output/<task_id>/` | 最近 50 个任务 | 仅报告/日志按文件读取，缺失时明确提示 |

### 13.2 `tasks` 增量列

| 列 | 类型 | 可空 | 语义 |
| --- | --- | --- | --- |
| `last_run_at` | DateTime(timezone) | 是 | 最近一次运行的开始时刻；每次运行开始时写入 |
| `duration_ms` | Integer | 是 | 最近一次运行的耗时（毫秒）；仅终态写入 |
| `package_checksum` | String(64) | 是 | 系统首次接收原始包的 SHA-256，作为创建接口同名兜底恢复与冲突判定依据（界面重传走覆盖重建，不依赖该字段） |
| `preparation` | JSON | 是 | 任务数据准备摘要（`DataPreparation` 契约快照），终态写入 |

迁移方式沿用 `_ensure_task_columns` 的 `ALTER TABLE ADD COLUMN`；旧行新列全部为 NULL。

### 13.3 两张镜像表

| 表 | 关键列 | 写入语义 |
| --- | --- | --- |
| `task_rule_results` | `task_id`、`rule_code`、`priority`、`execution_order`、`status`、`severity`、`executed_at`、`finding_count`、`result`(JSON)、`updated_at`；`UNIQUE(task_id, rule_code)` | 终态发布与单规则重跑均整批替换该任务全部行（同一事务），实现“最新为准、不保留版本” |
| `task_kpi_points` | `task_id`、`rule_code`、`measurement_unit_id`、`metric_resource_id`、`object_key`、`period_minutes`、`measured_at`、`value`、`source_file`、`line_number` | 在任务终态可见后独立整批替换，缺失字段以 NULL 保留；镜像失败不回滚任务行与规则结果 |

单个损坏的规则结果文件跳过并记录结构化日志、损坏的 KPI 历史行直接跳过，两者都不中断任务发布与启动回填。KPI 索引采用流式分批读写，避免大任务发布长期占用内存并阻塞终态可见。

### 13.4 留存与恢复

- 保留集合 = 按 `COALESCE(last_run_at, created_at)` 倒序前 50 个任务 ∪ 全部 `pending`/`running` 任务。
- 触发时机：每次任务终态发布完成后（完成/失败/重跑/重建/单规则重跑）；创建接口的兜底恢复上传不触发。
- 清理只删磁盘，不改动 DB；`uploads/` 根目录中可派生已知 task_id 的散包同样纳入清理，未消费散包与未知目录不删除。
- 启动回填扫描全部任务目录；数据库仍为 `pending`/`running` 而现场 `system.json` 已终态且缺少 `task.json` 时，用任务行、规则结果和终态时间恢复任务并补写 `task.json`，KPI 索引不参与这次恢复。
- 界面重传同名包先覆盖确认，确认后清空旧任务并用当前数据包全量重建；创建接口兜底矩阵：同名且 checksum 一致 → `202` + `Location`，只恢复 `uploads/<task_id>/` 现场、不自动重跑；checksum 不一致 → `409 package_checksum_conflict`。
- 手动设备 ID（`reserve` 与 `PATCH /api/v2/tasks/{task_id}/device-id`）必须命中 `inventory_devices.device_id`，否则 `400 device_not_found` 且不写任务记录。
