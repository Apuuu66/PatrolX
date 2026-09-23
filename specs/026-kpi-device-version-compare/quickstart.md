# 快速验证：KPI 同设备版本对比

## 展示效果用例

目录：`tests/fixtures/kpi-version-compare/`

构造两个已完成任务：

- `task-version-current`：设备 `device-a`，版本 `V2`，索引包含 `pod-a` / 15 分钟 / `ME_CALL` 点位。
- `task-version-baseline`：设备 `device-a`，版本 `V1`，相同维度不同数值点位。

自动化测试应验证：

1. 候选接口返回 `V1` 和 `task-version-baseline`。
2. 对比接口返回两条曲线、版本、任务来源和均值摘要。
3. 同版本任务返回 `baseline_same_version`。
4. 版本未知任务显示 `version=null`、`version_known=false`。
5. 基线任务索引缺失时返回 `baseline_index_missing`。

## 手动验证

1. 启动 API + Web。
2. 打开已完成 KPI 任务，进入测量单元指标趋势。
3. 切换“版本对比”。
4. 选择历史版本 `V1`。
5. 确认界面显示：
   - 当前版本 `V2`
   - 基线版本 `V1`
   - 基线任务 ID 和完成时间
   - 当前版本、基线版本两条曲线
   - 当前均值、基线均值、绝对差值和涨跌说明
6. 切换到无数据维度，确认显示具体 `reason_code` 对应的中文提示。
