# 快速验证：任务重建重跑

## 全量重建

1. 上传或复用 `uploads/` 中的一个 `zip` / `tar.gz` 任务。
2. 等待任务完成后修改或保持当前 KPI 配置。
3. 在任务列表选择“全量重建”，阅读破坏性提示并确认。
4. 轮询任务详情直到完成。
5. 验证规则结果、摘要和报告已重建；`kpi/kpi_catalog_snapshot.json` 使用当前配置；原始包字节不变。
6. 再次使用“普通重跑”，确认它不清理输出、不强制重建解压现场、不刷新快照。

## 增量重建

1. 打开已完成或失败任务详情。
2. 选择一条或多条普通规则，发起“重建重跑”。
3. 轮询任务详情直到完成。
4. 验证目标规则已更新，未选择规则保持不变。
5. 验证既有 KPI 快照内容保持不变。
6. 对 KPI 规则发起增量重建时，快照缺失或损坏必须在执行前被拒绝。

## API 最小请求

```bash
curl -X POST 'http://127.0.0.1:8000/api/v2/tasks/<task_id>/rebuild' \
  -H 'Content-Type: application/json' \
  -d '{"mode":"full","confirmed":true,"trigger_source":"api"}'
```

增量：

```bash
curl -X POST 'http://127.0.0.1:8000/api/v2/tasks/<task_id>/rebuild' \
  -H 'Content-Type: application/json' \
  -d '{"mode":"incremental","confirmed":true,"trigger_source":"ui","rule_codes":["<rule_code>"]}'
```
