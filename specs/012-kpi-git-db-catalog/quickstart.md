# 快速验证：KPI 基础数据入库与分类状态存储

## 前置条件

```bash
.venv/bin/python build.py install
```

准备一个资源全集 CSV，表头固定为：

```csv
资源id,中文描述,英文描述
```

至少包含一个 `ME_*` 记录；可额外包含 `UNIT_*` 记录用于验证预留单位解析。

## 1. 生成权威 Git JSON

```bash
.venv/bin/python -m app.tools.kpi_catalog generate \
  --csv /absolute/path/resource_metrics.csv \
  --output deploy/data/kpi_catalog.json
```

期望：

- 命令成功。
- `deploy/data/kpi_catalog.json` 中 `metrics` 按 `key` 升序。
- `metrics[].unit_key` 均为 `null`。
- `units` 包含解析出的 `UNIT_*` 记录。
- `source_csv_sha256` 与 CSV 字节 SHA-256 一致。
- 再次执行输出字节不变。
- 使用 `git diff` 可评审变化。

非法样例必须失败且不生成部分文件；错误信息包含行号或资源 ID。

## 2. 分类

启动在线服务：

```bash
.venv/bin/python build.py run
```

打开 Web：

```text
http://127.0.0.1:5173/kpi-resources
```

期望：

- 导航显示「KPI 指标库」。
- 页面显示 Git JSON 中的全部基础指标。
- 初始无分类记录时全部显示未分类。
- 页面不出现资源 CSV 上传控件。
- 顶部显示基础数据版本缩略值和分类修订号。
- 选择指标和 `call` / `api` / `media` 后批量分类成功。
- 选择指标和「未分类」可改回未分类。
- 刷新后分类状态保持。

API 抽查：

```bash
curl -s 'http://127.0.0.1:8000/api/v3/kpi/resource-metrics?page=1&page_size=20'
curl -s -X PUT 'http://127.0.0.1:8000/api/v3/kpi/resource-metrics/classification' \
  -H 'Content-Type: application/json' \
  -d '{"metric_keys":["<key>"],"domain":"call","operator":"quickstart"}'
```

期望响应包含递增后的 `classification_version`，没有 `expected_revision` 字段。

分类审计抽查：

```bash
curl -s 'http://127.0.0.1:8000/api/v3/kpi/resource-metrics/classification-audits?page=1&page_size=20'
```

期望审计记录包含操作时间、操作类型、操作人、来源状态和目标状态。Web 页面也可分页查看审计。

本地 CLI 分类抽查：

```bash
.venv/bin/python -m app.cli classify-kpi --metric-key <key> --domain call
```

期望命令复用同一数据库分类服务和引用保护；审计中对应记录的 `operator` 为 `cli`。

## 3. 数据库失败行为

临时把 SQLite 路径指向不可写位置后执行 KPI 任务：

```bash
PATROLX_SQLITE_PATH=/proc/patrolx-invalid/patrolx.db .venv/bin/python build.py verify
```

期望：

- 任务失败或启动目录加载失败。
- 日志明确数据库不可用。
- 不回退旧 YAML，不产生空的有效目录。
- 恢复环境后重新执行成功。

## 4. 巡检与历史快照

放入样例数据包后执行：

```bash
.venv/bin/python build.py verify
```

期望：

- 任务目录生成 `output/<task_id>/kpi/kpi_catalog_snapshot.json`。
- 快照记录 `base_data_version` 和 `classification_version`。
- 未分类指标不进入任一 KPI 领域规则。
- 已分类指标进入对应领域并按 Git 规则聚合。
- KPI 规则结果 metadata 包含两个版本。

随后修改分类或 Git JSON，再单规则重跑：

```bash
.venv/bin/python build.py verify-one --rule kpi.call
```

期望：

- 既有任务继续读取旧快照。
- 历史规则结果中的指标定义、域归属和规则版本不变。
- 新任务使用新基础数据版本或新分类修订。

API 抽查：

```bash
curl -s 'http://127.0.0.1:8000/api/v3/tasks/<task_id>/kpi/catalog-snapshot'
```

## 5. 契约与质量门禁

```bash
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py verify
.venv/bin/python build.py web-build
```

期望：

- OpenAPI、Pydantic 和生成客户端一致。
- `/api/v2` 不再暴露 KPI 资源查询、导入或分类接口。
- `/api/v3` 分类请求包含 `operator`，不包含 `expected_revision`。
- 全流程验证通过。
- Vite 构建无 chunk 大于 500 kB 告警。
