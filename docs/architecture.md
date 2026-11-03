# PatrolX 架构文档

本文档描述 PatrolX 的系统结构、运行模式、数据流、规则编排和运行时目录。项目长期约束见
[`.specify/memory/constitution.md`](../.specify/memory/constitution.md)；在线接口结构以
[`docs/api/openapi.yaml`](api/openapi.yaml) 为唯一契约源。

## 1. 系统定位

PatrolX 是离线巡检系统：

- 不连接被检系统，不做在线数据采集。
- 输入是预先收集好的 `zip` / `tar.gz` 数据包。
- 一个包对应一个任务和一个系统巡检上下文。
- 输出契约化巡检结果和 HTML 报告。
- 本地模式与在线模式共用同一套巡检器、规则库和结果契约。

## 2. 总体结构

```text
┌──────────────┐
│  数据包输入  │  uploads/：原始包输入现场
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 安全解压层   │───▶│ 按类落位目录   │
│ pkg.extract  │    │ logs/kpi/...   │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 规则私有准备 │───▶│ prepared/<rule>│
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 规则执行器   │───▶│ rules/<code>.json │
│ P1/P2        │    │ report.html    │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 报告生成器   │───▶│ report.html    │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐
│ Web / CLI    │  任务 → 系统 → 规则 → 发现
└──────────────┘
```

后端分层：

```text
api/          HTTP 路由与请求/响应边界
services/     任务、执行、报告、结果组织等业务编排
inspectors/   各领域巡检规则，直读 source_patterns 匹配文件
models/       Pydantic 契约模型与持久化模型
core/         配置、注册表、安全解压、分类等基础能力
```

约束：

- `api` 不得直接实现巡检逻辑。
- `inspectors` 不得依赖 Web 层或数据库。
- 规则之间不得互相引用实现；每条普通规则只读取自己的 source_patterns 匹配文件。

## 3. 运行模式

### 3.1 本地模式

本地模式面向规则开发和快速自验，无数据库依赖。入口隔离细节见 [`docs/design/entrypoints.md`](design/entrypoints.md)。

常用入口：

```bash
python main.py                             # 本地调试：执行 local_run/ 下全部压缩包
python build.py verify                     # 全流程：执行 uploads/ 下全部压缩包
python build.py verify-one --rule <code>   # 单规则重跑
python build.py test
python build.py lint
```

`python main.py` 是本地调试专用入口：

- 只扫描 `local_run/` 根目录。
- 执行其中全部压缩包，不做最新包选择。
- 不使用 `uploads/`，也不需要命令行参数。
- 每个包仍然生成独立的 `output/<task_id>/`。

`python build.py verify` 的默认行为：

- 扫描 `uploads/` 根目录下的压缩包。
- 多个包顺序分析，每个包一个任务。
- 任务 ID 由包名清洗生成，格式为 `task-<包名清洗后的标识>`。
- 原始包归档到 `uploads/<task_id>/`。
- 解压数据、规则结果和报告写入 `output/<task_id>/`。

### 3.2 在线模式

在线模式面向多人使用，提供 Web 界面和 API。

- 未登录访客可浏览结果并执行任务；配置类写操作要求管理员登录。
- 用户由管理员在 Web「用户管理」维护，不支持在线注册；首次部署可通过
  `scripts/create_default_admin.py` 初始化默认管理员，目标管理员已存在时可重置密码。
- 一次上传一个包，创建一个任务。
- 任务之间串行消费；任务内按 `EXTRACT → PREPARE → INSPECT → 收尾` 固定屏障执行，`PREPARE` / `INSPECT` 阶段内最多 4 个进程并行（固定并行度，无配置入口）。
- SQLite 是界面展示数据的唯一来源：任务快照（元数据、运行字段、准备摘要）、规则结果、KPI 历史点、设备台账与 KPI 配置均长期保存在 DB。
- `uploads/`、`output/` 降级为执行期现场（原始包、解压数据、规则 JSON 副本、执行日志、报告），按留存策略只保留最近 50 个任务的现场。
- 前端通过 `/api/v2` 访问后端，API 客户端由 OpenAPI 生成。

启动：

```bash
python run_online.py
```

该入口会启动 FastAPI 后端和 Vite 前端。生产部署可使用 Docker Compose，Docker 是可选扩展。

## 4. 核心数据流

1. **输入识别**
   - 只识别任务输入目录根层的压缩包。
   - 校验压缩包格式和大小限制。
   - 原始包保留为输入现场，解压过程只读。

2. **任务识别**
   - 任务 ID 由包名清洗生成。
   - 包类型是任务元数据：`inspection` 是标准巡检包，`log_supplement` 是日志补充包。
   - 巡检包在线记录省份、运营商、网元类型、版本等任务元数据；日志补充包不要求局点元数据。后端字段仍为 `product`，界面文案统一显示“网元类型”。

3. **安全解压与按类落位**
   - 主包由隐藏规则 `pkg.extract.main` 解压到 `.main/`，该目录永久保留主包原始解压现场。
   - `.main/` 记录 evidence fingerprint；证据缺失、损坏或指纹不符时，复核原包 checksum 后重建。
   - 隐藏规则 `pkg.extract.classification` 按 product/package kind 选择 profile，从 `.main/` 执行配置驱动的告警、精细、忽略和 fallback 路线。
   - 只有配置声明的归档和 `.gz` 成员按需展开；未知归档原样 fallback，不做内容嗅探或扩展名猜测。
   - 分类在 staging 构建目标根，校验 catalog 摘要后交换目标根并原子发布 `manifest.json`；失败逆序回滚。
   - 主包或发布失败时 classification 为 `ERROR`，不进入后续阶段；子归档、成员或单文件 gzip 局部失败为 `WARN`，其他合法文件继续发布。

4. **任务文件清单**
   - `pkg.extract.main` 与 `pkg.extract.classification` 到达终态后，执行器从 v5 `manifest.json` 构建一次内存 `TaskFileCatalog`。
   - catalog 只包含成功落位的普通文件，不再扫描分类目录。
   - fallback 保留的未知归档是目标根下的最终文件，会进入 catalog；未展开成员不会进入 catalog。
   - `.main/`、manifest、staging、`prepared/`、任务元数据、规则结果、报告和执行日志不在 catalog 中。
   - 清单返回 POSIX 相对路径，稳定排序、去重，并校验路径边界、普通文件、size、SHA-256 和 summary。

5. **规则私有 prepare**
   - 全部解压准备到达终态后，才执行 `PREPARE`。
   - 普通规则可以声明至多一个私有 prepare；prepare 继承 owner 的 `source_patterns` 和优先级。
   - prepared 数据写入 `prepared/<owner_code>/`，只有 owner 规则可读取。
   - prepare 失败或无匹配输入时，owner inspect 显式 `skip`；其他规则继续。

6. **普通规则 inspect**
   - prepare 阶段完成后，P1 基础检查和 P2 综合分析按优先级顺序执行。
   - 每条普通规则只按自己的 `source_patterns` 从 `TaskFileCatalog` 匹配文件；matcher 执行 `re.fullmatch()`。
   - 无匹配文件、格式不适用或解析失败时返回 `skip`，不静默通过。
   - 单规则可原地重跑，不自动补跑其他普通规则。

7. **结果与报告**
   - 规则结果写入 `rules/<rule_code>.json`。
   - 执行日志写入 `output/<task_id>/execution.log`。
   - 报告写入 `output/<task_id>/report.html`。
   - 巡检包完成规则执行后解析 `LST ME.txt`，写入任务证据 `inventory.json` 并归档台账观测。
   - 日志补充包不解析设备信息、不写入台账观测，也不产生台账质量问题；包内意外出现的 `LST ME.txt` 只作为普通待检文件。
   - 台账解析或归档失败只记录任务证据和日志，不使巡检任务失败。
   - Web 只消费契约化数据，不直接理解规则内部实现。

8. **终态发布与留存治理**
   - 任务进入终态时，父进程在单个事务内发布任务行（含 `last_run_at`、`duration_ms`、`preparation`）、全部规则结果（含 `pkg.extract.main`、`pkg.extract.classification`）与本次 KPI 历史点。
   - 发布完成后再写现场文件（`task.json`、`system.json`、`report.html`），最后触发留存清理。
   - 留存清理只删除磁盘现场，不改动任何 DB 行；保留集合 = 按 `COALESCE(last_run_at, created_at)` 倒序的前 50 个任务 ∪ 全部 `pending` / `running` 任务。
   - 重跑、全量/增量重建与单规则重跑同样整批替换该任务的规则结果与 KPI 历史点：只保留最新一次执行结果，不做版本历史。
   - 执行日志与报告不入库，随现场清理一同消失；现场缺失时报告/日志接口返回 410 `scene_cleaned`，重跑与重建返回 410 并提示重新上传同名数据包、确认覆盖后全量重建。
   - 界面重传同名包先弹覆盖确认，确认后清空旧任务并用当前数据包全量重建（033 FR-024、034 FR-013）。创建接口的同名 checksum 恢复矩阵仅作探测未命中兜底：现场缺失且 checksum 一致时写回 `uploads/<task_id>/` 现场（不自动重跑），不一致返回 409 `package_checksum_conflict`。

### 4.1 局点设备台账数据流

- 局点来自巡检包上传时的 `province + operator`，不从压缩包猜测。
- 设备身份是省份与规范化设备名的组合；当前版本只来自 `LST ME.txt`。
- `LST ME.txt` 是记录级清单，可能包含多台设备。上传 `product` 是唯一的网元类型筛选依据，不从包内推断；记录内网元类型与上传值经 NFC、空白归一和转大写后相等时才进入本次匹配和归档。其他记录不进入任务证据明细，仅保留未匹配数量。
- 清单同时兼容键值记录和真实导出的表头加数据行格式；表格式记录优先使用 `ME patch version`，为空或 `null` 时回退到 `ME version`。原始类型和版本值仍保留在任务证据中。
- 任务证据 `inventory.json` 保存原始值、行号、来源文件、状态和归档结论；SQLite 保存跨任务设备、观测、解析结果和变更审计。
- 同一任务重复归档幂等；全量重建覆盖旧观测时保留变更审计。
- 台账资产跨任务长期保留，任务目录删除不影响历史观测资产。管理员可执行物理删除，不提供手动建档或备注编辑。物理删除会同时删除设备档案、全部观测和版本历史，并保留删除审计；任务原始包与 `inventory.json` 保持不变，后续巡检可重新建账。

## 5. 运行时目录

```text
local_run/
└── <本地调试压缩包>

uploads/
└── <task_id>/
    └── <原始压缩包>

data/
└── patrolx.db

output/
└── <task_id>/
    ├── .main/
    ├── manifest.json
    ├── task.json
    ├── system.json
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
    ├── prepared/
    │   └── <rule_code>/
    ├── rules/
    │   └── <rule_code>.json
    ├── report.html
    └── execution.log
```

职责：

| 目录 | 职责 |
| --- | --- |
| `local_run/` | 本地调试输入目录，直接执行 `python main.py` 时扫描 |
| `uploads/` | 原始包输入现场，不修改；按留存策略保留最近 50 个任务的现场 |
| `output/` | 处理现场，包含解压数据、结果副本、日志、报告；按留存策略保留最近 50 个任务的现场 |
| `data/` | 系统元数据库等非任务输出数据 |
| `.main/` | 原始包只读证据现场，可由原包校验后重建，不进入 catalog |
| `manifest.json` | v5 分类现场唯一发布凭据，记录证据、快照、审计和 catalog |
| `prepared/` | 规则私有中间数据，按 owner 规则隔离，不进入 API 契约 |
| `rules/` | 规则契约结果，单规则单文件，支持原地更新 |

生命周期：

- 数据库长期保留任务行、规则结果与 KPI 历史点（人工删除除外），是界面展示的唯一来源；磁盘现场按“最近 50 个任务”策略自动清理。
- `.classification.staging/` 只存在于分类执行期间；发布成功后删除，失败则回滚并清理。
- manifest v5 是分类目录、entries、ignored、conflicts、failures 和 catalog 的一致性凭据；目录扫描结果不构成事实。
- 保留集合 = 按 `COALESCE(last_run_at, created_at)` 倒序的前 50 个任务 ∪ 全部 `pending` / `running` 任务（执行中的任务豁免清理）。
- 清理范围：`uploads/<task_id>/`、`output/<task_id>/` 中不在保留集合内的任务目录，以及 `uploads/` 根目录中可派生已知 task_id 的散包；无法归属到已知任务的目录与散包不删除。
- 清理触发点：每次任务终态发布完成后（完成/失败/重跑/重建/单规则重跑，含本地 CLI）；创建接口的兜底恢复写回现场不触发清理，界面覆盖重建按删除 + 重建的正常终态触发。
- 清理只删磁盘、不改 DB：现场被清理后任务列表、详情、规则结果、发现、KPI 趋势与台账仍从 DB 完整可查；删除失败的目录记录结构化日志，由下一次任务结束时的清理重试。
- `.main/` 是任务现场的一部分，随现场清理一同删除。
- 删除任务必须级联删除 `uploads/<task_id>/` 和 `output/<task_id>/`；先删除文件现场，成功后再删除 `tasks`、`task_rule_results`、`task_kpi_points` 记录。
- 文件现场删除失败返回 `task_delete_failed`，携带任务标识、现场位置、失败路径、原因，以及可选的路径长度与上限；任务保持可列出并允许重试。
- 升级到本版本时，启动阶段对既有 `output/` 任务做一次幂等回填（任务行、规则结果、KPI 历史点），回填完成前不执行留存清理。

## 6. 包分类与解压

### 6.1 分类规则

分类只依据上传网元类型和配置声明的真实来源路径，不再通过成员内容嗅探或通用扩展名兜底。
静态配置位于：

```text
deploy/config/classify_rules.yaml
```

配置顶层严格为 `{version, profiles, routes}`，必须声明 `UMF`、`CSP`、`GENERIC` profile。
巡检包 profile 等于规范化 product；日志补充包固定使用 `GENERIC`。每条 route 声明：

- 阶段：`alarm`、`precise`、`ignore`、`fallback`。
- 动作：`copy`、`expand`、`decompress`、`expand_recursive`、`select_and_decompress`、`ignore`、`fallback`。
- 来源目录 glob、文件名 glob、优先级、profile 集合和目标模板。
- 可选 selection include/exclude；exclude 始终优先于 include。

匹配顺序固定为阶段优先、阶段内 priority 优先、同级 route id 稳定排序。告警路线跨 UMF/CSP
生效并高于 ignore；CSP 非告警内容不进入工作分类现场。目录段和文件名匹配不区分大小写，
落位保留来源大小写。

配置加载时拒绝重复 YAML key、未知字段、非法动作/category/target、不可达 fallback、profile
交集内同 phase/priority 的重叠 pattern。加载后对规范化有效配置计算 SHA-256 fingerprint；
仅修改注释、空白、映射顺序或 route 顺序不得改变 fingerprint。

内部审计 category 为 `config`、`status`、`operation`、`kpi`、`alarm`、`log`、`chr`、`other`，
不等同于公共 `RuleCategory`。物理目标根由配置模板决定，例如 `basic/`、`mml/`、`logs/`、
`chr/`、`host-debug/`、`host-system/`、`kpi/`、`alarm/` 和 `other/`。

按需展开只适用于配置明确声明的归档。未声明的 KPI/MESH/MML/CHR/Host/Service Logs 归档
不读取成员；未命中任何精细路线的归档按 fallback 原样保留。选中 `.gz` 成员时只去除一层
`.gz` 后缀，exclude 与未选成员进入 ignored 审计，不进入 catalog。

### 6.2 两个隐藏单元与 manifest v5

- 主包先解压为 `.main/` 证据现场，原始子压缩包和原始 `.log.gz` 都保留在该现场。
- 隐藏单元只有 `pkg.extract.main` 和 `pkg.extract.classification`；前者建立证据现场，后者完成分类发布。
- 分类在 `.classification.staging/` 构建目标根和 catalog；摘要复核通过后交换目标根，并通过 `os.replace()` 原子发布 `manifest.json`。
- 发布失败按已完成交换的逆序回滚；成功后只清理代码 allowlist 中的 legacy 分类根，不触碰 `.main/`、prepared、rules、reports、任务摘要或执行日志。
- manifest v5 严格记录 `main` 证据快照、product/package kind、classification snapshot、path limit、entries、ignored、conflicts、failures、catalog 和 summary。
- `.main/` 证据指纹按相对路径、size 和 SHA-256 的 canonical JSON 计算；原始包 checksum 始终是重建依据。
- v1-v4 manifest 一律不可复用。v5 只有 checksum、evidence fingerprint、product、package kind、配置/发布/path-limit 指纹和目标根全部一致且 catalog 摘要有效时才复用。
- catalog 只包含成功落位且摘要匹配的普通文件；不得包含 `.main/`、manifest、staging、prepared、rules、reports、task.json、execution.log 或链接。
- 单个子归档/成员失败记录稳定 `error_code` 和 reason，classification 返回 `WARN` 并继续发布其他合法文件；配置、证据或发布失败返回 `ERROR`，阻断 prepare/inspect。

### 6.3 固定安全预算

- 最大归档深度 8，最大成员路径深度 12。
- 单归档最多 100000 个文件，单任务最多 200000 个文件。
- 单文件最大 2 GiB，任务累计解压最大 3 GiB。
- 预算为代码固定值，任务和 YAML 不可覆盖；超限只影响对应归档或成员，并写 FailureRecord。

### 6.4 安全限制

所有解压必须防：

- 路径穿越。
- 符号链接攻击。
- 文件数超限。
- 单文件超限。
- 总解压体积超限。
- 嵌套深度超限。

子归档或成员超限/异常不应中断整个任务，应记录 FailureRecord；配置、证据现场或原子发布失败必须使 classification 为 `ERROR` 并阻断规则阶段。

### 6.5 真实样例

真实包结构基准见：

```text
docs/example/real-package-structure.md
```

基准映射包括：UMF/CSP 告警统一进入 `alarm/`；`PerfResult_*.zip` 的 73 个成员进入
`kpi/`；`CollectExport*.zip` 的 14 个 CSV 进入 `other/MESH Application Metrics/`；
Service Logs 只保留 98 个业务主日志并将 85 个 `.log.gz` 展开为 `.log`；CHR 选择并解压
3 个 `.bil.gz` 为 `chr/*.bil`。所有排除成员必须出现在 ignored 审计中。

当前活动普通规则为 `alarm.active_state`、`alarm.recurrence` 与 `kpi.measurement_units`。上述映射只决定安全解压、
分类落位和证据保留；告警 CSV 会触发两条仅分析告警文件的规则，其余日志、配置、状态、资源和 CHR 文件仍只保留证据，
不代表恢复对应业务规则。

## 7. 规则模型与执行编排

### 7.1 优先级

| 优先级 | 职责 | 示例 |
| --- | --- | --- |
| P0 | 隐藏的数据准备与解压基础设施 | `pkg.extract.main`、`pkg.extract.classification` |
| P1 | 单维度阈值、统计、完整性检查 | `alarm.active_state`、`alarm.recurrence`、`kpi.measurement_units` |
| P2 | 跨维度关联、趋势、根因分析（当前无活动普通规则） | 无 |

规则执行按优先级升序分组；组内按规则编码排序。

活动普通规则范围只包含告警与 KPI 两类：告警规则仅分析 `alarm_all` 匹配的直属 CSV，KPI 规则仅分析
`kpi_all` 匹配的测量单元 CSV。配置、日志、资源和话统类业务规则模块已删除，不能重新注册、启停、重跑或重建；
已持久化的历史结果继续只读可查。新增其他类别规则必须经过新的规格、契约与规则库范围审查。

### 7.2 依赖

规则只声明：

```text
source_patterns[]  对 TaskFileCatalog 的 POSIX 相对路径执行 re.fullmatch() 的正则
outputs.metrics[]  声明的指标契约
可选 prepare       规则私有预处理声明
```

执行器维护 `EXTRACT → PREPARE → INSPECT` 阶段屏障，但不维护普通规则依赖图。普通规则只能读取自己的匹配文件或自己的 prepared 数据；`pkg.extract.main` 与 `pkg.extract.classification` 是隐藏解压基础设施，prepare 是隐藏规则私有准备单元，都不作为普通规则展示。

执行编排细节：

- `EXTRACT` 与收尾（结果落盘、摘要、报告）永不并行；主包 `pkg.extract.main` 失败时任务失败，不进入 PREPARE。
- 父进程先规划（匹配文件、prepare 缓存命中判定、skip 判定），只把真正需要执行的单元交给固定 4 进程的 `spawn` 进程池；阶段内待执行单元 < 3 或匹配文件总字节 < 8MB 时整体串行直通，不建池。
- 进程池按阶段惰性创建、在 PREPARE 与 INSPECT 之间复用，任务结束（含异常与主包失败路径）在 `finally` 中回收，不残留子进程。
- 父进程是 `execution.log`、`rules/*.json`、任务摘要与报告的唯一写入者；worker 只回传结果与日志条目，单元日志按计划序写入，保证每行完整 JSON 且不交错。
- 单个 prepare 失败只把 owner 规则置为 `skip`（原因“预处理未就绪”）；单条规则异常或 worker 非正常退出只把该单元记为 `error`，其余单元继续。
- 每个阶段写 `stage_parallel_start` / `stage_parallel_done`，记录 `mode`、直通原因、`workers`、`pending_units`、`matched_bytes`、`wall_ms`、父子峰值 RSS 与最慢单元耗时（统一为字节）。
- 单规则重跑（`verify-one`）保持串行、不建池，只改动目标规则 JSON、任务摘要与报告。

### 7.3 Rule Contract

注册规则必须声明：

- `code`
- `name`
- `category`
- `severity`
- `priority`
- `rule_version`
- `hidden`
- `description`
- `recommendation`
- `source_patterns[]`
- `outputs.metrics[]`
- 可选 `params[]`

校验要求：

- 描述和建议非空。
- metric key 与 unit 必须稳定。
- `pass` / `warn` / `fail` 必须满足输出契约。
- `skip` / `error` 豁免输出契约校验，但必须有原因或异常信息。

### 7.4 规则私有 prepare

- 一个普通规则最多声明一个 prepare；prepare 代码必须唯一。
- prepare 不声明 priority、severity、outputs 或公共 artifact。
- prepared 路径固定为 `output/<task_id>/prepared/<owner_code>/`。
- 缓存 marker 是 `.prepare.sha256`，内容为当前 owner 规则 Python 文件内容的 SHA-256。
- marker 不存在或不一致时重建；一致时复用；prepare 失败不写 marker。
- 不做输入 checksum、输出 manifest 或单个 prepared 文件缺失检查。
- prepare 执行顺序为 `owner priority → owner code → prepare code`。
- PREPARE 阶段内最多 4 个进程并行（固定并行度）；prepare 之间保持无依赖。

### 7.5 状态语义

| 状态 | 含义 | 展示 |
| --- | --- | --- |
| `pass` | 通过 | 绿 |
| `warn` | 告警 | 黄 |
| `fail` | 失败 | 红 |
| `error` | 执行异常 | 灰 |
| `skip` | 跳过 | 蓝，展示原因 |

`skip` 必须填写 `skip_reason`。无数据、格式不适用或解析失败时使用 `skip`，
不得静默通过或抛出任务级异常。

### 7.6 重跑与重建重跑

重跑会刷新、复用或不触碰的数据清单见 [`docs/design/task-rerun.md`](design/task-rerun.md)。

- 先确保 `.main/` 证据现场与 manifest v5 分类现场可复用；缺失、指纹变化或不可复用时按复用矩阵重建。
- 再从 manifest catalog 构建 `TaskFileCatalog`，执行目标规则私有 prepare 或复用其缓存。
- 最后按目标规则 `source_patterns` 重新匹配文件并执行目标规则。
- 只重写目标规则 JSON，再重建任务摘要和 HTML 报告。
- 不自动补跑其他普通规则，不建立规则间依赖图。

显式重建重跑与普通重跑分离：

- 全量重建删除并重建任务输出目录，强制重建解压现场、全部 prepare、普通规则和 KPI 快照。
- 增量重建强制重建解压现场和目标规则私有 prepare，只重算指定普通规则，保留未选规则结果和既有 KPI 快照。
- 重建预检失败时不修改任务输出；原始上传包始终只读。
- 详细刷新范围见 [`docs/design/task-rerun.md`](design/task-rerun.md)。

- 规则逻辑变化必须升级 `rule_version`。

### 7.7 日志文件处理（历史兼容）

- 日志规则已随 037 规则库收缩下线，当前不会产生新的日志巡检结果。
- 解压阶段仍先把 `.log.gz` 展开为同目录同名 `.log`，便于保留可读证据。
- `.main/` 内保留原始 `.log.gz` 作为证据；工作现场的冲突/失败 `.log.gz` 也保留用于排查。
- 物理落位目录是 `logs/`；契约类别仍然是 `log`。历史日志结果继续按既有字段只读展示。

## 8. 接口与前端

### 8.1 API 契约

OpenAPI 契约文件：

```text
docs/api/openapi.yaml
```

原则：

- 任务、系统、规则等既有接口使用 `/api/v2`；基础指标配置资源使用 `/api/v3`。
- 资源接口直接返回资源 JSON，不套壳。
- 创建/重跑类操作返回 `202 + Location`。
- 错误响应统一为 `{code, message, detail}`。
- 列表使用 `page` / `page_size` 并返回总数。
- 破坏性变更进入新版本，避免改变既有字段语义。

后端使用 Pydantic 和 FastAPI 保证契约一致；前端 API 客户端由 OpenAPI 生成：

```bash
python build.py gen-web-api
```

禁止手写与契约不一致的调用代码。

### 8.2 页面结构

| 路由 | 页面 |
| --- | --- |
| `/` | 任务列表 |
| `/tasks/:taskId` | 任务详情 |
| `/tasks/:taskId/rules/:ruleCode` | 规则详情 |
| `/tasks/:taskId/report` | 报告预览 |
| `/tasks/:taskId/logs` | 执行日志 |
| `/inspectors` | 规则管理 |
| `/kpi-resources` | 基础指标配置 |
| `/dicts` | 数据字典 |

前端原则：

- 桌面优先，不做移动端适配。
- 卡片化、留白充足、信息密度适中。
- 状态徽标使用统一语义色。
- 规则详情优先渲染指标图表；无图表结构时使用通用表格兜底。
- 发现列表展示 severity、evidence、source_file、recommendation。
- 单规则重跑后只增量刷新该规则；任务执行中可轮询刷新摘要。

## 9. 数据模型

数据模型细节见：

```text
docs/data-model.md
```

核心层级：

```text
InspectionTask
└── SystemInspection
    └── RuleResult
        ├── Metric[]
        └── Finding[]
```

持久化原则：

- 任务、系统、规则、发现使用契约 Schema 定义。
- 本地 CLI 和在线 API 返回同一套结构，且都写入同一个 SQLite 快照，双模式结果一致。
- 界面展示数据（任务列表/详情、规则结果、发现、指标、KPI 趋势）唯一来源是 SQLite：规则结果按 `task_id + rule_code` 最新一次执行整批替换，不做版本历史。
- 规则结果 JSON 同时留在 `output/<task_id>/rules/` 作为执行期现场副本，供报告渲染与单规则重跑复用；现场缺失不影响界面查询。
- `metric.key` 是跨任务稳定标识，不可随意变更。

## 10. 存储策略

默认存储：

- SQLite：任务快照（元数据、运行字段 `last_run_at` / `duration_ms`、准备摘要、包 checksum）、任务规则结果与 KPI 历史点、局点设备台账资产、KPI 分类状态/修订/审计，以及 KPI 指标口径、公式、阈值、容量、展示、公共配置和配置审计。
- KPI 基础资源：`deploy/data/kpi/base/` 只保存基础指标和预留单位；Git 是基础资源权威来源，SQLite 是动态口径权威来源。
- 文件：原始包、解压数据、规则结果副本、报告、执行日志、任务 KPI 快照和任务台账证据 `inventory.json`；文件是执行期现场，不是界面展示的数据源。
- 结果文档按任务 → 规则平铺组织。
- 磁盘现场留存：`uploads/<task_id>/` 与 `output/<task_id>/` 只保留最近 50 个任务（按 `COALESCE(last_run_at, created_at)` 倒序），执行中任务豁免；无配置入口，删除失败下次任务结束时重试。
- 现场缺失语义：报告与执行日志接口返回 410 `scene_cleaned`；重跑/重建返回 410 并提示重新上传同名数据包、确认覆盖后全量重建；界面重传同名包先覆盖确认再全量重建，创建接口保留 checksum 兜底矩阵（一致写回现场、不一致 409 `package_checksum_conflict`）。

默认不引入：

- PostgreSQL
- Redis
- Kafka
- 分布式执行器
- 外部对象存储

可选演进：

- 多人/大规模场景可切换 PostgreSQL。
- 契约和业务代码不应绑定具体数据库实现。
- 性能优化在功能稳定后按需引入。

## 11. 可观测性

- 健康检查：`GET /healthz`。
- Prometheus 指标：`GET /metrics`。
- 结构化日志：structlog。
- 任务执行日志：`output/<task_id>/execution.log`。
- 日志应覆盖任务创建、解压、子包处理、分类落位、规则执行、异常和报告生成。
- 业务异常必须有统一错误码，禁止静默吞掉。

## 12. 测试与验收

最低质量门槛：

```bash
python build.py lint
python build.py test
```

本地流水线变更还需要：

```bash
python build.py verify
```

契约变更：

```bash
python build.py contract
python build.py gen-web-api
```

关键测试类型：

- 规则单元测试：每个巡检规则必须有测试和样例数据。
- 编排测试：优先级、依赖推导、循环依赖、artifact 版本。
- 安全测试：路径穿越、链接、解压炸弹防护。
- 契约测试：Pydantic/OpenAPI 一致性。
- 双模式测试：CLI 与 API 结果一致性，除 id/时间戳外逐字段比对。
- 前端构建：`python build.py web-build` 或等效命令。

### 7.8 KPI 测量单元巡检

KPI CSV 允许表头前存在 `key：value` 元数据行；表头按列名定位
`测量开始时间`、`测量结束时间` 和 `周期(分钟)`，该周期列之后的列均为指标值。

现行 KPI 能力由单一规则 `kpi.measurement_units`（P1）承载，匹配 `^kpi/.*\.csv$` 与 `^traffic/.*\.csv$`：

- 测量单元归属：按文件名主干匹配已启用测量单元，未归属文件计入 `unmatched_files`，多周期文件按优先级保留并在 `skipped_files` 记录跳过原因。
- 指标自动入库：任务执行时按 CSV 表头归属指标列——复用既有指标、暴露跨测量单元冲突、目录未覆盖的列自动创建并默认启用（specs/021）。
  人工注册（`/api/v5/kpi/measurement-bindings/{binding_id}/register-metric`）与绑定批量确认（`/api/v5/kpi/measurement-bindings/batch-confirm`）只作为异常修正能力。
- 判定维度：文件归属、数值可读性、指标静态阈值、任务内趋势；单文件或单指标解析失败不中断其他单元。
- 结果形态：`metadata.measurement_units[]` 保存每个测量单元的指标明细与状态，任务摘要与报告只读该结构。

在线维护入口（SQLite 权威，`docs/api/openapi.yaml` 为准）：

| 能力 | 入口 |
| --- | --- |
| 测量单元导入/列表/启停 | `/api/v5/kpi/measurement-units`、`/api/v5/kpi/measurement-units/{resource_id}` |
| 指标资源 | `/api/v5/kpi/measurement-resources`、`/api/v5/kpi/measurement-resources/{resource_id}` |
| 指标绑定 | `/api/v5/kpi/measurement-bindings`、`/api/v5/kpi/measurement-bindings/batch-confirm`、`/api/v5/kpi/measurement-bindings/{binding_id}` |
| 界面派生指标 | `/api/v5/kpi/measurement-derived`（模板限 `success_rate` / `reverse_success_rate`） |
| 单任务内趋势与版本对比 | `/api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/.../history-trend`、`.../version-candidates`、`.../version-compare` |

历史索引：KPI 结果组织完成后重建任务私有索引 `kpi/history/index.jsonl`；跨任务历史查询只按需流式读取候选任务索引。
时间输入按 SQLite 公共配置中的 `input_timezone` 解释，持久化为 UTC。

历史设计（已被替代，不得作为现行指引）：`/api/v3/kpi/resource-metrics` 基础指标配置中心、v4 时代的动态口径配置中心与
任务级分类线索接口均已退役；`deploy/data/kpi/` 资源目录与
`kpi.api`、`kpi.media`、`kpi.call` 三条领域规则不再是运行时依赖。

### 7.9 扫描规则生成辅助

`tools/generate_scan_rules.py` 用于在无法提供真实压缩包时，从本地解压目录提取全部文件名并生成
`source_patterns` YAML 草稿。默认按目录和文件名中的连续数字泛化；也可选择按目录泛化或逐文件精确匹配。
草稿中的 `matched_files` 仅用于人工核对，不参与运行时匹配。用户修改 `source_patterns` 后执行
`validate` 子命令，可检查非法正则和漏配文件；校验语义与规则执行器的 `re.fullmatch()` 一致。

#### 扫描配置与本地输入

规则可用 `source_refs` 引用 `deploy/config/scan_rules.yaml` 中的稳定扫描组；注册表装载后
把引用展开为运行时 `source_patterns`。普通规则必须声明 `source_patterns` 或 `source_refs`
之一，不能同时声明两者。

```yaml
version: 1
groups:
  alarm_all:
    description: 告警目录直属 CSV
    source_patterns:
      - '^alarm/[^/]+\.csv$'
  kpi_all:
    description: KPI 测量单元 CSV（含话统目录）
    source_patterns:
      - '^kpi/.*\.csv$'
      - '^traffic/.*\.csv$'
disabled_rules: []
```

`disabled_rules` 用于首次初始化规则启停状态时导入默认停用状态；注册表装载后仍保留全部规则元数据和私有
prepare。界面状态初始化后，SQLite 中的规则启停状态是唯一执行事实来源，后续手工修改配置不会覆盖已保存状态。
状态列表和任务执行前会惰性初始化普通规则；执行器按任务开始时的启用集合过滤普通规则和 owner 私有 prepare。

```python
Inspector(
    code="alarm.active_state",
    source_refs=["alarm_all"],
)
```

规则生成工具推荐复用 `local_run/` 压缩包对应的任务解压现场：

```bash
output/task-<cleaned-package-name>/
```

先执行 `python main.py` 生成任务现场，再让扫描工具读取任务根目录：

```bash
python main.py

python tools/generate_scan_rules.py generate --source-dir output/task-<cleaned-package-name> --output deploy/config/scan_rules.draft.yaml

python tools/generate_scan_rules.py validate --source-dir output/task-<cleaned-package-name> --rules deploy/config/scan_rules.yaml
```

Windows 上推荐使用 Git Bash 或 WSL。YAML 中的 `source_patterns` 必须使用 POSIX `/` 分隔符；
运行时任务清单会把相对路径统一转换为 `/` 后再做 `re.fullmatch()`。路径包含空格时加引号。

### 7.10 未清除告警与反复上报巡检

告警能力由两条独立 P1 规则组成，均通过 `alarm_all` 只匹配 `^alarm/[^/]+\.csv$`，因此不读取嵌套目录、
非 CSV、操作日志、配置、状态文件或其他任务数据：

- `alarm.active_state`：以告警状态列中的 `Not Cleared` 为唯一活动判据，输出未清除记录、对象分组、严重级、
  持续时长、原始重复次数与估算上报总数，并按最高严重级、重复量和持续时长排序。
- `alarm.recurrence`：按应用与告警 ID 汇总生命周期，输出对象明细、状态分布、短告警、快速复发、重复上报、
  重置清除等事实，不消费活动规则结果。

两条规则共用 `app/inspectors/alarm/common.py` 的纯解析与归一化模块。该模块不构造 `RuleResult`、不写 prepared
数据，两条规则也没有 `prepare` 或任何规则间依赖。表头、状态、严重级和对象键的中英文别名集中在公共映射中；
未知术语和未知表头进入质量统计供审计，不能静默错映射。当前已覆盖 UTF-8 BOM、GB18030、无时区按 UTC+8
解释以及带偏移时间转 UTC。

“总次数”固定展示两个独立口径：原始 `Σ Repeat Times` 与估算 `Σ(1 + Repeat Times)`。后者不是精确事件总数。
规则不判断计划内/计划外或操作时间/非操作时间；只陈述告警文件中的发生、持续、对象、重复和快速复发事实。
`coverage.end_at` 是最大有效告警时间，不是真实恢复时刻或任务执行时刻。`Reset Cleared` 仅表示清除状态被重置，
不代表稳定恢复；规则也不会根据观察末刻之后没有记录来推断恢复。

结果分别写入 `metadata.alarm_active` 与 `metadata.alarm_recurrence`，规则详情页和 HTML 报告的“告警优先处置”
区块读取相同结构。单规则重跑只重写目标规则、任务摘要和报告，不执行或重建另一条告警规则。

### 7.11 告警规则的历史只读兼容

`alarm.stat` 与 `alarm.flapping` 已随 037 规则库收缩删除，不再是活动能力，也不存在对应的 `scan_rules.yaml` 扫描组。历史任务中已持久化的结果和 `metadata.alarm_flapping` 仍可读取，规则详情页继续按既有字段渲染分组证据；这类结果不可重新启停、重跑或重建。

历史告警结果的字段与判定语义见 [`specs/030-alarm-flapping/contracts/alarm-flapping-result.md`](../specs/030-alarm-flapping/contracts/alarm-flapping-result.md)。该规格仅用于解释历史数据，不得作为恢复活动告警规则的依据。
