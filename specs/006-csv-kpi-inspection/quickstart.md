# 快速开始：CSV KPI 离线巡检

## 1. 准备样例包

创建一个 zip 包，包含以下文件：

```text
kpi/kpi-call-15.csv
kpi/kpi-api-15.csv
kpi/kpi-media-15.csv
```

`kpi-call-15.csv` 可使用本功能样例：

```csv
呼叫会话统计
测量周期,开始时间,结束时间,呼叫请求,请求成功,请求失败,统计峰值,最大并发
15,2026-09-14 10:00:00,2026-09-14 10:15:00,1200,1170,30,100,88
15,2026-09-14 10:15:00,2026-09-14 10:30:00,1350,1300,50,105,92
15,2026-09-14 10:30:00,2026-09-14 10:45:00,1500,1440,60,120,98
15,2026-09-14 10:45:00,2026-09-14 11:00:00,1300,1270,30,95,84
15,2026-09-14 11:00:00,2026-09-14 11:15:00,1100,1080,20,85,76
```

`kpi-api-15.csv` 和 `kpi-media-15.csv` 使用相同三段布局即可；第一版不要求 API/媒体指标阈值。

## 2. 预期识别

- `kpi/kpi-call-15.csv` → 规则 `kpi.call`，周期 15 分钟。
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
- `record_count = 5`
- `parse_error_count = 0`
- `consistency_error_count = 0`
- `success_breach_count = 5`（样例成功率均低于 99%）
- `failure_breach_count = 5`
- 结果状态为 `fail`
- finding 的 `source_file` 为 `kpi/kpi-call-15.csv`
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
