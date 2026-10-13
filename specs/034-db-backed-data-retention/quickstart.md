# 快速验证：任务数据长期留存与磁盘现场治理

验证目标：界面展示数据以 SQLite 为唯一来源（FR-001）；磁盘现场按"最近 50 个任务"自动清理（FR-004/FR-005）；清理后可完整回溯、依赖现场的操作给出明确提示（FR-011）；重传同名包提示覆盖、确认后全量重建（FR-013）；任务记录运行时间与时长（FR-008/FR-009）；手动设备 ID 台账校验（FR-010）。

契约与环境语义以 [spec.md](./spec.md)、[data-model.md](./data-model.md)、[contracts/api-delta.md](./contracts/api-delta.md) 为准，本文件只给可运行步骤。

## 前置条件

- 已执行 `python build.py install`（本机无 `python` 时使用 `.venv/bin/python`）。
- 生成代表性样例包（固定时间戳、可重复生成）：

```bash
python tests/fixtures/make_real_package.py          # 默认生成到 uploads/
```

- 留存清理会删除磁盘现场（不影响数据库内容）。在真实数据上验证前，先备份 `data/patrolx.db`、`uploads/`、`output/`，或使用独立工作副本。
- 保留额度固定为 50，无配置入口；执行中的任务豁免清理。

## 1. 单元测试与契约

```bash
python build.py lint
python build.py test          # 发布/回填/读取/清理/恢复/设备校验
python build.py contract      # OpenAPI ↔ Pydantic 一致性
python build.py gen-web-api   # 重新生成前端客户端
```

预期：全部通过；契约测试覆盖 `last_run_at`/`duration_ms` 可空性、`scene_cleaned` 410、`device_not_found` 400、`package_checksum_conflict` 409 与恢复成功路径。

## 2. 本地 CLI 全流程（双模式一致性）

```bash
python build.py verify
```

预期：本地模式与在线模式共用发布路径，任务与规则结果同样写入 SQLite；文件输出与 `rule_version` 不变。

## 3. 在线模式走查（`python build.py run` 后上传样例包执行）

### 3.1 入库快照（FR-007/FR-008）

```bash
sqlite3 data/patrolx.db "select task_id, created_at, last_run_at, completed_at, duration_ms, status from tasks order by created_at desc limit 3;"
sqlite3 data/patrolx.db "select task_id, rule_code, status, finding_count from task_rule_results where task_id='<task_id>' order by execution_order;"
sqlite3 data/patrolx.db "select count(*) from task_kpi_points where task_id='<task_id>';"
```

预期：`created_at` 与 `last_run_at` 是两个独立字段（创建时间不随运行变化）；终态任务 `duration_ms >= 0`，运行中为 NULL、从未运行为 NULL；规则结果含隐藏规则；KPI 点数与 `output/<task_id>/kpi/history/index.jsonl` 行数一致。

### 3.2 清理后仍可查（FR-001/FR-011，SC-001/SC-003）

模拟现场已清理：

```bash
rm -rf output/<task_id> uploads/<task_id>
```

预期：

- 任务列表、详情、规则详情与 KPI 趋势/版本对比/明细均正常打开，内容与清理前一致（唯一数据源为数据库，不因文件缺失报错或空白）。
- `GET /api/v2/tasks/<task_id>/report` → 410 `scene_cleaned`（提示报告已随现场清理）。
- `GET /api/v2/tasks/<task_id>/logs` → 410 `scene_cleaned`（执行日志不入库）。
- `POST /api/v2/tasks/<task_id>/rerun` 与 `/rebuild` → 410 `scene_cleaned`（不进入队列）。

### 3.3 重传覆盖与全量重建（FR-013，SC-007；2026-10-13 修订）

1. 重新上传同名原始包 → 界面提示“覆盖同名任务并全量重建？”；取消后既有任务与数据不变，磁盘不产生新文件。
2. 确认“覆盖并重建” → 清空旧任务并用当前数据包全量重建：`202` + `Location`，`uploads/<task_id>/` 与 `output/<task_id>/` 现场重新生成，任务记录以本次重建结果为准。
3. 直接用 API 重传同名包（未经界面覆盖流程）→ 由创建接口校验和矩阵兜底：现场包缺失且与首次接收 checksum 一致 → 写回现场并返回 `202`；不一致 → `409 package_checksum_conflict`，现场不被覆盖。

### 3.4 留存范围（FR-004，SC-002）

用 `tests/fixtures/make_real_package.py` 派生并执行 51 个任务后：

```bash
ls uploads | wc -l
ls output  | wc -l
```

预期：系统空闲时，除 `pending`/`running` 任务外，`uploads/` 与 `output/` 保留的任务现场均 ≤ 50，且保留集合是按 `COALESCE(last_run_at, created_at)` 倒序的最近 50 个任务；`uploads/` 根目录中可派生已知 task_id 的散包同样被清理，未消费散包不删除。

### 3.5 设备 ID 台账校验（FR-010，SC-005）

```bash
curl -s -X PATCH localhost:8000/api/v2/tasks/<task_id>/device-id \
  -H 'Content-Type: application/json' -d '{"device_id": "NOT-EXIST"}'
```

预期：400 `device_not_found`，任务记录不变；创建流程手动指定设备 ID 时同样拒绝且不落库。

## 4. 端到端与展示效果

```bash
python build.py e2e
```

重点场景：51 任务清理、清理后追溯、重传恢复、列表/详情的运行时间与时长展示、设备 ID 校验提示。

展示效果判定（与 033 同口径）：本特性不新增巡检数据语义，代表性样例包内容不变；展示效果由"代表性样例包派生多任务 + 51 任务清理场景"的 E2E 种子复现，不扩充 `tests/fixtures/make_real_package.py`。

## 5. 质量门禁

```bash
python build.py lint
python build.py test
python build.py verify
python build.py contract
python build.py gen-web-api
```

涉及前端展示改动时追加 `python build.py web-build` 与 `python build.py e2e`。

## 6. 文档与宪法一致性

- 实现随附宪法 §存储与运行时数据 MINOR 修正（2.9.0 → 2.10.0）：明确磁盘现场按留存策略保留、界面展示数据长期保留在 SQLite、删除任务仍级联删除任务位置。
- 同步回写 `docs/architecture.md`（存储结构与生命周期）、`docs/data-model.md`（任务/规则结果/KPI 的 DB 与文件角色）、`docs/roadmap.md`（数据层统一与磁盘治理落地状态）。
