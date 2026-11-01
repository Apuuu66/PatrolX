# PatrolX 真实样例结构基准

本文档记录 `App Problem Scene` 真实样例的结构、分类落位和规则适配基准。原始示例见 `docs/example/zip.txt`。

## 基准包

- 主包：`ZZapp01BCN_app_Problem_scene_333.zip`
- 本地样例：`uploads/ZZapp01BCN_app_Problem_scene_333.zip`
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

## PatrolX 工作现场

`.main/` 保留主包完整证据现场；分类工作现场只保存规则可读取的终态文件：

```text
alarm/alarm_history_202609010101137101_001.csv
alarm/alarm_history_202609010101137101_002.csv
config/LST ME.txt
config/system_info.ini
config/version.ini
kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_30_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_60_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_15_0_202609020000.csv
logs/CspService/logs/paas-192.168.2.2/CspService.log
logs/CspService/logs/paas-192.168.2.2/CspService_20260901011314.log
logs/CspService/logs/paas-192.168.2.3/CspService.log
logs/UmfService/logs/paas-192.168.2.2/UmfService.log
logs/UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log
logs/UmfService/logs/paas-192.168.2.3/UmfService.log
logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log
logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log
logs/UMFAcc/logs/paas-192.168.2.3/UMFAcc.log
```

主包内非日志类普通文件按语义类目平铺，例如 `Basic Information/system_info.ini` 落到 `config/system_info.ini`。主包内日志文件保留服务与节点路径，避免丢失识别上下文。

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
