# 契约：分类配置 v1

**状态**：Plan 阶段冻结
**配置路径**：`deploy/config/classify_rules.yaml`
**消费者**：`pkg.extract.classification`、CLI `explain-match`、分类审计与测试
**约束**：配置只读、启动时整体校验；不提供在线编辑、热加载或任务级覆盖。

## 1. 顶层结构

```yaml
version: 1
profiles:
  UMF:
    scene_anchors:
      - "Basic Information About the UMF"
      - "Debugging Commands"
      - "Equipment Status"
      - "MESH Information (Problem)"
      - "System Resources"
      - "Operation Logs"
      - "MML Configurations"
      - "Performance Measurement Results"
      - "MESH Application Metrics"
      - "CHR Information"
      - "Host Debugging Logs"
      - "Host System Logs"
      - "Service Logs (Problem)"
  CSP:
    scene_anchors:
      - "Alarm Data"
  GENERIC:
    scene_anchors: []
routes:
  - id: alarm.umf
    phase: alarm
    priority: 1000
    profiles: [UMF, CSP]
    source:
      scope: evidence
      directory: "**/Alarm Information/**"
      file: "*"
      capture_root: "Alarm Information"
    action: expand_recursive
    category: alarm
    target: "alarm/{member}"

  - id: alarm.csp
    phase: alarm
    priority: 1000
    profiles: [UMF, CSP]
    source:
      scope: evidence
      directory: "**/Alarm Data/**"
      file: "*"
      capture_root: "Alarm Data"
    action: expand_recursive
    category: alarm
    target: "alarm/{member}"

  - id: csp.ignore-non-alarm
    phase: fallback
    priority: 0
    profiles: [CSP]
    source:
      scope: evidence
      directory: "**"
      file: "*"
    action: ignore
    category: null
    target: null

  - id: umf.other
    phase: fallback
    priority: 100
    profiles: [UMF]
    source:
      scope: scene
      directory: "**"
      file: "*"
    action: fallback
    category: other
    target: "other/{suffix}"

  - id: generic.logs
    phase: fallback
    priority: 100
    profiles: [GENERIC]
    source:
      scope: evidence
      directory: "**"
      file: "*"
    action: fallback
    category: log
    target: "logs/{suffix}"
```

顶层键集合必须严格等于 `{version, profiles, routes}`。未知键、缺失键、重复 YAML key、非 mapping 根节点均视为 `invalid_classification_config`。

## 2. Profile

- key 只允许 `UMF`、`CSP`、`GENERIC`，比较大小写不敏感，规范化为大写。
- 三个 profile 必须全部声明；每个 profile 的对象键集合严格等于 `{scene_anchors}`。
- `scene_anchors` 是非空 string 列表，`GENERIC` 除外，可为空。
- anchor 必须是单个 literal 目录段，不含 `/`、`*`、`?`、`.`、`..`，不得为空。
- anchor 使用 `str.strip().upper()` 比较；manifest 记录原始配置值。
- `UMF`、`CSP` 只用于巡检包；`GENERIC` 只用于日志补充包。
- 巡检包 profile 必须与规范化 product 完全相等，不得回退 `GENERIC`。
- 日志补充包必须使用 `GENERIC`，不得读取 product 或执行 UMF/CSP 精细路线。

场景根算法：

1. 对每个普通证据文件，检查其父路径中的完整目录段是否等于 profile anchor。
2. 命中 anchor 时，收集 anchor 的父目录作为候选场景根。
3. 有候选时，先按 anchor 父目录精确聚类；依次选择覆盖 anchor 种类最多、命中次数最多、目录层数最多的候选，最后按大小写归一化路径字典序稳定决胜；没有候选时，场景根为 `.main/` 证据根。
4. `scope: scene` 使用相对于该场景根的路径。
5. `scope: evidence` 始终使用相对于 `.main/` 的完整路径。
6. UMF 场景根不得被 CSP anchor 或不需要的 profile anchor 影响。

## 3. Route

每条 route 的键集合严格为：

```text
{id, phase, priority, profiles, source, action, category, target}
```

`select_and_decompress` 额外要求 `selection`；`expand`/`expand_recursive` 可选 `member_decompress`。其他动作禁止这两个键。

### 3.1 id

- 非空 string，只允许小写 ASCII 字母、数字、`.`、`_`、`-`。
- 全配置唯一，长度不超过 128。
- id 是对外审计标识；改变 id 是语义变更。

### 3.2 phase

只允许：

```text
alarm
precise
ignore
fallback
```

阶段优先级固定为 `alarm > precise > ignore > fallback`，与 YAML 顺序无关。高阶段只要有一条 route 命中，就不再考虑低阶段。

### 3.3 priority

- 必须是 32 位有符号整数，不得为 boolean。
- 同一阶段内按数值降序选择。
- 同阶段、同 priority、profiles 有交集且 pattern 可重叠的两条 route 必须使配置失败。
- 同阶段不同 priority 的重叠合法，高 priority 唯一获胜。

### 3.4 profiles

- 非空列表，元素只允许 `UMF`、`CSP`、`GENERIC`。
- 规范化为大写去重集合。
- 不得同时包含 `GENERIC` 与 `UMF/CSP`。
- 跨网元告警 route 必须声明 `[UMF, CSP]`。
- 每个实际使用的 profile 必须具备可达的 fallback 或 catch-all ignore 行为。

### 3.5 source

source 的键集合严格为 `{scope, directory, file, capture_root}`，其中 `capture_root` 可省略。

```yaml
source:
  scope: scene | evidence
  directory: "Basic Information About the UMF/**"
  file: "*.ini"
  capture_root: "Basic Information About the UMF"
```

规则：

- `scope` 只允许 `scene`、`evidence`。
- `directory` 匹配文件父目录的完整 `/` 分隔路径，不得含文件名。
- `directory` 由 `/` 分隔的目录段组成；段要么是 literal，要么是恰好 `**`。literal 段不得含 `/`、`*`、`?`。
- `**` 匹配零个或多个完整目录段。
- directory 不得以 `/` 开头或结尾，不得包含空段、`.`、`..`，但单独的 `**` 可表示 scope 根下的全部深度。
- `file` 匹配单个文件名，允许 `*`、`?` 和 literal；不得含 `/`、空值、`.`、`..`。
- 匹配前将目录路径和两段 pattern 做 `str.strip().upper()`；分类目标保留来源原始大小写。
- `capture_root` 是可选 literal 目录段，必须真实出现在对应来源命中路径中，不参与 wildcard 语义。
- `{suffix}` 从 `capture_root` 之后开始；缺省 capture_root 时从 scope 根之后开始。同一段重复时取最右侧完整段。
- 任意 `alarm` phase route 的 `capture_root` 必须是 `Alarm Information` 或 `Alarm Data`，且对应 literal 必须位于 directory pattern 中。
- 未知归档的 fallback route 必须使用 `action: fallback` 或 `copy`，不得依赖自动嗅探。

### 3.6 action

只允许：

| action | 适用输入 | 行为 |
| --- | --- | --- |
| `copy` | 普通文件或未展开归档 | 原样复制到 target |
| `expand` | 支持的归档 | 展开 route 命中归档，成员继承当前 route；可选解压指定成员 GZIP |
| `decompress` | 单文件 GZIP | 解压一个 `.gz`，`.tar.gz` 必须先作为 TAR 归档处理 |
| `expand_recursive` | 告警归档或普通文件 | 递归展开 ZIP/TAR/TAR.GZ，递归解压 GZIP，并保留所有普通成员 |
| `select_and_decompress` | 归档 | 按 selection 选择成员；选中 GZIP 解压，未选成员写 ignore 审计 |
| `ignore` | 任意文件 | 不落位，只写审计 |
| `fallback` | profile 未命中兜底 | 行为等同 `copy`，但必须承担 catch-all 语义 |

动作约束：

- `copy`、`decompress`、`fallback`、`ignore` 不得声明 `selection` 或 `member_decompress`。
- `expand`、`expand_recursive` 可声明 `member_decompress`，其元素是成员路径 glob；只对匹配的 `.gz` 成员解压，其他成员保持原相对路径。
- `select_and_decompress` 必须声明 selection。
- 告警 route 必须使用 `expand_recursive`。
- `.tar.gz` 必须先按 TAR 归档展开；只有普通单文件 `.gz` 才使用 gzip 解压。
- 归档内后续嵌套归档默认继承当前 route 的展开语义；`action: expand_recursive` 不再要求额外嵌套规则。
- 任何未声明展开的归档都作为普通文件落位，不得读取成员列表来决定类别。

### 3.7 category

非 `ignore` route 必须使用以下业务分类之一：

```text
config
status
operation
kpi
alarm
log
chr
other
```

`ignore` route 的 category 必须为 `null`。业务分类只用于审计和后续寻址，不得扩展或重定义公共 `RuleCategory`。

### 3.8 target

- 非 `ignore` route 必须声明非空 string；`ignore` route 必须为 `null`。
- 目标必须是相对 POSIX 模板，不含绝对路径、`.`、`..`、空段、反斜杠、NUL。
- 首段必须来自固定工作根 allowlist：

```text
alarm
basic
chr
config
debug
host-debug
host-system
kpi
logs
mml
operation-log
other
resource
status
traffic
```

- 允许变量仅为 `{suffix}`、`{member}`、`{archive_stem}`、`{service}`、`{node_path}`、`{name_without_gz}`；未知变量或未闭合花括号配置失败。
- `copy/fallback`：只允许 `{suffix}`。
- `expand/expand_recursive`：只允许 `{member}`、`{archive_stem}`。
- `decompress`：只允许 `{suffix}`、`{name_without_gz}`。
- `select_and_decompress`：只允许 `{member}`、`{service}`、`{node_path}`、`{name_without_gz}`。
- `{member}` 是动作完成后的成员相对路径；单文件 `.gz` 解压后去掉该后缀。
- `{archive_stem}` 是 route 命中的归档文件名去掉 `.zip`、`.tar`、`.tar.gz`、`.tgz` 或 `.gz` 后的结果。
- `{name_without_gz}` 是最终文件名去掉一个 `.gz` 后缀。
- 空变量与相邻 `/` 一并省略，不得产生空目录段。

目标冲突算法：

1. 使用 route target 和变量得到 `original_target`。
2. 若目标未被其他证据占用，直接使用。
3. 若已占用，计算 `SHA-256(product + NUL + source_relative + NUL + member_relative)` 的前 12 个小写十六进制字符。
4. 在文件首个扩展名前插入 `__<digest12>`；无扩展名时追加 `__<digest12>`。
5. 如仍占用，依次追加 `-2`、`-3`，直到得到唯一路径。
6. entry 同时保存 `original_target` 和 `target`；不得覆盖任何已有文件。

## 4. selection

`selection` 的键集合严格为 `{include, exclude}`；`include` 必须为非空列表，`exclude` 可以为空列表。

```yaml
selection:
  include:
    - pattern: "**/UMFAcc.log"
      service: UMFAcc
    - pattern: "**/UMFAcc_*.log.gz"
      service: UMFAcc
  exclude:
    - pattern: "**/RScheck/**"
      reason: service_check_script
    - pattern: "**/LocalLogReport.csv"
      reason: report_not_log
```

`include[]` 键集合为 `{pattern, service}`，`service` 可省略。`exclude[]` 键集合为 `{pattern, reason}`。

- pattern 与 source.file 使用相同 glob 语法，但作用于归档成员完整相对路径，并且 `**/` 可匹配零个或多个目录段。
- pattern 大小写不敏感，成员落位保留原始大小写。
- exclude 优先于 include；命中 exclude 时记录配置的 reason。
- include 命中且 service 存在时，`{service}` 使用规范化配置值。
- include 无 service 时不得在 target 使用 `{service}`。
- 同一成员同时命中不同 service 的 include 时配置失败。
- include 未命中的成员记录 `member_not_selected`；不进入 catalog。
- `{node_path}` 是成员父路径；若首段与 `{service}` 大小写不敏感相等，则移除该首段。
- 选中成员以 `.gz` 结尾时自动解压并去除该后缀；`name_without_gz` 与 `member` 均反映最终路径。

## 5. 必需的 UMF 精细路线

下表是 profile `UMF`、phase `precise` 的最低配置集合。priority 可调整，但同一阶段内必须保持明确排序；除非模式确实互斥，不得使用相同 priority。

| route id | source scope / directory / file | capture_root | action | category | target |
| --- | --- | --- | --- | --- | --- |
| `umf.basic` | scene / `Basic Information About the UMF/**` / `*` | `Basic Information About the UMF` | `copy` | `config` | `basic/{suffix}` |
| `umf.debug` | scene / `Debugging Commands/**` / `*` | `Debugging Commands` | `copy` | `status` | `debug/{suffix}` |
| `umf.equipment-status` | scene / `Equipment Status/**` / `*` | `Equipment Status` | `copy` | `status` | `status/{suffix}` |
| `umf.mesh-status` | scene / `MESH Information (Problem)/**` / `*` | `MESH Information (Problem)` | `copy` | `status` | `status/{suffix}` |
| `umf.system-resources` | scene / `System Resources/**` / `*` | `System Resources` | `copy` | `status` | `status/{suffix}` |
| `umf.operation-log` | scene / `Operation Logs` / `operationlog_history_*.csv` | `Operation Logs` | `copy` | `operation` | `operation-log/{suffix}` |
| `umf.mml-file` | scene / `MML Configurations` / `EXP MML.txt` | `MML Configurations` | `copy` | `config` | `mml/{suffix}` |
| `umf.mml-archive` | scene / `MML Configurations` / `EXPMML_*.zip` | `MML Configurations` | `expand` | `config` | `mml/{member}` |
| `umf.kpi` | scene / `Performance Measurement Results` / `PerfResult_*.zip` | `Performance Measurement Results` | `expand` | `kpi` | `kpi/{member}` |
| `umf.mesh-metrics` | scene / `MESH Application Metrics` / `CollectExport*.zip` | `MESH Application Metrics` | `expand` | `other` | `other/MESH Application Metrics/{archive_stem}/{member}` |
| `umf.chr` | scene / `CHR Information` / `ServiceLogs_*.zip` | `CHR Information` | `select_and_decompress` | `chr` | `chr/{member}` |
| `umf.host-debug` | scene / `Host Debugging Logs` / `DEBUG.tar.gz` | `Host Debugging Logs` | `expand` + member GZIP | `log` | `host-debug/{member}` |
| `umf.host-system` | scene / `Host System Logs` / `OS.tar.gz` | `Host System Logs` | `expand` + member GZIP | `log` | `host-system/{member}` |
| `umf.service-logs` | scene / `Service Logs (Problem)` / `ServiceLogs_*.zip` | `Service Logs (Problem)` | `select_and_decompress` | `log` | `logs/{service}/{node_path}/{name_without_gz}` |
| `umf.other` | scene / `**` / `*` | — | `fallback` | `other` | `other/{suffix}` |

CHR include 必须为 `**/*.bil.gz`。exclude 至少包含：

```yaml
- pattern: "**/LocalLogReport.csv"
  reason: report_not_log
```

Service Logs include 必须覆盖：

```text
**/UMFAcc.log
**/UMFAcc_*.log.gz
**/UmfService.log
**/UmfService_*.log.gz
**/CacheService.log
**/ResourceManageService.log
```

Service Logs exclude 至少覆盖：

```text
**/RScheck/**
**/rscheck*.gz
**/dblog.tar.gz
**/UFP_*.log
**/UFP_MSS_2_0.zip
**/monitor_detect.log
**/UmfService_monitor.log
**/start/**/*.log
**/proxy/**/*.log
**/bbox*.dat.txt
**/LocalLogReport.csv
```

`ServiceLogs_*.zip` 中除 include 与 exclude 外的成员必须记录 `member_not_selected`，不得进入 catalog。

## 6. 跨网元告警与 ignore

- `alarm.umf` 必须匹配任意 evidence 前缀中的完整目录段 `Alarm Information/`，不得依赖 `Problems`、设备名或固定深度。
- `alarm.csp` 必须匹配任意 evidence 前缀中的完整目录段 `Alarm Data/`，不得依赖 `Problems`、`0/`、设备名或固定深度。
- 两条 alarm route 均声明 `[UMF, CSP]`、phase `alarm`、priority `1000`、`expand_recursive`、target `alarm/{member}`。
- 告警 route 在 `0/` ignore route 之前执行；告警中的 0 字节、仅表头、零记录和有记录文件均落位。
- 普通 `0/` 内容的 ignore route 必须位于 `ignore` 阶段，profiles 至少包含 `[UMF, CSP]`，scope evidence，directory `**/0/**`，file `*`。
- CSP 非告警内容最终必须由 CSP catch-all ignore 捕获。
- UMF fallback 必须捕获场景内全部未命中文件，并按场景相对路径进入 `other/`。
- 所有 ignore 与 member_not_selected 必须进入 `ignored[]`，不得静默丢弃。

## 7. 重叠校验算法

两条 route 的同优先级冲突校验必须是确定性的静态算法：

1. 规范化 directory/file pattern：`strip()`、`upper()`、移除多余尾 `/`、拆分目录段。
2. 将 directory literal、`**`、`/` 边界和 file glob 编译到同一个 ε-NFA。
3. Alphabet 包含所有出现过的 literal scalar，以及一个 `OTHER` 等价类，表示未被任何 literal 显式列出的 scalar。
4. `*` 表示 0..n 个非 `/` scalar；`?` 表示 1 个非 `/` scalar；`**` 作为完整目录段表示 0..n 个目录段。
5. scene scope pattern 增加 `**/` 前缀，等价映射到 evidence 路径；evidence scope 保持原样。
6. 对两份 NFA 的 ε-closure 状态对做广度优先搜索。
7. 存在可达的双方接受状态对时判定重叠；否则不重叠。
8. 仅对同 phase、同 priority、profiles 有交集且判定重叠的 route 失败。
9. 错误详情必须包含两条 route id、phase、priority 和 profile 交集。

该校验不得以抽样路径、仅字面前缀或运行时文件作为判据。

## 8. 配置指纹

`classification.config_fingerprint` 为规范化有效配置的 SHA-256：

1. 填充所有 schema 默认值，例如省略的 `capture_root: null`、`member_decompress: []`。
2. profile key、anchor、route profiles、category、phase、action、scope 转为规范大小写。
3. 大小写不敏感 pattern 统一 `upper()`。
4. 去重无序集合：profiles、anchor、include、exclude、member_decompress。
5. route 按 id 升序，include 按 `(pattern, service)`，exclude 按 `(pattern, reason)` 排序。
6. 使用 UTF-8、`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")` 序列化。
7. 对序列化字节计算 SHA-256，使用 64 个小写十六进制字符。

必须成立：

- 只改注释、空白、YAML 映射键顺序或 route 声明顺序，指纹不变。
- 改任一 anchor、pattern、profiles、priority、action、category、target、selection、member_decompress 或 id，指纹改变。
- 无效配置不产生可复用指纹，也不得写入新 manifest。

## 9. 错误与审计

配置错误统一返回 `invalid_classification_config`，至少包含：

```json
{
  "code": "invalid_classification_config",
  "path": "routes[3].target",
  "message": "目标首段不在 allowlist: payload",
  "route_id": "umf.basic"
}
```

当错误与具体 route 无关时，`route_id` 可为 `null`。必须整体失败，不得执行已通过校验的前缀 route，不得回退旧配置或 v4 结果。
