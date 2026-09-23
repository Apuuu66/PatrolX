# KPI 同设备版本对比展示 fixture

- `index-current.jsonl`：`task-version-current`，设备 `device-a`，版本 `V2`。
- `index-baseline.jsonl`：`task-version-baseline`，设备 `device-a`，版本 `V1`。
- 两条数据维度均为 `MU_CALL` / `ME_CALL` / `pod-a` / 15 分钟；当前均值 130，基线均值 105。
- 测试用该数据构造任务元数据与私有历史索引，可重复验证两条曲线、版本来源和上涨摘要。
