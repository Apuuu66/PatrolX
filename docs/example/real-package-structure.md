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
            │   ├── system_info.ini
            │   └── version.ini
            ├── KPI/
            │   └── PerfResult_202609010101137101.zip
            └── Service Logs (Problem)/
                └── ServiceLog_20260901011314.zip
```

`alarm_history_*.zip` 内部只有多个告警 CSV，没有 `alarm_summary.json`。`PerfResult_*.zip` 内部都是测量单元 CSV；展开时按压缩包成员归组统一进入 `kpi/`。

## 嵌套子包结构

### 告警包

```text
alarm_history_202609010101137101.zip
├── alarm_history_202609010101137101_001.csv
└── alarm_history_202609010101137101_002.csv
```

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

`Container_Metric_Unit_*` 是容器 CPU/内存资源 CSV，不是 KPI。资源规则同样按列名识别 CPU、内存、时间与周期；CPU/内存列可按 `CPU`、`处理器`、`内存`、`memory` 等语义别名识别。

### 日志包

```text
ServiceLog_20260901011314.zip
├── UmfService/
│   └── logs/
│       └── paas-192.168.2.2/
│           ├── UmfService.log
│           └── UmfService_20260901011314.log.gz
└── UMFAcc/
    └── logs/
        └── paas-192.168.2.2/
            ├── UMFAcc.log
            └── UMFAcc_20260901011314.log.gz
```

`*.log.gz` 展开后为同名 `*.log`。

## PatrolX 工作现场

`.main/` 保留主包完整证据现场；分类工作现场只保存规则可读取的终态文件：

```text
alarm/alarm_history_202609010101137101_001.csv
alarm/alarm_history_202609010101137101_002.csv
config/system_info.ini
config/version.ini
kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_15_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_30_0_202609020000.csv
kpi/ne333_Call_Session_API_Statistics_60_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv
kpi/ne333_Container_Metric_Unit_15_0_202609020000.csv
logs/UmfService/logs/paas-192.168.2.2/UmfService.log
logs/UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log
logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log
logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log
```

主包内非日志类普通文件按语义类目平铺，例如 `Basic Information/system_info.ini` 落到 `config/system_info.ini`。主包内日志文件保留服务与节点路径，避免丢失识别上下文。

## 规则适配

| 文件 | 类别 | 规则 |
| --- | --- | --- |
| `alarm_history_*.csv` | `alarm` | `alarm.stat` |
| `system_info.ini`、`version.ini` | `config` | `config.check` |
| `Call_Session_API_Statistics_*` | `kpi` | `kpi.call` |
| `PerfResult_*` 内 `Container_Metric_Unit_*` | `kpi` | `kpi.measurement_units`、`resource.check` |
| `UmfService/*.log` | `log` | `log.umf_service` |
| `UMFAcc/*.log` | `log` | `log.umf_acc` |

服务专属日志规则只读取目录结构识别出的服务记录：

- `log.umf_service`：检查认证失败和重试定时器超限。
- `log.umf_acc`：检查连接池耗尽和 SCTP 链路错误。
