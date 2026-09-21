# 快速验证

1. 准备资源目录：

```csv
资源id,中文描述,英文描述
MU__CALL_SESSION_API_STATISTICS,呼叫会话接口统计,Call Session API Statistics
ME_CALL_REQUESTS,呼叫请求次数,Call Requests
```

2. 在新版测量单元页导入 CSV，确认 MU/ME/UNIT 数量和 `Call_Session_API_Statistics` 片段。
3. 准备任务 CSV 表头：

```csv
container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)
pod-a,2026-09-02 00:00:00,2026-09-02 00:15:00,15,100
pod-b,2026-09-02 00:15:00,2026-09-02 00:30:00,15,0
```

4. 上传包含该文件的任务包；候选绑定出现后确认为 `confirmed`。
5. 重跑任务；规则 `kpi.measurement_units` 应按 `pod-a`、`pod-b` 分别展示指标，全部 0 显示 `PASS · 全 0`。
6. 验证大小写不一致进入 unmatched，多 MU 命中进入 ambiguous，解析失败进入 parse_error 且任务不中断。
