# PatrolX 真实样例结构基准

本文档记录 `App Problem Scene` 真实样例的结构、分类落位和规则适配基准。原始示例见 `docs/example/zip.txt`。

## 基准包

- 主包：`ZZapp01BCN_app_Problem_scene_333.zip`
- 仓库内测试夹具：`tests/fixtures/sample/sample.zip`
- 本地运行输入：生成到临时目录，或复制到已忽略的 `uploads/` 后上传；运行时输入不得入库
- 生成器：`tests/fixtures/make_real_package.py`

## 原始主包结构

```text
ZZapp01BCN_app_Problem_scene_333.zip
└── ZZapp01BCN_app Problem scene_333/
    └── 333/
        └── app Problem scene/
            ├── Alarm Information/
            │   └── alarm_history_202609010101137101.zip
            ├── Basic Information/
            │   ├── LST ME.txt
            │   ├── system_info.ini
            │   └── version.ini
            ├── KPI/
            │   └── PerfResult_202609010101137101.zip
            └── Service Logs (Problem)/
                └── ServiceLog_20260901011314.zip
```

`alarm_history_*.zip` 内部只有多个告警 CSV，没有 `alarm_summary.json`。`PerfResult_*.zip` 内部都是测量单元 CSV；展开时按压缩包成员归组统一进入 `kpi/`。当前活动普通规则仅 `kpi.measurement_units`，告警、配置、日志、资源和话统文件仍会安全分类保留，但不会触发对应业务的普通规则。

`Basic Information/LST ME.txt` 是网元清单，样例同时保留键值记录和真实导出的表头加数据行格式。键值记录包含 `UMF-SZ-01`、`CSP-SZ-01`（含软件版本）和 `CSP-SZ-02`（缺软件版本）；表格式记录追加 `TABLE-CSP-01`（使用补丁版本）和 `TABLE-UMF-01`（补丁版本为 `null`，回退基础版本）。文件中的网元类型可使用 `umf` / `csp` 或 `UMF` / `CSP`，解析器会把上传 `product` 与清单值统一转为大写后比较，上传值始终是唯一筛选依据。

文件头部在第一条网元记录之前携带一行执行时间，行尾格式为 `YYYY-MM-DD  HH:MM:SS`：

```text
+++    CSP/*xx*/     2026-09-01  10:00:00
```

样例生成器使用固定时间戳 `2026-09-01  10:00:00`。解析器只扫描第一条设备记录之前的头部区域，取首个行尾匹配行；该行不参与设备记录解析，文件内全部设备共用这一执行时间。时间按北京时间（UTC+8）解释并存为 UTC。

## UMF 真实目录分类基准

合成样例在既有主包内容之外加入以下 UMF 目录，用于验证配置驱动的按需分类。外层设备名、问题编号和包装目录只作为不稳定的包装层存在，不进入分类目标：

```text
Outer Device/
└── Problem 038/
    └── wrapper/
        └── UMF Problem Scene/
            ├── Basic Information About the UMF/Nested/config.ini
            ├── debugging commands/Diagnostic.JSON
            ├── Equipment Status/equipment.csv
            ├── MESH Information (Problem)/mesh.txt
            ├── System Resources/resources.txt
            ├── operation logs/OPERATIONLOG_HISTORY_20260918.CSV
            ├── MML Configurations/
            │   ├── EXP MML.txt
            │   └── EXPMML_20260918.zip
            ├── Performance Measurement Results/PerfResult_20260918.zip
            ├── MESH Application Metrics/CollectExport_20260918.zip
            ├── Service Logs (Problem)/ServiceLogs_20260918.zip
            ├── CHR Information/ServiceLogs_20260918.zip
            ├── Host Debugging Logs/DEBUG.tar.gz
            ├── Host System Logs/OS.tar.gz
            ├── collectandcheck.ini
            └── Unlisted/
                ├── custom.dat
                └── UnknownBundle.ZIP
```

### 场景根与目录匹配

`deploy/config/classify_rules.yaml` 为 UMF profile 声明 13 个场景 anchor，包括 `Basic Information About the UMF`、`Operation Logs`、`MML Configurations` 和 `Performance Measurement Results` 等。分类器扫描 `.main/` 中命中 anchor 的完整目录段，先按 anchor 父目录精确聚类，再优先选择覆盖 anchor 种类最多、命中次数最多且路径最具体的目录作为 scene root。因此即使包中只有 `Operation Logs` 和 `MML Configurations`，也能剥离设备名、问题编号和包装层。

目录段和文件名 glob 匹配不区分大小写，落位时保留来源原始大小写。`capture_root` 使用命中路径中最右侧的完整同名目录段，`{suffix}` 从该段之后开始。例如重复出现 `Basic Information About the UMF/.../basic information about the umf/Sub/Config.TXT` 时，目标为 `basic/Sub/Config.TXT`。

### UMF 目标映射

| route | 来源（scene 相对） | 动作 | category | target |
| --- | --- | --- | --- | --- |
| `umf.basic` | `Basic Information About the UMF/**` / `*` | copy | `config` | `basic/{suffix}` |
| `umf.debug` | `Debugging Commands/**` / `*` | copy | `status` | `debug/{suffix}` |
| `umf.equipment-status` | `Equipment Status/**` / `*` | copy | `status` | `status/{suffix}` |
| `umf.mesh-status` | `MESH Information (Problem)/**` / `*` | copy | `status` | `status/{suffix}` |
| `umf.system-resources` | `System Resources/**` / `*` | copy | `status` | `status/{suffix}` |
| `umf.operation-log` | `Operation Logs` / `operationlog_history_*.csv` | copy | `operation` | `operation-log/{suffix}` |
| `umf.mml-file` | `MML Configurations` / `EXP MML.txt` | copy | `config` | `mml/{suffix}` |
| `umf.mml-archive` | `MML Configurations` / `EXPMML_*.zip` | expand | `config` | `mml/{member}` |
| `umf.kpi` | `Performance Measurement Results` / `PerfResult_*.zip` | expand | `kpi` | `kpi/{member}` |
| `umf.mesh-metrics` | `MESH Application Metrics` / `CollectExport*.zip` | expand | `other` | `other/MESH Application Metrics/{archive_stem}/{member}` |
| `umf.service-logs` | `Service Logs (Problem)` / `ServiceLogs_*.zip` | select_and_decompress | `log` | `logs/{service}/{node_path}/{name_without_gz}` |
| `umf.chr` | `CHR Information` / `ServiceLogs_*.zip` | select_and_decompress | `chr` | `chr/{member}` |
| `umf.host-debug` | `Host Debugging Logs` / `DEBUG.tar.gz` | expand | `log` | `host-debug/{member}` |
| `umf.host-system` | `Host System Logs` / `OS.tar.gz` | expand | `log` | `host-system/{member}` |
| `umf.other` | `**` / `*` | fallback | `other` | `other/{suffix}` |
| `umf.ignore-outside-scene` | evidence / `**` / `*` | ignore | — | 仅写忽略审计 |

`PerfResult_*.zip` 的全部 73 个成员直接进入 `kpi/`，不按成员文件名或扩展名二次分类。`CollectExport*.zip` 的 14 个 CSV 进入以归档 stem 命名的 `other/MESH Application Metrics/<archive_stem>/` 命名空间。MML ZIP 同样按单一 `expand` 路线进入 `mml/`。

Service Logs 归档使用 include/exclude 选择：13 个业务主日志和 85 个轮转 `.log.gz` 共生成 98 个 `.log`；RScheck、dblog、UFP、monitor、start/proxy、bbox 和 `LocalLogReport.csv` 均只写 ignored。CHR 归档选择 3 个 `**/*.bil.gz` 并去除一层 `.gz`，`LocalLogReport.csv` 与其他成员只写 ignored。Host Debug/System 归档展开后，把其中的 `**/*.log.gz` 解压为 `.log`，同包非日志成员仍按成员路径保留。

未声明的 `UnknownBundle.ZIP` 按 `umf.other` 原样复制，不读取或推断其成员；场景内 `collectandcheck.ini` 和未命中普通文件也按 `umf.other` 保留场景相对路径。场景根之外的 `collectandcheck.ini` 等文件命中 `umf.ignore-outside-scene`，只写忽略审计。CSP 非告警内容命中 `csp.ignore-non-alarm`，只写忽略审计，不进入工作分类现场。

这些目录后缀、文件模式和目标模板均位于部署配置中；调整真实目录时只需修改配置，不在分类器中新增 UMF 目录分支。

## 嵌套子包结构

### 告警包

```text
alarm_history_202609010101137101.zip
├── alarm_history_202609010101137101_001.csv
├── alarm_history_202609010101137101_002.csv
└── alarm_history_202609010101137101_003.csv
```

告警 CSV 使用真实导出表头（12 列）：

```text
告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息
```

列语义与解析映射：

| 真实列 | 解析用途 |
| --- | --- |
| `告警流水号` | 记录标识，参与跨文件重复行判定 |
| `告警ID` | `alarm_code`，与 `应用名称` 组成闪断判定分组键 |
| `应用名称` | 分组对象（`object`），实例明细保留在 `定位信息` |
| `告警名称` | 展示用描述 |
| `告警级别` | 中文口径，归一化为 `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` |
| `发生时间` / `清除时间` | 生命周期起止；清除时间为空即视为未清除，真实导出没有独立状态列 |
| `清除类型` | 展示清除方式（自动/手动）；恢复结论仍只取决于清除时间与观察窗 |
| `告警重复次数`、`事件类型`、`应用ID`、`定位信息` | 记录上下文，供展示与定位，不参与判定 |

`_003.csv` 保留为历史闪断检测的固定演示证据（告警 1050–1053）。`alarm.stat` 与 `alarm.flapping` 已下线，不再从当前包执行；静态历史夹具只用于验证既有结果的只读展示。

### 性能包

```text
PerfResult_202609010101137101.zip
├── ne333_Call_Session_API_Statistics_5_0_202609020000.csv
├── ne333_Call_Session_API_Statistics_15_0_202609020000.csv
├── ne333_Call_Session_API_Statistics_30_0_202609020000.csv
├── ne333_Call_Session_API_Statistics_60_0_202609020000.csv
├── ne333_Container_Metric_Unit_5_0_202609020000.csv
└── ne333_Container_Metric_Unit_15_0_202609020000.csv
```

`Call_Session_API_Statistics_*` 是呼叫 KPI。CSV 表头前的元数据行允许存在；解析器必须按列名定位：

- `测量开始时间`
- `测量结束时间`
- `周期(分钟)`

`周期(分钟)` 之后的全部列都是 KPI/测量对象列，列名与顺序可变化，不使用固定下标。

`Container_Metric_Unit_*` 是容器 CPU/内存资源 CSV，不是 KPI，也不会被当作活动 KPI 测量单元。资源规则已下线，文件仅按既有分类规则安全保留。

### 日志包

以下通用 `ServiceLog_*.zip` 保留了历史样例和多节点结构。038 的 UMF 选择规则匹配的是 `Service Logs (Problem)/ServiceLogs_*.zip`，并使用上一节声明的 selection。

```text
ServiceLog_20260901011314.zip
├── CspService/
│   └── logs/
│       ├── paas-192.168.2.2/
│       │   ├── CspService.log
│       │   └── CspService_20260901011314.log.gz
│       └── paas-192.168.2.3/
│           └── CspService.log
├── UmfService/
│   └── logs/
│       ├── paas-192.168.2.2/
│       │   ├── UmfService.log
│       │   └── UmfService_20260901011314.log.gz
│       └── paas-192.168.2.3/
│           └── UmfService.log
└── UMFAcc/
    └── logs/
        ├── paas-192.168.2.2/
        │   ├── UMFAcc.log
        │   └── UMFAcc_20260901011314.log.gz
        └── paas-192.168.2.3/
            └── UMFAcc.log
```

同一服务的主备节点日志并存，用于展示多节点证据聚合。

`*.log.gz` 展开后为同名 `*.log`。

### UMF Service Logs 选择包

```text
Service Logs (Problem)/ServiceLogs_20260918.zip
├── UMFAcc/logs/node-01..07/pod-01..07/UMFAcc.log | UMFAcc_*.log.gz
├── UmfService/logs/node-01..07/pod-01..07/UmfService.log | UmfService_*.log.gz
├── CacheService/logs/node-03/pod-01/CacheService.log
├── ResourceManageService/logs/node-01..03/pod-01/ResourceManageService.log
├── UMFAcc/logs/node-01/{proxy,RScheck}/...
├── UMFAcc/logs/node-01/{rscheck_*.gz,dblog.tar.gz,UFP_*.log,UFP_MSS_2_0.zip,monitor_detect.log}
├── UmfService/logs/node-02/{UmfService_monitor.log,start/boot.log,proxy/request.log}
├── CacheService/logs/node-03/bbox.dat.txt
└── LocalLogReport.csv
```

选择后必须恰好得到：

```text
logs/UMFACC/<node_path>/<name>.log       # 42 个轮转 + 3 个主日志
logs/UMFSERVICE/<node_path>/<name>.log    # 43 个轮转 + 3 个主日志
logs/CACHESERVICE/<node_path>/CacheService.log
logs/RESOURCEMANAGESERVICE/<node_path>/ResourceManageService.log
```

总计 98 个业务主日志，其中 85 个来源为 `.log.gz`。exclude 优先于 include；未命中 include 的成员写 `member_not_selected`，带明确 exclude 的成员写稳定 reason，二者均不进入 catalog。

### CHR 与 Host 日志包

```text
CHR Information/ServiceLogs_20260918.zip
├── nodes/paas-01/health.bil.gz
├── nodes/paas-02/health_2.bil.gz
├── nodes/paas-03/health_3.bil.gz
├── nodes/paas-01/LocalLogReport.csv
└── nodes/paas-01/notes.txt

Host Debugging Logs/DEBUG.tar.gz
├── nodes/paas-01/DEBUG.log.gz
├── nodes/paas-01/README.txt
└── nodes/paas-02/DEBUG.log.gz

Host System Logs/OS.tar.gz
├── nodes/paas-01/OS.log.gz
├── nodes/paas-01/uptime.txt
└── nodes/paas-02/OS.log.gz
```

CHR 产生 3 个可读取的 `chr/*.bil`；Host Debug/System 的 4 个 `.log.gz` 分别产生 `host-debug/*.log` 和 `host-system/*.log`。Host 包中的 README/uptime 不属于 selection，但仍作为普通展开成员进入对应 host 根；如后续只关注日志，应在配置中显式改为 selection，而不是在代码内按扩展名猜测。

## PatrolX 工作现场

`.main/` 保留主包完整证据现场；`manifest.json` v5 是分类工作现场的唯一发布凭据，`catalog[]` 只列出成功落位的终态普通文件。下例只展示代表性路径：

```text
manifest.json
basic/Nested/config.ini
debug/Diagnostic.JSON
status/equipment.csv
status/mesh.txt
status/resources.txt
operation-log/OPERATIONLOG_HISTORY_20260918.CSV
mml/Config/Fragment.txt
mml/Config/Parameters.cfg
other/MESH Application Metrics/CollectExport_20260918/<14 CSV>
logs/UMFACC/<node_path>/<98 中对应日志>
chr/nodes/paas-01/health.bil
host-debug/nodes/paas-01/DEBUG.log
host-system/nodes/paas-01/OS.log
alarm/alarm_history_202609010101137101_001.csv
alarm/alarm_history_202609010101137101_002.csv
kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_30_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_60_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_15_0_202609020000.csv
other/...
```

上例中的 `kpi/*` 使用真实包基准名称；合成 UMF 包使用 `PerfResult_20260918.zip` 的 73 个成员。实际 task 只会命中一个可识别场景，路径以 manifest 为准。所有 ignored、conflicts 和 failures 必须能在 manifest 中逐项追溯；目录存在但未进入 catalog 的文件不得被规则读取。

## 规则适配

| 文件 | 类别 | 当前处理 |
| --- | --- | --- |
| `alarm_history_*.csv` | `alarm` | 安全保留，不触发普通规则 |
| `system_info.ini`、`version.ini` | `config` | 安全保留，不触发普通规则 |
| `LST ME.txt` | `config` | 台账解析（`site_device_lst_me`），不属于普通巡检规则 |
| `Call_Session_API_Statistics_*` | `kpi` | `kpi.measurement_units` |
| `PerfResult_*` 内 `Container_Metric_Unit_*` | `kpi` | 作为非 KPI 文件安全保留，不触发资源规则 |
| `UmfService/*.log`、`UMFAcc/*.log`、`CspService/*.log` | `log` | 安全保留，不触发普通规则 |

台账基准（`product` 取字典 code，比较时统一转为大写）：

| 上传 `product` | 命中记录 | 归档结果 |
| --- | --- | --- |
| `umf` | `UMF-SZ-01`、`TABLE-UMF-01` | 归档 2 台设备（表格式设备回退使用 `27.0.0`） |
| `csp` | `CSP-SZ-01`、`CSP-SZ-02`、`TABLE-CSP-01` | 归档 3 台设备（`CSP-SZ-02` 版本缺失，表格式设备使用 `27.0.0.13`） |
| 其他 | 无 | `not_archived`，原因 `network_element_type_no_match` |
