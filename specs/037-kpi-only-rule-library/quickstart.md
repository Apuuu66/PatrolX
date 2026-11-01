# 快速验证：KPI-only 规则库收缩

## 前置条件

在实现 worktree 根目录执行：

```bash
python build.py install
```

本功能只使用 `tests/fixtures/` 的合成包，不读取 `uploads/` 或真实 `DataCollect/` 数据。

## 1. 验证活动规则目录

```bash
.venv/bin/python - <<'PY'
from app.inspectors.registry import registry
from app.services.rule_states import get_enabled_rule_codes

registry.load_all()
normal = {rule.code for rule in registry.all()}
hidden = {rule.code for rule in registry.all(include_hidden=True) if rule.hidden}
assert normal == {"kpi.measurement_units"}, normal
assert "pkg.extract.main" in hidden
assert all(code.startswith("pkg.extract.") for code in hidden)
assert get_enabled_rule_codes() == {"kpi.measurement_units"}
print("active:", sorted(normal))
print("hidden:", len(hidden))
PY
```

预期：普通规则只有 KPI，hidden 集合包含 8 条解压基础设施。

## 2. 验证 KPI 命中、skip 与台账

```bash
.venv/bin/python -m pytest -q \
  tests/test_kpi_measurement_scenarios.py \
  tests/test_scan_config_registry.py \
  tests/test_real_package.py \
  tests/test_inventory_task_flow.py
```

预期：

- KPI 合成包产生 `kpi.measurement_units` 非 skip 结果。
- 无 KPI 输入时唯一普通结果为 `skip`，且 `skip_reason` 非空。
- 任务结果只含 1 条普通规则。
- 设备台账至少写入 1 台设备。
- 原包 SHA-256 前后一致。

## 3. 验证历史结果读取与重跑拒绝

```bash
.venv/bin/python -m pytest -q \
  tests/test_baseline_review.py \
  tests/test_api.py \
  tests/test_api_robustness.py \
  tests/test_rerun_status.py \
  tests/test_task_rebuild.py
```

预期：

- 预置的历史非 KPI 规则 JSON 可通过 `GET /api/v2/tasks/{task_id}/rules/{code}` 读取。
- 该规则不出现在 `/api/v2/inspectors`。
- `POST /rerun` 与增量 `POST /rebuild` 返回 `400 unknown_rule`，任务现场摘要不变。

## 4. 验证分类、解压与非 KPI 数据保留

```bash
.venv/bin/python -m pytest -q \
  tests/test_archive.py \
  tests/test_classify.py \
  tests/test_extraction_site.py \
  tests/test_baseline_pipeline.py
```

预期：7 个分类目录仍生成，非 KPI 文件被保留但不会创建非 KPI 普通规则结果。

## 5. 后端质量门禁与全流程

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py verify
```

## 6. 前端与历史详情交互

```bash
.venv/bin/python build.py web-build
.venv/bin/python build.py e2e
```

预期：

- 规则目录、启停页和新任务页面只展示 KPI 普通规则。
- 历史非 KPI 规则详情仍可打开并展示已保存结果，不依赖活动 inspector 元数据。
- 不出现已删除规则可重跑的提示。

## 7. 契约同步

```bash
.venv/bin/python build.py contract
```

预期：OpenAPI 结构校验通过；Schema 与生成客户端无破坏性变化。
