# PatrolX 真实样例结构基准

本文档记录 `App Problem Scene` 真实样例的完整结构，是后续包解析、分类落位和巡检规则设计的默认基准。完整原始示例与文件内容见 `docs/example/zip.txt`。

## 基准包

- 主包：`ZZapp01BCN_app_Problem_scene_333.zip`
- 嵌套日志子包：`ServiceLog_20260901011314.zip`
- 本地实际路径：`uploads/ZZapp01BCN_app_Problem_scene_333.zip`

## 原始主包结构

```text
ZZapp01BCN_app_Problem_scene_333.zip
└── ZZapp01BCN_app Problem scene_333/
    └── 333/
        └── app Problem scene/
            ├── Alarm Information/
            │   ├── alarm_history_202609010101137101.csv
            │   └── alarm_summary_202609010101137101.json
            ├── Basic Information/
            │   ├── system_info.ini
            │   └── version.ini
            ├── KPI/
            │   └── kpi_202609010101137101.csv
            ├── Resource/
            │   └── pod_cpu_mem_202609010101137101.txt
            ├── Traffic/
            │   └── call_stat_202609010101137101.txt
            └── Service Logs (Problem)/
                └── ServiceLog_20260901011314.zip
```

注意：目录名中的业务类别是 `Alarm Information`、`Basic Information`、`KPI`、`Resource`、`Traffic`、`Service Logs (Problem)` 等自然语言名称，不等于 PatrolX 的七类目录枚举值。分类落位应依赖文件名规律和分类规则表，不能假设源包目录名已经规范。

## 分类映射

| 源目录 | 文件 | PatrolX 类别 | 现有消费规则 |
| --- | --- | --- | --- |
| `Alarm Information/` | `alarm_history_*.csv`、`alarm_summary_*.json` | `alarm` | `alarm.stat` |
| `Basic Information/` | `system_info.ini`、`version.ini` | `config` | `config.check` |
| `KPI/` | `kpi_*.csv` | `kpi` | `kpi.threshold` |
| `Resource/` | `pod_cpu_mem_*.txt` | `resource` | `resource.check` |
| `Traffic/` | `call_stat_*.txt` | `traffic` | `traffic.stat` |
| `Service Logs (Problem)/` | `ServiceLog_*.zip` | `log` | `pkg.extract.logs` 状态汇总 → `log.filter` → 日志分析规则 |

分类依据要点：

- `alarm_history.csv`：文件名含 `alarm`，优先归告警；不因 `.csv` 扩展名归 KPI。
- `alarm_summary.json`：文件名含 `alarm`，优先归告警；不因 `.json` 扩展名归配置。
- `system_info.ini` / `version.ini`：扩展名和基础信息语义归配置。
- `kpi_*.csv`：文件名含 `kpi`。
- `pod_cpu_mem_*.txt`：文件名含 `pod` / `mem`。
- `call_stat_*.txt`：文件名含 `call`。
- `ServiceLog_*.zip`：文件名含 `service` / `log`，归日志子包，由递归解压服务展开为最终 `.log`。

## PatrolX 解压后的完整目录结构

任务 ID 由包名生成，解压后的落位结果如下：

```text
output/<task_id>/
├── .main/
│   ├── ZZapp01BCN_app Problem scene_333.zip
│   └── Service Logs (Problem)/
│       └── ServiceLog_20260901011314.zip
├── alarm/
│   └── ZZapp01BCN_app Problem scene_333/
│       └── 333/
│           └── app Problem scene/
│               └── Alarm Information/
│                   ├── alarm_history_202609010101137101.csv
│                   └── alarm_summary_202609010101137101.json
├── config/
│   └── ZZapp01BCN_app Problem scene_333/
│       └── 333/
│           └── app Problem scene/
│               └── Basic Information/
│                   ├── system_info.ini
│                   └── version.ini
├── kpi/
│   └── ZZapp01BCN_app Problem scene_333/
│       └── 333/
│           └── app Problem scene/
│               └── KPI/
│                   └── kpi_202609010101137101.csv
├── resource/
│   └── ZZapp01BCN_app Problem scene_333/
│       └── 333/
│           └── app Problem scene/
│               └── Resource/
│                   └── pod_cpu_mem_202609010101137101.txt
├── traffic/
│   └── ZZapp01BCN_app Problem scene_333/
│       └── 333/
│           └── app Problem scene/
│               └── Traffic/
│                   └── call_stat_202609010101137101.txt
├── logs/
│   └── ServiceLog_20260901011314/
│       ├── AAAService/
│       │   └── logs/
│       │       └── paas-192.168.2.2/
│       │           ├── aaa_service_20260901011314.log
│       │           └── aaa_service_history_20260901011314.log
│       └── AppService/
│           └── logs/
│               └── paas-192.168.2.2/
│                   ├── app_service_20260901011314.log
│                   ├── app_service_error_20260901011314.log
│                   └── app_service_history_20260901011314.log
├── rules/
├── .patrolx-extracted.json
├── report.html
├── task.json
├── system.json
└── execution.log
```

其中：

- `report.html` 位于 `output/<task_id>/report.html`。
- `.main/` 保留主包解压原始现场和所有原始压缩包；普通规则不读取该目录。
- 分类目录只保留最终解压结果；`logs/` 不保留子压缩包或已成功展开的 `.log.gz`。
- 历史日志 `*.log.gz` 在 `logs/` 内展开为同名 `.log`。
- `.patrolx-extracted.json` 使用 v3 结构记录主包现场、子包、`.log.gz`、失败和拒绝状态。
- `rules/` 存放契约化规则结果；规则通过 `source_patterns` 直读任务工作现场。
- 原始主包保留在 `uploads/<task_id>/` 下。

## 日志子包详细结构

`ServiceLog_*.zip` 解压后按业务服务和节点分层：

```text
ServiceLog_20260901011314.zip
├── AAAService/
│   └── logs/
│       └── paas-192.168.2.2/
│           ├── aaa_service_20260901011314.log
│           └── aaa_service_history_20260901011314.log
└── AppService/
    └── logs/
        └── paas-192.168.2.2/
            ├── app_service_20260901011314.log
            ├── app_service_error_20260901011314.log
            └── app_service_history_20260901011314.log
```

解析规则：

- `ServiceLog_*` 是日志子包容器目录，不是服务名。
- `ServiceLog_*` 之后的第一个业务目录是服务名，例如 `AAAService`、`AppService`。
- 服务名不限定固定枚举，应从目录结构动态识别。
- `logs/` 之后的节点目录是节点名，例如 `paas-192.168.2.2`。
- 同一服务的普通日志、错误日志和历史日志必须聚合到同一服务。
- 解压服务先把 `*.log.gz` 展开为同名 `*.log`；日志规则递归检索最终 `*.log`。

日志过滤规范化产物应包含：

```json
{
  "service": "AppService",
  "node": "paas-192.168.2.2",
  "source_file": "logs/ServiceLog_20260901011314/AppService/logs/paas-192.168.2.2/app_service_20260901011314.log",
  "line_no": 2,
  "timestamp": "2026-09-01T10:00:01Z",
  "level": "ERROR",
  "message": "2026-09-01T10:00:01Z ERROR app db connection pool exhausted"
}
```

## 各类数据的巡检要点

| 类别 | 样例案例 | 巡检关注点 |
| --- | --- | --- |
| `alarm` | 数据库连接池耗尽、SCTP 链路中断、CPU 使用率偏高 | 告警数量、严重级别分布、未处理告警、告警与日志/KPI 的关联 |
| `config` | `system_info.ini`、`version.ini` | 基础配置完整性、关键配置项、版本信息 |
| `kpi` | 呼叫成功率、附着成功率、接通率 | 阈值检查、趋势/基线比对、数据完整性 |
| `resource` | Pod CPU/内存快照 | CPU/内存水位、限额余量、资源热点 |
| `traffic` | 总呼叫量、应答率 | 话务量统计、接通/应答质量、异常波动 |
| `log` | 连接池耗尽、认证失败、SCTP 重连失败、历史 gzip 错误 | 服务/节点维度过滤、错误密度、重复错误、堆栈异常、错误集中度 |

## 后续实现约定

1. 新增解析和规则时，优先兼容本基准结构，不假设源包目录名已经规范化。
2. 分类规则应保持可配置；客户目录变化优先通过规则表适配。
3. 日志规则必须识别服务与节点；解压后的 `.log.gz` 已成为同名 `.log`，规则只读取最终 `.log`。
4. P0/P1/P2 日志规则只读取 `TaskFileCatalog` 匹配到的最终源日志；不依赖其他普通规则产物。
5. 如果出现新的真实包结构，应新增基准章节和对应测试样例，不应直接破坏本样例的兼容性。
