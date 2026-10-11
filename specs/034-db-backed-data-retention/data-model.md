# 阶段 1 数据模型：任务数据长期留存与磁盘现场治理

**功能**：`034-db-backed-data-retention` | **日期**：2026-10-12

本文件描述实现阶段要落地的表结构、字段语义、校验规则与状态迁移。契约字段以 `docs/api/openapi.yaml` 为准，本文件不替代 OpenAPI。

## 1. 角色边界

| 数据 | 存储位置 | 生命周期 | 界面读取 |
| --- | --- | --- | --- |
| 任务元数据、运行字段、stats、preparation 摘要 | SQLite `tasks` | 长期保留（人工删除除外） | DB |
| 规则结果（含隐藏规则）、发现、指标 | SQLite `task_rule_results`（契约 JSON）+ `output/<task_id>/rules/*.json`（现场副本） | DB 长期；文件随现场清理 | DB |
| KPI 历史点（趋势/版本对比） | SQLite `task_kpi_points` + `output/<task_id>/kpi/history/index.jsonl`（现场副本） | DB 长期；文件随现场清理 | DB |
| 设备台账与观测 | 既有 `inventory_*` 表 | 长期保留 | DB |
| KPI 配置（测量单元/绑定/指标资源/派生） | 既有 `kpi_measurement_*` 表 | 长期保留 | DB |
| 原始上传包 | `uploads/<task_id>/<package_file>` | 最近 50 个任务（任务结束后清理） | 不展示 |
| 解压数据、prepared、执行日志、报告、`task.json`/`system.json` | `output/<task_id>/` | 最近 50 个任务（任务结束后清理） | 仅报告/日志按文件读取，缺失时明确提示 |

## 2. `tasks` 表（增量列）

| 列 | 类型 | 可空 | 语义 |
| --- | --- | --- | --- |
| `created_at`（已有） | DateTime(timezone) | 否 | 任务创建时刻，不随运行变化；重跑/重建不覆盖 |
| `completed_at`（已有） | DateTime(timezone) | 是 | 最近一次运行的结束时刻 |
| `last_run_at`（新增） | DateTime(timezone) | 是 | 最近一次运行的**开始**时刻；每次运行开始时写入；从未运行为 NULL |
| `duration_ms`（新增） | Integer | 是 | 最近一次运行的耗时（毫秒）；仅终态写入；运行中/从未运行为 NULL |
| `package_checksum`（新增） | String(64) | 是 | 系统首次接收原始包时的 SHA-256；恢复现场与冲突判定的依据 |
| `preparation`（新增） | JSON | 是 | 任务数据准备摘要（`DataPreparation` 契约 JSON 快照），任务终态写入 |

已有列 `name`、`mode`、`status`、`trigger`、`package_file`、`customer`、`package_kind`、`version`、`stats` 语义不变。迁移方式：`init_db()` 中 `ALTER TABLE ADD COLUMN`（沿用 `_ensure_task_columns` 模式），旧行新列全部为 NULL。

### 校验规则

- `last_run_at`、`duration_ms` 只由运行生命周期写入，不由请求参数直接赋值。
- `duration_ms >= 0`；不早于 `last_run_at` 对应的运行结束时刻，计算为 `completed_at - last_run_at` 的毫秒数。
- `created_at` 在任务行已存在时保持不变；不因重跑/重建改写。
- 从未运行的任务 `last_run_at`/`duration_ms` 均为 NULL；运行中任务 `last_run_at` 非空、`duration_ms` 为 NULL。

## 3. `task_rule_results`（新增）

| 列 | 类型 | 可空 | 语义 |
| --- | --- | --- | --- |
| `id` | Integer 主键 | 否 | 自增 |
| `task_id` | String(64)，索引 | 否 | 任务标识；无外键约束（任务删除由服务层级联） |
| `rule_code` | String(128) | 否 | 规则代码，含隐藏规则（`pkg.extract.*`、prepare 相关） |
| `priority` | String(8) | 是 | P1/P2，来自结果契约 |
| `execution_order` | Integer | 是 | 展示顺序 |
| `status` | String(16)，索引 | 否 | pass/warn/fail/error/skip |
| `severity` | String(16) | 是 | 规则严重级 |
| `executed_at` | DateTime(timezone) | 是 | 规则执行时刻 |
| `finding_count` | Integer，默认 0 | 否 | 发现条数，支撑概览聚合 |
| `result` | JSON | 否 | 完整 `RuleResult` 契约 JSON（`model_dump(by_alias=True, mode="json")`） |
| `updated_at` | DateTime(timezone) | 否 | 该行最近一次发布时刻（UTC） |

约束：`UNIQUE(task_id, rule_code)`。写入语义：任务收尾"整批替换"（删除该任务全部行后按现场 `rules/*.json` 重新插入，同一事务）；单规则重跑同样整批替换，实现"最新为准、无版本历史"（FR-007）。损坏的单个规则 JSON 跳过并记录日志，其余规则正常发布。

## 4. `task_kpi_points`（新增）

| 列 | 类型 | 可空 | 语义 |
| --- | --- | --- | --- |
| `id` | Integer 主键 | 否 | 自增 |
| `task_id` | String(64)，索引 | 否 | 任务标识 |
| `rule_code` | String(128) | 是 | 产生该点的规则 |
| `measurement_unit_id` | String(64)，索引 | 是 | 测量单元 |
| `metric_resource_id` | String(64)，索引 | 是 | 指标资源 |
| `object_key` | String(256)，索引 | 是 | 对象（网元等） |
| `period_minutes` | Integer | 是 | 统计周期 |
| `measured_at` | DateTime(timezone)，索引 | 否 | 数据点时间 |
| `value` | Float | 是 | 指标值 |
| `source_file` | String(512) | 是 | 证据来源 |
| `line_number` | Integer | 是 | 证据行号 |

与 `output/<task_id>/kpi/history/index.jsonl` 的记录字段一一对应；缺失字段以 NULL 保留记录。写入语义与规则结果一致：任务收尾整批替换本任务的行。

## 5. 状态与写入时序

```text
任务创建(created_at)
  └─ 运行开始：status=running，last_run_at=开始时刻，duration_ms=NULL
       ├─ 正常收尾：status=completed，completed_at=结束时刻，duration_ms=结束-开始
       │    └─ 发布：tasks 行 + task_rule_results + task_kpi_points + preparation（单事务）
       │         └─ 写 task.json/system.json/report（现场最后写入）
       │              └─ 留存清理（不含本次任务之外的在执行任务）
       └─ 失败收尾：status=failed，completed_at/duration_ms 同上，发布已产生的结果（如主包解压失败结果）
            └─ 留存清理（同上）
```

- 单规则重跑 / 增量重建 / 全量重建：`last_run_at` 更新为本次开始时刻，`duration_ms` 覆盖为本次耗时；`created_at` 不变。
- 人工删除任务：先删 `output/<task_id>` 与 `uploads/<task_id>`，成功后删除 `task_rule_results`、`task_kpi_points`、`tasks` 行（沿用既有"文件成功才删记录"的顺序）。

## 6. 留存保留范围

- 保留集合 = 按 `COALESCE(last_run_at, created_at)` 倒序的前 50 个任务 ∪ 所有 `pending`/`running` 任务。
- 清理目标 = `uploads/` 与 `output/` 下不在保留集合中的 `<task_id>` 目录；`uploads/` 根目录中文件名可派生已知 task_id 的散包同样按保留范围清理；未消费的散包（无对应任务）不删除。
- 触发时机 = 每次任务终态发布完成后；恢复上传（FR-013）不触发。
- 清理只删磁盘，不删除或修改任何 DB 行；删除失败的目录记录日志并在下次任务结束时重试。

## 7. 启动回填（幂等）

1. 建表与增量列迁移完成后执行。
2. 扫描 `output/*/task.json`：task_id 已在 `tasks` 表中的直接跳过。
3. 对未入库任务：导入任务行（含 `stats`、`customer`、`version`、`package_kind`、时间字段、`preparation` 摘要），导入 `rules/*.json` → `task_rule_results`，导入 `kpi/history/index.jsonl` → `task_kpi_points`。
4. 单文件损坏跳过并记录结构化日志，不中断启动；回填完成前禁止执行留存清理。

## 8. 展示数据来源矩阵（FR-001）

| 界面/接口 | 数据来源（034 之后） |
| --- | --- |
| `GET /api/v2/tasks`（列表） | `tasks` 表（含 `last_run_at`、`duration_ms`） |
| `GET /api/v2/tasks/{task_id}`（详情） | `tasks` + `task_rule_results`（摘要化）+ `preparation` 列 + 台账快照 |
| `GET /api/v2/tasks/{task_id}/system` | `tasks` + `task_rule_results` 拼装 |
| `GET /api/v2/tasks/{task_id}/rules/{rule_code}` | `task_rule_results.result` |
| `GET /api/v2/overview` | `tasks` + `task_rule_results` 聚合 |
| KPI 趋势 / 版本对比 / 指标明细 | `task_kpi_points` + `task_rule_results` |
| `GET /api/v2/tasks/{task_id}/report` | 现场文件；缺失 → 410 `scene_cleaned` |
| `GET /api/v2/tasks/{task_id}/logs` | 现场文件；缺失 → 410 `scene_cleaned` |

## 9. 既有实体复用

- 设备台账：`inventory_devices.device_id` 作为手动设备 ID 的存在性校验依据（FR-010）。
- 任务台账：`inventory_parse_results` / `inventory_observations` 语义不变，继续长期保留。
- KPI 配置：`kpi_measurement_*` 不变；本特性只新增历史点的任务镜像。
