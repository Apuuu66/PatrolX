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
- SQLite 只保存轻量任务/系统元数据；巡检结果和运行现场以文件为主。
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
   - 共享解压服务从 `.main/` 递归登记并展开子压缩包，再生成分类工作现场。
   - 文件按日志、KPI、话统、告警、配置、资源、其他分类落位；分类现场只保留最终规则输入。
   - `.log.gz` 在 `logs/` 内展开为同目录同名 `.log`，成功后移除工作现场的 `.log.gz`。
   - 同一子包通过 checksum/manifest 去重，只解压一次。
   - 项目级 `extract_policy.yaml` 先判断白名单，再判断路径跳过/全局保留；主包本身始终解压。
   - 命中跳过的嵌套压缩项和 `.log.gz` 不展开，作为 category 根下的最终文件保留；白名单命中仍走既有解压和安全流程。
   - 主包解压失败时任务失败，不进入后续阶段；子包或 gzip 局部失败保留原因并继续任务。

4. **任务文件清单**
   - 全部解压隐藏规则到达终态后，执行器构建一次内存 `TaskFileCatalog`。
   - 清单只扫描 `logs/`、`kpi/`、`traffic/`、`alarm/`、`config/`、`resource/`、`other/` 七个 category 根。
   - 策略跳过后的压缩项是 category 根下的最终文件，会进入清单；其内部成员不会进入清单。
   - `.main/`、manifest、`prepared/`、任务元数据、规则结果、报告和执行日志天然排除。
   - 清单返回 POSIX 相对路径，稳定排序、去重，并在发现链接或越界路径时拒绝。

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

### 4.1 局点设备台账数据流

- 局点来自巡检包上传时的 `province + operator`，不从压缩包猜测。
- 设备身份是省份与规范化设备名的组合；当前版本只来自 `LST ME.txt`。
- `LST ME.txt` 是记录级清单，可能包含多台设备。只有记录内网元类型与上传 `product` 规范化后相等的记录才进入本次匹配和归档；其他记录继续保留在任务证据中，便于追溯但不产生台账观测。
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
    ├── task.json
    ├── system.json
    ├── logs/
    ├── kpi/
    ├── traffic/
    ├── alarm/
    ├── config/
    ├── resource/
    ├── other/
    ├── prepared/
    │   └── <rule_code>/
    ├── rules/
    │   └── <rule_code>.json
    ├── report.html
    ├── execution.log
    └── .patrolx-extracted.json
```

职责：

| 目录 | 职责 |
| --- | --- |
| `local_run/` | 本地调试输入目录，直接执行 `python main.py` 时扫描 |
| `uploads/` | 原始包输入现场，长期保留，不修改 |
| `output/` | 处理现场，包含解压数据、结果、日志、报告 |
| `data/` | 系统元数据库等非任务输出数据 |
| `prepared/` | 规则私有中间数据，按 owner 规则隔离，不进入 API 契约 |
| `rules/` | 规则契约结果，单规则单文件，支持原地更新 |

生命周期：

- 任务和结果长期保留，不自动清理；`.main/` 在任务生命周期内永久保留。
- 删除任务必须级联删除 `uploads/<task_id>/` 和 `output/<task_id>/`；先删除文件现场，成功后再删除数据库记录。
- 文件现场删除失败返回 `task_delete_failed`，携带任务标识、现场位置、失败路径、原因，以及可选的路径长度与上限；任务保持可列出并允许重试。

## 6. 包分类与解压

### 6.1 分类规则

分类优先依据文件名、目录名、扩展名和业务名称规律，规则表在：

```text
deploy/config/classify_rules.yaml
```

当前类别：

- `log`
- `kpi`
- `traffic`
- `alarm`
- `config`
- `resource`
- `other`

规则表支持通配符和中文别名，例如：

- `*log*` → 日志
- `*kpi*` → KPI
- `*alarm*` / `*告警*` → 告警
- `*config*` / `*配置*` → 配置
- `*service*` / `*日志*` → 日志

名称无法判定时，可解压后做内部文件名或内容嗅探；仍无法判定归入 `other/`。

规则表还可声明 `archive_members`，将指定压缩包内普通成员统一归入一个类别。例如 `PerfResult_*.zip` 内的呼叫和容器 CSV 都属于测量单元，统一进入 `kpi/`；嵌套压缩包仍按自身名称分类。

### 6.2 嵌套包与 manifest

- 主包先解压为 `.main/` 证据现场，原始子压缩包和原始 `.log.gz` 都保留在该现场。
- 通用递归解压服务按子包自身文件名/内容分类；无法识别时继承父级分类，最后归入 `other/`。
- 成员展开到 `<category>/<压缩包内部相对路径>`，不再插入来源子包名目录层；KPI 包内的日志子包、日志包内的 KPI 子包都允许跨分类落位。
- 分类工作现场只保留最终解压结果；中间压缩包和已成功展开的 `.log.gz` 会被移除。
- `pkg.extract.{category}` 汇总对应分类的 manifest 终态，不再各自维护一套解压流程。
- 解压清单为 `.patrolx-extracted.json`（manifest v4），记录主包现场、各级子包、`.log.gz`、失败和拒绝状态，以及逐项路径长度与路径上限。
- manifest 必须校验版本和结构；旧版本、损坏或不匹配 checksum/path-limit 时整体安全重建现场。
- manifest v4 新现场包含 `policy` 审计节，保存归一化策略快照、fingerprint、计数器和 path-limit 快照；v3 及更早清单不允许静默迁移，必须重建。
- 有效 manifest 按 checksum、policy fingerprint 和 path-limit 快照复用现场；快照不匹配或现场缺失/损坏时按当前静态配置重建。
- 同 checksum 子包去重；任务级累计文件数、总字节数和嵌套深度构成固定安全预算。策略跳过项复制/保留时同样计费。

### 6.3 解压策略

静态项目级配置位于：

```text
deploy/config/extract_policy.yaml
```

- 决策顺序：主包始终解压 → 普通文件保持既有分类拷贝 → 白名单路径 → 白名单名称关键字 → 全局保留 → 路径跳过 → 既有解压。
- 路径作用域归一化为任务内 POSIX 目录前缀，`/0/`、`0/` 等价；`0/` 不匹配 `0a/file`。
- 名称关键字对每个目录段和最终文件名做大小写无关子串匹配，只使用外部来源路径，不读取跳过压缩包内部。
- 被跳过的压缩项复制到对应 category 根并保留相对路径；来源已在 category 子现场的项原地保留。
- 复制成功记录 `skipped`；目标冲突、复制失败或预算拒绝记录局部 `failed` / `rejected`，不覆盖既有文件。
- 执行器可在普通规则无匹配时，按同 category 的 manifest 审计补充可读 `skip_reason`；普通规则仍不读取 manifest 或策略对象。
- 该文件是部署侧静态配置，不提供在线修改 API、任务级覆盖或热更新契约。

### 6.4 安全限制

所有解压必须防：

- 路径穿越。
- 符号链接攻击。
- 文件数超限。
- 单文件超限。
- 总解压体积超限。
- 嵌套深度超限。

超限或异常文件不应中断任务，应记录到解压规则结果或执行日志。

### 6.5 真实样例

真实包结构基准见：

```text
docs/example/real-package-structure.md
```

典型映射：

- `alarm_history.csv` / `alarm_summary.json` → 告警。
- `system_info.ini` / `version.ini` → 配置。
- `kpi_*.csv` → KPI。
- `pod_cpu_mem_*.txt` → 资源。
- `call_stat_*.txt` → 话统。
- `ServiceLog_*.zip` → 日志。

`ServiceLog_*.zip` 解压后按 `ServiceLog_*/<service>/logs/<node>/*.log` 组织。服务名取
`ServiceLog_*` 之后的业务目录，节点名取 `logs/` 后的目录。日志过滤必须递归读取 `.log`
和 `.log.gz`，并记录 service、node、source_file。

## 7. 规则模型与执行编排

### 7.1 优先级

| 优先级 | 职责 | 示例 |
| --- | --- | --- |
| P0 | 数据准备、解析、过滤、标准化 | `pkg.extract.*`、`log.filter` |
| P1 | 单维度阈值、统计、完整性检查 | `log.error_density`、`kpi.api` |
| P2 | 跨维度关联、趋势、根因分析 | `traffic.compare`、`resource.trend` |

规则执行按优先级升序分组；组内按规则编码排序。

### 7.2 依赖

规则只声明：

```text
source_patterns[]  对 TaskFileCatalog 的 POSIX 相对路径执行 re.fullmatch() 的正则
outputs.metrics[]  声明的指标契约
可选 prepare       规则私有预处理声明
```

执行器维护 `EXTRACT → PREPARE → INSPECT` 阶段屏障，但不维护普通规则依赖图。普通规则只能读取自己的匹配文件或自己的 prepared 数据；`pkg.extract.*` 是隐藏解压基础设施，prepare 是隐藏规则私有准备单元，都不作为普通规则展示。

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

- 先确保 manifest 与主包解压现场可复用；缺失或不可复用时执行主包解压。
- 再构建 `TaskFileCatalog`，执行目标规则私有 prepare 或复用其缓存。
- 最后按目标规则 `source_patterns` 重新匹配文件并执行目标规则。
- 只重写目标规则 JSON，再重建任务摘要和 HTML 报告。
- 不自动补跑其他普通规则，不建立规则间依赖图。

显式重建重跑与普通重跑分离：

- 全量重建删除并重建任务输出目录，强制重建解压现场、全部 prepare、普通规则和 KPI 快照。
- 增量重建强制重建解压现场和目标规则私有 prepare，只重算指定普通规则，保留未选规则结果和既有 KPI 快照。
- 重建预检失败时不修改任务输出；原始上传包始终只读。
- 详细刷新范围见 [`docs/design/task-rerun.md`](design/task-rerun.md)。

- 规则逻辑变化必须升级 `rule_version`。

### 7.7 日志处理

- 解压阶段先把 `.log.gz` 展开为同目录同名 `.log`；日志规则只匹配最终 `.log`。
- `.main/` 内保留原始 `.log.gz` 作为证据；工作现场的冲突/失败 `.log.gz` 也保留用于排查。
- 物理落位目录是 `logs/`；契约类别仍然是 `log`。
- 日志规则解析文件路径时提取 service、node、source_file 等上下文。

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
- 本地 CLI 和在线 API 返回同一套结构。
- 规则结果独立落盘，支持单规则更新。
- `metric.key` 是跨任务稳定标识，不可随意变更。

## 10. 存储策略

默认存储：

- SQLite：任务元数据、轻量状态、局点设备台账资产、KPI 分类状态/修订/审计，以及 KPI 指标口径、公式、阈值、容量、展示、公共配置和配置审计。
- KPI 基础资源：`deploy/data/kpi/base/` 只保存基础指标和预留单位；Git 是基础资源权威来源，SQLite 是动态口径权威来源。
- 文件：原始包、解压数据、规则结果、报告、执行日志、任务 KPI 快照和任务台账证据 `inventory.json`。
- 结果文档按任务 → 规则平铺组织。

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
  alarm_history:
    description: 告警历史 CSV
    source_patterns:
      - '^alarm/(?:.*/)?alarm_history_\d+\.csv$'
disabled_rules:
  - 'log.ccc_service'
```

`disabled_rules` 用于首次初始化规则启停状态时导入默认停用状态；注册表装载后仍保留全部规则元数据和私有
prepare。界面状态初始化后，SQLite 中的规则启停状态是唯一执行事实来源，后续手工修改配置不会覆盖已保存状态。
状态列表和任务执行前会惰性初始化普通规则；执行器按任务开始时的启用集合过滤普通规则和 owner 私有 prepare。

```python
Inspector(
    code="alarm.stat",
    source_refs=["alarm_history"],
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

### 7.10 告警生命周期与闪断检测

`alarm.flapping`（P1）与 `alarm.stat` 共用 `scan_rules.yaml` 的 `alarm_all` 扫描组，但各自读取匹配文件、
互不依赖、不消费对方结果：`alarm.stat` 只做总量与未处理统计，`alarm.flapping` 负责生命周期结论。

- 分组键为 `alarm_code + object`（对应真实导出的 `告警ID + 应用名称`）；`object` 为空归入"对象未知"分组，不丢弃记录。
- 告警 CSV 以真实导出表头为准（`告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息`），
  解析层同时保留英文列名别名；`告警级别` 的中文口径（`紧急` / `严重` / `重要` / `次要`）归一化为 `CRITICAL` / `HIGH` / `MEDIUM` / `LOW`。
- 恢复证据只来自清除时间与观察窗；真实导出没有独立状态列，`status` 只由清除时间推断（`已清除` / `未清除`）并用于展示，
  绝不作为恢复依据。
- `应用ID`、`定位信息`、`事件类型`、`清除类型`、`告警重复次数` 只进入展示字段（`groups[].app_ids` / `locations` /
  `event_types` / `clear_types` / `source_repeat_max`）与 Finding 定位文案，不参与任何判定或版本口径。
- 覆盖窗口：`start_at = min(created_at)`、`end_at = max(cleared_at ?? created_at)`、`span_sec` 为整数秒。
- 观察窗：`observation_gap_sec = end_at - recent_cleared_at`；未清除、无清除时间或
  `observation_gap_sec < stable_observation_sec`（默认 1800 秒）时标记 `observation_insufficient`，
  不得判为稳定恢复。
- 复发：`repeat_window_sec`（默认 3600 秒）窗口内出现次数 `>= min_repeat_count`（默认 3）即 `repeated`。
- 操作窗：默认 `00:00-02:00`（按 +08:00 解释的本地时间），只作为证据标注（窗口内/外出现次数、
  窗口外再现、窗口后仍未恢复），不改变主状态；`operation_window_enabled=false` 时窗口计数归零、窗口标记全为 false。
- 参数默认值只在规则 `params` 表声明，结果 `metadata.alarm_flapping.policy` 携带本次生效阈值；
  纯参数取值变化不递增 `rule_version`，判定逻辑变化才递增。

主状态六选一（互斥；反复优先于短告警，观察窗不足只作兜底）：

| 状态 | 判定 | 贡献规则状态 | Finding |
| --- | --- | --- | --- |
| `uncleared_repeated` | 存在未清除记录且命中复发窗口 | fail | CRITICAL |
| `uncleared_single` | 存在未清除记录且未命中复发窗口 | warn | 无 |
| `cleared_repeated` | 全部已清除且命中复发窗口 | fail | HIGH |
| `cleared_short` | 全部已清除、未复发，最长持续 ≤ `short_alarm_sec` | warn | MEDIUM |
| `observation_insufficient` | 全部已清除、未复发、非短告警，但观察窗不足 | warn | 无 |
| `cleared_stable` | 全部已清除、未复发且观察窗充足 | pass | 无 |

容错与数据卫生：

- 行级：`created_at` 不可解析、`cleared_at` 存在但不可解析、`cleared_at < created_at`、`alarm_code` 缺失的行计入
  `excluded_rows` 并记录原因分类；`alarm_id + created_at + alarm_code + object` 重复的行计入 `duplicate_rows` 且只统计一次。
- 文件级：单个文件解析失败只计入 `failed_files`，不影响其他文件。
- 无匹配文件或全部记录时间不可解析时返回 `skip` + `skip_reason`，不静默通过、不伪装为 `pass`。
- `groups` 超过 `groups_max`（500）时按状态优先级截断并在 `totals.groups_truncated` 标注；Finding 上限 20 条。

结果契约见 [`specs/030-alarm-flapping/contracts/alarm-flapping-result.md`](../specs/030-alarm-flapping/contracts/alarm-flapping-result.md)；
规则详情页由"告警生命周期分组"面板渲染 `metadata.alarm_flapping`（六态计数、覆盖窗口、生效阈值与分组明细）。
