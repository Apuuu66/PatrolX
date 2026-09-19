# 快速开始：KPI 基础数据管理

## 1. 查看权威配置

```bash
ls -1 deploy/data/kpi/base
ls -1 deploy/data/kpi/rules
```

基础指标与规则按类型分文件保存；不要手工编辑 `output/<task_id>/kpi/kpi_catalog_snapshot.json`。

## 2. 离线刷新基础指标和预留单位

准备资源 CSV，表头仍为：

```text
资源id,中文描述,英文描述
```

执行：

```bash
.venv/bin/python -m app.tools.kpi_catalog generate \
  --csv local_run/resource_metrics/resources.csv \
  --data-dir deploy/data/kpi
```

命令只更新：

- `deploy/data/kpi/base/metrics.json`
- `deploy/data/kpi/base/units.json`

不会修改：

- `deploy/data/kpi/rules/common.json`
- `deploy/data/kpi/rules/metric-rules.json`
- `deploy/data/kpi/rules/thresholds.json`
- `deploy/data/kpi/rules/capacity-rules.json`
- `deploy/data/kpi/rules/display-rules.json`

CSV 是完整基础指标快照；源文件中不存在的旧指标会被移除。如果被移除指标仍被规则引用，生成或目录校验会失败。

## 3. 修改规则

按类型编辑对应规则文件，例如：

```bash
$EDITOR deploy/data/kpi/rules/thresholds.json
```

保存后由 Git review。下一次新任务会使用最新配置；旧任务快照不变。

## 4. 创建新任务

```bash
python build.py run
# 或本地 CLI 执行
.venv/bin/python -m app.cli run --package <zip-or-tar.gz>
```

任务首次需要 KPI 配置时，会在任务目录写入：

```text
output/<task_id>/kpi/kpi_catalog_snapshot.json
```

## 5. 查看任务快照

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
path = Path('output/<task_id>/kpi/kpi_catalog_snapshot.json')
data = json.loads(path.read_text())
print(data['base_data_version'])
print(data['classification_version'])
print(len(data['metrics']))
print(data['rules'].keys())
PY
```

## 6. 重跑边界

- 已有有效快照：重跑复用，不刷新。
- 新任务：首次需要 KPI 配置时生成快照。
- 指定规则重跑且快照缺失：失败，不使用当前配置重建历史快照。
- 需要新配置结果：删除任务后重新上传。
