# 快速验证：KPI 跨任务历史趋势

## 前置条件

1. 至少准备两个覆盖不同日期的 KPI 巡检压缩包。
2. 两个任务使用相同设备 ID。
3. 两个包包含相同测量单元、指标、行对象和周期。
4. 当前任务的 KPI 数据中存在可解析的测量开始时间和周期。

## 本地全流程

```bash
.venv/bin/python build.py install
.venv/bin/python build.py verify
.venv/bin/python build.py lint
.venv/bin/python build.py test
cd web && npm test && npm run build
```

## 验证设备 ID

1. 打开任务创建页。
2. 上传压缩包并填写设备 ID。
3. 创建成功后打开任务详情，确认显示设备 ID。
4. 使用 admin 修改设备 ID，确认详情立即更新。
5. 重跑或重建任务，确认设备 ID 不丢失。

预期：

- 普通用户看不到可用编辑入口，或编辑请求被后端 403 拒绝。
- pending/running 任务不允许修改设备 ID。
- 未填写设备 ID 的任务仍能正常巡检。

## 验证历史趋势

1. 打开当前任务的 KPI 测量单元结果。
2. 点击某个已有单任务趋势的指标趋势缩略图。
3. 切换到“历史对比”视图。
4. 确认显示最近 7 个自然日窗口。
5. 确认历史曲线只包含相同设备、测量单元、指标、行对象和周期的点。
6. 查看历史中位数基线、当前值、偏差和显著偏离提示。

预期：

- 任务首屏没有历史趋势请求。
- 打开单个趋势弹窗时只发起一次该指标的历史请求。
- 无历史、索引缺失或样本不足时显示明确中文原因，并仍可查看单任务趋势。

## 验证索引与隔离

对一个完成任务检查：

```bash
test -f output/<task_id>/kpi/history/index.jsonl
head -n 1 output/<task_id>/kpi/history/index.jsonl
```

预期：

- 文件为 UTF-8 JSONL。
- 每行包含 `task_id`、`measurement_unit_id`、`metric_resource_id`、`object_key`、`period_minutes`、`measured_at`、`value`。
- 不包含 `device_id`。
- 删除任务后，`output/<task_id>/kpi/history/index.jsonl` 不存在。

## 契约验证

```bash
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
```

预期：

- OpenAPI 校验通过。
- 前端 API 客户端重新生成。
- `TaskSummary.device_id`、设备 ID 修改接口和历史趋势接口出现在生成客户端中。
