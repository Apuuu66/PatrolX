# 数据模型：按真实目录进行按需归档分类

**功能**：`038-on-demand-archive-classification`
**状态**：Plan 阶段冻结
**日期**：2026-11-02
**关联契约**：[classification-config.md](contracts/classification-config.md)、[manifest-v5.md](contracts/manifest-v5.md)、[task-product-api.md](contracts/task-product-api.md)

## 1. 模型边界

本模型区分四个层次：

| 层次 | 事实来源 | 可修改性 |
| --- | --- | --- |
| 上传输入 | 原始包与上传元数据 | 只读；不得移动、覆盖或删除 |
| 证据现场 | `.main/` 安全展开结果 | 可从原始包幂等重建，不得手工修改 |
| 分类现场 | 配置驱动的目标根、manifest、catalog 与审计 | 通过 staging + manifest 原子发布 |
| 巡检现场 | 规则结果、prepared、报告和任务摘要 | 分类发布不得删除或覆盖 |

`output/<task_id>/manifest.json` 的 v5 manifest 是分类现场唯一发布凭据。普通规则只能通过 manifest 的 `catalog[]` 获得可巡检文件。目录扫描结果、旧分类目录和临时文件都不是模型事实。

## 2. 领域枚举

### 2.1 Product

```text
UMF
CSP
```

字段与约束：

- 输入先 `trim().upper()`，内部只保存两个枚举值之一。
- 巡检包必须有值；日志补充包必须为 `null`。
- 不得从包名、路径、台账内容或归档成员推断。
- 不接受小写持久化值；展示层如需中文名称只做显示映射，不改变存储值。

### 2.2 PackageKind

```text
inspection
log_supplement
```

- `inspection` 必须有 province、operator 和 product。
- `log_supplement` 禁止 province、operator 和 product，分类 profile 固定为 `GENERIC`。
- 任务元数据继续使用 `TaskRecord.package_kind`，不新增数据库列。

### 2.3 ClassificationPhase、Action、Category

| 枚举 | 合法值 |
| --- | --- |
| Phase | `alarm`、`precise`、`ignore`、`fallback` |
| Action | `copy`、`expand`、`decompress`、`expand_recursive`、`select_and_decompress`、`ignore`、`fallback` |
| Category | `config`、`status`、`operation`、`kpi`、`alarm`、`log`、`chr`、`other` |

`Category` 是本功能内部审计分类，不是公共 `RuleCategory` 的扩展。`ignore` route 的 category 必须为 null。

### 2.4 ClassificationErrorCode

```text
archive_depth_exceeded
member_path_depth_exceeded
file_count_exceeded
task_file_count_exceeded
file_too_large
total_bytes_exceeded
archive_corrupt
unsafe_path
link_rejected
duplicate_member
target_conflict
invalid_classification_config
```

错误码是稳定值。manifest、规则结果、CLI 和 UI 不得依赖中文异常文本区分错误。

## 3. 关系总览

```text
TaskContext(product, package_kind)
  └─ ClassificationSnapshot
       ├─ ClassificationConfig
       │    ├─ Profile[]
       │    └─ Route[]
       │         └─ SelectionPattern[]
       └─ EvidenceSnapshot

ClassificationConfig + EvidenceSnapshot
  └─ ClassificationAudit
       ├─ LandedEntry[] ── ConflictRecord[]
       ├─ IgnoredRecord[]
       └─ FailureRecord[]

EvidenceSnapshot + ClassificationSnapshot + ClassificationAudit
  └─ ManifestV5
       ├─ CatalogEntry[]  ← 普通规则唯一可见文件列表
       └─ Summary
```

## 4. 任务上下文

### TaskContext

内部运行上下文，不新增持久化表。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `task_id` | string | 由唯一包名派生 |
| `package_kind` | PackageKind | 必填；写回 `TaskRecord.package_kind` |
| `product` | Product/null | inspection 必填；log_supplement 为 null |
| `package_checksum` | SHA-256 string | 任务首次接收时记录的唯一恢复依据 |
| `province` | string/null | inspection 必填；log_supplement 为 null |
| `operator` | string/null | inspection 必填；log_supplement 为 null |

关系与不变量：

- `task_id` 不包含 product、province、operator 或版本。
- product/package kind 从 API/CLI 进入任务服务后，必须通过 `RuleContext` 和 `UnitRequest` 传播到隐藏分类规则；worker 不得重新推断。
- 同一 task_id 的 checksum、kind、product 必须保持首次接收值；冲突按 [task-product-api.md](contracts/task-product-api.md) 的固定顺序处理。
- 任务现场被清理后恢复上传包时，只恢复磁盘现场，不改变已有任务事实，不自动重跑。

## 5. 分类配置模型

### 5.1 ClassificationConfig

顶层严格键集合：

```text
version
profiles
routes
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `version` | integer | 固定为 `1` |
| `profiles` | mapping[string, Profile] | 必须包含规范化后的 `UMF`、`CSP`、`GENERIC` |
| `routes` | Route[] | 至少包含各 profile 可达的精细/告警/ignore/fallback 行为 |
| `fingerprint` | SHA-256 string | 加载后由规范化有效配置计算，不写入 YAML |

校验不变量：

- YAML 根必须是 mapping；重复键、未知键、缺失键和错误类型整体失败。
- 所有 profile、phase、action、category、scope 和 enum 值先规范化再校验。
- route id 全局唯一；route 声明顺序不参与语义选择。
- 每个实际使用的 profile 必须有可达的 fallback 或 catch-all ignore。
- 任一 schema、route、target、overlap 或 fallback 校验失败，返回 `invalid_classification_config`，不得执行部分 route。
- fingerprint 只由规范化有效配置决定；注释、空白、YAML 键顺序和 route 声明顺序不改变指纹。
- 无效配置不产生可复用 fingerprint，也不得写入新的有效 manifest。

### 5.2 Profile

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `key` | `UMF`/`CSP`/`GENERIC` | 大小写不敏感输入，规范化为大写 |
| `scene_anchors` | string[] | 单段 literal；不得含 `/`、`*`、`?`、`.`、`..`；GENERIC 可为空 |

语义：

- `UMF`、`CSP` 仅用于巡检包，必须与 TaskContext.product 完全一致。
- `GENERIC` 仅用于日志补充包。
- 场景根只由当前 profile 的 anchors 推导；不得混用其他网元的 anchor。
- anchor 比较使用 `strip().upper()`，配置快照保留原始配置值。
- CSP 当前只保留告警；CSP 非告警内容由 catch-all ignore 审计后忽略。

### 5.3 Route

基础严格键集合：

```text
id
phase
priority
profiles
source
action
category
target
```

`select_and_decompress` 额外要求 `selection`；`expand`/`expand_recursive` 可选 `member_decompress`；其他 action 禁止这两个键。校验实现必须以“基础严格键集合 + 当前 action 的 required/optional 键”为准，不能把基础集合误当成所有动作的唯一允许键集合。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | string | 匹配 `[a-z0-9._-]+`，全局唯一，长度 ≤128 |
| `phase` | ClassificationPhase | 固定优先级 `alarm > precise > ignore > fallback` |
| `priority` | int32 | 非 boolean；同阶段按降序选择 |
| `profiles` | Product/Profile[] | 非空、去重；`GENERIC` 不得与 UMF/CSP 混用 |
| `source` | SourcePattern | 见 5.4 |
| `action` | Action | 必须与输入类型和目标变量兼容 |
| `category` | Category/null | ignore 必须 null；其他动作必须非 null |
| `target` | POSIX template/null | ignore 必须 null；首段在固定 allowlist 中 |
| `selection` | SelectionPattern/null | 仅 `select_and_decompress` 必填 |
| `member_decompress` | glob[] | 仅 `expand`/`expand_recursive` 可选 |

选择与冲突不变量：

- 先按 phase 级别选择；高 phase 命中后不再考虑低 phase。
- 同 phase 内按 priority 降序；不同 priority 允许模式重叠，最高 priority 唯一获胜。
- 同 phase、同 priority、profiles 有交集且 source 模式可重叠时，整份配置失败。
- 重叠判定必须用 ε-NFA 状态乘积可达性，不得抽样文件或只看字面前缀。
- 目标模板只允许 `{suffix}`、`{member}`、`{archive_stem}`、`{service}`、`{node_path}`、`{name_without_gz}`，并按 action 限制可用变量。
- target 必须相对、无空段、无 `.`/`..`、无绝对路径、无 NUL、无目标越界。
- 告警 route 必须使用 `expand_recursive`，且 `capture_root` 只能是 `Alarm Information` 或 `Alarm Data`。

### 5.4 SourcePattern

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `scope` | `scene`/`evidence` | scene 相对推导的场景根；evidence 相对 `.main/` |
| `directory` | string | 完整父目录模式；literal 段或完整段 `**`；不得含文件名 |
| `file` | string | 单文件名 glob；支持 `*`、`?`；不得跨 `/` |
| `capture_root` | string/null | literal 段；必须真实出现在命中路径中 |

- 匹配前统一 `strip().upper()`；落位路径保留来源原始大小写。
- `**` 只匹配零个或多个完整目录段。
- `{suffix}` 从最右侧 `capture_root` 之后开始；缺省时从 scope 根之后开始。
- 外层设备名、问题编号、包装层不得进入目标模板，也不得成为稳定匹配条件。
- 未明确声明 expand/decompress 的未知归档按 fallback 或 copy 原样保留。

### 5.5 SelectionPattern

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `include` | `{pattern, service?}[]` | 非空；pattern 作用于归档成员完整相对路径 |
| `exclude` | `{pattern, reason}[]` | 可为空；exclude 优先于 include |
| `service` | string/null | 规范化为大写；用于 `{service}` 和节点路径去首段 |

- pattern 大小写不敏感，成员落位保留原始大小写。
- include 未命中记录 `member_not_selected`，不进入 catalog。
- 同一成员命中多个不同 service 的 include 时配置失败。
- 选中 `.gz` 成员时自动解压并移除一个 `.gz` 后缀。
- `{node_path}` 是成员父路径；若首段与 service 大小写不敏感相等则移除该段。

## 6. 分类快照与证据模型

### 6.1 ClassificationSnapshot

严格键集合：

```text
package_kind
product
profile
ruleset
config_fingerprint
extraction_policy_fingerprint
path_limit_fingerprint
scene_root
target_roots
budgets
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `package_kind` | PackageKind | 必须等于 TaskContext |
| `product` | Product/null | inspection 必填；GENERIC 为 null |
| `profile` | Profile | inspection 等于 product；log_supplement 为 GENERIC |
| `ruleset` | string | `UMF_ARCHIVE_V1`、`CSP_ARCHIVE_V1` 或 `GENERIC_LOG_V1` |
| `config_fingerprint` | SHA-256 | 等于 classification.config_fingerprint |
| `extraction_policy_fingerprint` | SHA-256 | 覆盖动作、预算、错误分类和原子发布语义 |
| `path_limit_fingerprint` | SHA-256 | 等于顶层 path_limit.fingerprint |
| `scene_root` | POSIX relative path | `.main/` 内；GENERIC 为 `.main` |
| `target_roots` | string[] | 去重、升序，且来自固定工作根 allowlist |
| `budgets` | ExtractionBudget | 必须等于代码固定值，任务不可覆盖 |

### 6.2 EvidenceSnapshot

严格对应 manifest 的 `main` 对象：

```text
checksum
count
evidence_path
evidence_fingerprint
reused
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `checksum` | SHA-256 | 原始包首次接收 checksum；64 个小写十六进制字符 |
| `count` | integer | `.main/` 普通文件数；非负；不含目录和链接 |
| `evidence_path` | string | 固定为 `.main` |
| `evidence_fingerprint` | SHA-256 | 按 6.3 算法计算 |
| `reused` | boolean | 本次执行是否复用有效证据现场 |

证据现场不变量：

- `.main/` 只能从原始包安全展开，原始包保持只读。
- 证据现场存在 symlink、非普通文件、指纹不可计算或指纹不一致时视为损坏。
- 证据损坏时先复核原始包 checksum，再从原始包重建。
- 证据文件内容、路径或大小任一变化都使 fingerprint 失效。
- 分类重建只读取 `.main/`，不得重新读取新的外部输入。

### 6.3 Evidence fingerprint

对 `.main/` 内全部普通文件构造：

```json
[{"path": "relative/path", "size": 123, "sha256": "64-lowercase-hex"}]
```

按 `path` 的字节序升序排列，使用 UTF-8、`sort_keys=True`、`separators=(",", ":")` 的 canonical JSON 序列化，再计算 SHA-256。任何路径分隔符统一为 POSIX `/`。

### 6.4 ExtractionBudget

固定预算，不可由任务或 YAML 覆盖：

| 字段 | 值 | 单位 |
| --- | --- | --- |
| `max_archive_depth` | 8 | 层 |
| `max_member_path_depth` | 12 | 路径段 |
| `max_archive_files` | 100000 | 文件 |
| `max_task_files` | 200000 | 文件 |
| `max_file_bytes` | 2147483648 | bytes |
| `max_total_bytes` | 3221225472 | bytes |

运行时预算状态包含已使用文件数、累计解压字节和当前归档深度；超限只写对应 `FailureRecord`。主包无法建立证据现场时使 `pkg.extract.main=ERROR`；子归档或单文件 GZIP 超限使 classification 返回 `WARN` 并保留其他合法文件。

## 7. 分类审计模型

### 7.1 ClassificationAudit

聚合对象，不单独作为普通规则输入：

```text
entries[]
ignored[]
conflicts[]
failures[]
summary
```

### 7.2 LandedEntry

严格键集合：

```text
source_relative
member_relative
route_id
product
category
original_target
target
action
status
reason
error_code
sha256
size
```

不变量：

- `status` 固定为 `landed`；`error_code` 必须为 null。
- `target` 必须位于任务目录，使用 POSIX `/`，不得逃逸或指向内部保留路径。
- `source_relative` 是 `.main/` 内的原始证据相对路径；`member_relative` 普通文件为 null。
- `original_target` 是模板展开后的目标；`target` 是冲突消歧后的实际目标。
- `sha256` 和 `size` 描述实际落位文件。
- 同一 `(source_relative, member_relative)` 在当前配置下不得产生多个成功 entry；不支持多目的地。

### 7.3 IgnoredRecord

严格键集合：

```text
source_relative
member_relative
route_id
product
category
original_target
target
action
status
reason
error_code
```

- `status` 固定为 `ignored`；`error_code` 必须为 null。
- `reason` 非空，例如 `route_ignored`、`member_not_selected`、`service_check_script`、`report_not_log`。
- ignore 不创建目标文件，不进入 catalog。
- 所有未选成员和 catch-all ignore 都必须有记录，不得静默丢弃。

### 7.4 ConflictRecord

严格键集合：

```text
source_relative
member_relative
original_target
target
digest
status
```

- `status` 固定为 `resolved`；`digest` 为 12 个小写十六进制字符。
- digest 输入固定为 `SHA-256(product + NUL + source_relative + NUL + member_relative)`。
- 冲突项必须同时对应一个 landed entry，且 original_target/target 一致。
- 消歧在首个扩展名前插入 `__<digest12>`；仍冲突时按 `-2`、`-3` 确定追加。
- 任何无法消歧的情况不得写 conflict resolved，必须写 `FailureRecord(error_code=target_conflict)`。

### 7.5 FailureRecord

严格键集合：

```text
source_relative
member_relative
route_id
category
action
error_code
reason
```

- `reason` 非空中文说明，可带路径、大小或预算 details。
- `error_code` 只能来自 ClassificationErrorCode。
- 一个归档成员失败不删除同归档已成功的其他成员。
- 失败项不得进入 catalog。

### 7.6 Summary

严格键集合：

```text
counts
by_route
by_category
by_action
by_status
```

`counts` 严格包含 `{landed, ignored, conflicts, failures, catalog}`，分别等于对应数组长度。`by_status` 严格包含 `{landed, ignored, failed}`。所有 mapping key 按字符串升序序列化。

## 8. ManifestV5

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

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `version` | integer | 固定为 `5` |
| `main` | EvidenceSnapshot | 见 6.2 |
| `product` | Product/null | 必须与 snapshot.product 一致 |
| `classification` | object | 严格包含 `config_fingerprint`、`profile`、`snapshot` |
| `path_limit` | object | 严格包含 `enabled`、`limit`、`fingerprint` |
| `entries` | LandedEntry[] | 仅成功落位 |
| `ignored` | IgnoredRecord[] | 仅审计忽略 |
| `conflicts` | ConflictRecord[] | 仅已解决冲突 |
| `failures` | FailureRecord[] | 仅局部失败 |
| `catalog` | CatalogEntry[] | 仅成功落位的可巡检文件 |
| `summary` | Summary | 必须与数组一致 |

无效条件包括：未知/缺失键、重复 JSON key、类型错误、枚举非法、fingerprint 不匹配、catalog 存在缺失/symlink/摘要不符、summary 计数不一致、路径逃逸或 entry 无法回溯到 `.main/` 证据。

### 8.1 CatalogEntry

严格键集合：

```text
path
category
route_id
source_relative
sha256
size
```

- `path` 相对于 `output/<task_id>/`，按 `/` 归一化，按字节序升序且唯一。
- path 必须存在、是普通文件、不是 symlink，并重新计算摘要匹配。
- 每个 catalog path 必须对应一个 landed entry target。
- catalog 不得包含 `.main/`、配置/审计文件、manifest、prepared、rules、报告、任务元数据和 execution.log。
- `TaskFileCatalog.build()` 只读取 v5 manifest 的 catalog，不扫描物理分类目录。
- catalog 构建失败时整个 classification 为 ERROR，不发布部分 catalog。

## 9. 隐藏解压单元状态

### 9.1 `pkg.extract.main`

状态：

```text
PENDING → RUNNING → PASS（展示为 OK）
                  ↘ ERROR
```

- `PASS`：`.main/` 可用、证据指纹可计算、检查原始包 checksum 通过；准备页可显示为 `OK`。
- `ERROR`：主包无法安全展开、证据无效或原始包 checksum 与任务记录不一致。
- `ERROR` 阻断 prepare 与 inspect；不得读取任何分类目录。
- 规则版本从旧逻辑升级为 `4.0.0`。

### 9.2 `pkg.extract.classification`

状态：

```text
PENDING → RUNNING → PASS      (无 failures，manifest v5 有效；展示为 OK)
                  ↘ WARN      (有局部 failures，manifest v5 仍有效)
                  ↘ ERROR     (配置/复用/发布/catalog 失败)
```

- `PASS`：所有配置和分类均成功，catalog 可巡检；准备页可显示为 `OK`。
- `WARN`：单个子归档、GZIP 或成员失败，其他合法文件已落位；允许 prepare/inspect。
- `ERROR`：配置无效、证据不可用、manifest 无效、catalog 不一致或无法原子发布；阻断 prepare/inspect。
- 只有成功发布的 v5 manifest 才能让 classification 为 PASS/WARN；失败现场不能向规则暴露旧 catalog。
- 持久化与执行器使用 `RuleStatus.PASS`/`RuleStatus.WARN`/`RuleStatus.ERROR`；`OK` 仅是准备页展示文案，`UNIT_STATUS_OK` 仅表示 worker 执行成功，不是 `RuleResult.status` 的第三个枚举来源。
- 规则版本为 `1.0.0`。

### 9.3 文件状态转换

```text
Discovery
  ├─ 命中 ignore → IgnoredRecord
  ├─ 命中 copy/fallback → LandedEntry
  └─ 命中 expand/decompress/select
       ├─ 成员成功 → LandedEntry
       ├─ 成员未选 → IgnoredRecord
       ├─ 目标冲突 → ConflictRecord + LandedEntry
       └─ 解压/预算/路径失败 → FailureRecord
```

任何失败都只作用于对应条目；主包证据建立失败例外，直接使任务失败。

## 10. 复用、重建与发布状态

分类器必须先加载并完整校验当前配置，再判断复用：

| 条件 | 动作 |
| --- | --- |
| v5 有效；checksum、证据、product、kind、snapshot、path_limit、catalog 全部一致 | 复用 `.main/` 与分类现场 |
| 仅注释/空白/route 顺序改变，fingerprint 不变 | 复用 |
| 有效配置 fingerprint 变化 | 复用 `.main/`，重建分类现场 |
| product 或 package kind 变化 | 复用 `.main/`，重建分类现场 |
| extraction policy、target roots、budgets 或 path limit 变化 | 复用 `.main/`，重建分类现场 |
| manifest 缺失、损坏或 schema 不合法 | 视分类现场无效，重建 |
| `.main/` 缺失、损坏或指纹不一致 | 复核原始包 checksum 后重建 `.main/` |
| 分类配置无效 | classification=ERROR，禁止复用和部分执行 |

发布状态：

```text
NoManifest/InvalidManifest
  → ClassificationStaging
  → ManifestStagingValidated
  → OldManifestHidden
  → TargetRootsSwapped
  → NewManifestPublished
  → Cleanup
```

目标根交换失败必须逆序回滚；manifest 发布前任何读取方都不得把 staging 目录当作可巡检现场。发布只替换分类目标根，不得删除证据、原始包、规则结果、prepared、报告、任务元数据或数据库。

## 11. 配置错误与局部失败边界

| 情况 | 分类单元 | catalog | 后续 prepare/inspect |
| --- | --- | --- | --- |
| 配置 schema/route/target/overlap/fallback 失败 | ERROR | 不发布 | 阻断 |
| 主包无法建立证据现场 | main ERROR | 不发布 | 阻断 |
| 单个子归档损坏、成员路径非法、预算超限 | WARN + FailureRecord | 发布有效部分 | 继续 |
| 目标冲突可稳定消歧 | PASS/WARN + ConflictRecord | 包含实际 target | 继续 |
| 目标冲突无法消歧 | WARN + FailureRecord | 不包含该 entry | 继续处理其他文件 |
| catalog 文件缺失、摘要不符、symlink 或 summary 不一致 | ERROR | 不发布 | 阻断 |
| 日志补充包携带 product/province/operator | API/CLI 校验失败 | 不创建或执行 | 阻断 |

## 12. 跨模型不变量

- product、package kind、profile、ruleset 和 snapshot 必须互相一致。
- `ManifestV5.product == ClassificationSnapshot.product`。
- `classification.config_fingerprint == snapshot.config_fingerprint`。
- `classification.profile == snapshot.profile`。
- `path_limit.fingerprint == snapshot.path_limit_fingerprint`。
- `summary.counts.landed == len(entries)`、`ignored == len(ignored)`、`conflicts == len(conflicts)`、`failures == len(failures)`、`catalog == len(catalog)`。
- 每个 catalog entry 都能回溯到唯一 landed entry；每个 landed entry 的 target 都实际存在且摘要一致。
- 普通规则只读 catalog；不得扫描 `WORK_CATEGORIES` 或自行解析 manifest entries。
- 业务分类只用于审计和后续寻址，不改变 `RuleResult`、`Metric`、`Finding` 或公共 `RuleCategory` 契约。
- 当前保留的 KPI 规则判定、指标契约和 `rule_version=3.3.0` 不变；分类只保证 `kpi/` 输入路径稳定。

## 13. 历史版本迁移

本节只描述迁移与历史对比，不属于可复用模型：

- 历史 `manifest` 版本 1–4 一律视为不可复用，不读取其中 `files`、`subpackages`、`log_gz`、`rejected` 或旧 policy 条目作为 v5 事实。
- 历史分类根 `logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other` 只可在 v5 成功发布后按已知 allowlist 清理。
- 历史巡检任务 product 缺失时保持 null；不得从旧目录名或台账推断回填。
- 旧按名称/扩展名分类和旧 extract policy 仅可作为迁移前行为对比资料，不参与生产分类。
- 历史任务恢复上传包时仍先校验首次接收 checksum；恢复不自动重跑，也不伪造 product。
