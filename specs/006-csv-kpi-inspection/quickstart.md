# 快速开始：CSV KPI 离线巡检

## 1. 准备样例包

创建一个 zip 包，包含以下文件：

```text
kpi/kpi-call-5.csv
kpi/kpi-api-15.csv
kpi/kpi-media-15.csv
```

`kpi-call-5.csv` 可使用本功能样例：

```csv
设备类型：XXX
测量单元名称：呼叫会话统计
服务名,实例,可信度,不可信原因,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数,呼叫请求成功次数,呼叫请求失败次数
BasicKpi,,可信,,2026-09-14 10:00:00,2026-09-14 10:05:00,5,100,100,0
```

`kpi-api-15.csv` 和 `kpi-media-15.csv` 使用相同三段布局即可；第一版不要求 API/媒体指标阈值。

## 2. 预期识别

- `kpi/kpi-call-5.csv` → 规则 `kpi.call`，周期 5 分钟。
- `kpi/kpi-api-15.csv` → 规则 `kpi.api`，周期 15 分钟。
- `kpi/kpi-media-15.csv` → 规则 `kpi.media`，周期 15 分钟。
- 缺少任一领域文件时，对应规则返回 `skip` 和明确原因。
- 其他目录或文件名不符合模板的 CSV 不被这三条规则处理。

## 3. 本地验证

```bash
make install
make verify
```

也可以在任务包已存在时重跑单条规则：

```bash
make verify-one RULE=kpi.api
make verify-one RULE=kpi.media
make verify-one RULE=kpi.call
```

质量门禁：

```bash
make lint
make test
```

## 4. 检查结果

打开 Web 任务详情或检查：

```text
output/<task_id>/rules/kpi.api.json
output/<task_id>/rules/kpi.media.json
output/<task_id>/rules/kpi.call.json
```

对上面样例，`kpi.call` 应满足：

- `file_count = 1`
- `record_count = 1`
- `parse_error_count = 0`
- `consistency_error_count = 0`
- `success_breach_count = 0`（样例成功率为 100%）
- `failure_breach_count = 0`
- 结果状态为 `fail`
- finding 的 `source_file` 为 `kpi/kpi-call-5.csv`
- evidence 中可见原始请求/成功/失败值、派生率、99% 阈值和配置来源

`统计峰值`、`最大并发` 只出现在记录值展示中；不出现其成功率/失败率，也不产生容量阈值告警。

## 5. 错误隔离用例

在同一个包中加入：

```text
kpi/kpi-call-5.csv
```

并让其中一行周期写成 `15`、时间范围与 15 分钟不一致。预期：

- `kpi.call` 仍处理 `kpi/kpi-call-15.csv`；
- 坏文件/坏行出现在 `metadata.kpi_files[].errors`；
- `parse_error_count > 0`；
- 规则状态为 `fail`；
- `kpi.api`、`kpi.media` 不受影响。
