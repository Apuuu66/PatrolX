# 阶段 0 研究：任务数据长期留存与磁盘现场治理

**功能**：`034-db-backed-data-retention` | **日期**：2026-10-12

本文件记录技术决策与取舍。所有决策已对照 spec（13 条 FR / 7 条 SC）、AGENTS.md 与宪法 2.9.0。

## 现状调研结论（决策依据）

- `TaskRecord`（`app/models/db.py`）只有 `created_at` / `completed_at`，无运行时间与时长；已有 `_ensure_task_columns` 这类 `ALTER TABLE ADD COLUMN` 增量迁移机制可复用。
- 展示数据当前以 `output/` 文件为主源：`TaskService.list_tasks` 先扫 `output/*/task.json`，`TaskService.get` 先 `load_task_meta`，`_load_system_json` 先读 `system.json`，规则详情读 `rules/<code>.json`，`overview.py` 扫 `task.json`，KPI 历史/版本对比读 `output/<task_id>/kpi/history/index.jsonl`；数据库只做在线任务索引与状态兜底。
- KPI 历史索引由巡检过程写出（`app/inspectors/kpi/measurement.py` → `kpi_measurement_units.inspect_measurement_files` → `kpi_history.write_history_index`），可能发生在 INSPECT 阶段的 worker 进程，因此 DB 镜像不能放在该路径写，必须由父进程在收尾发布。
- 上传逻辑（`app/api/router.py::create_task_v3`）在同名任务已存在时只比对 `uploads/<task_id>/<filename>` 的现场文件 checksum；现场被清理后 `existing_checksum=None`，现状会无条件 409，需要改为按库中记录的 checksum 判断恢复。
- 终端发布路径：在线 `TaskService._publish_terminal`（先 DB 状态、再 `task.json`）与本地 `cli._publish_terminal`；`run_task`、`run_incremental_rebuild`、`run_single_rule` 是仅有的三个会写终态的入口（单规则重跑由 API 侧 `TaskService._execute` 收尾再发布）。
- 设备 ID 手工入口为 `PATCH /api/v2/tasks/{task_id}/device-id` → `TaskService.update_device_id`；`reserve()` 也接受可选 `device_id`。台账表为 `inventory_devices`。
- 报告（`report.html`）与执行日志（`execution.log`）当前按文件读取，报告/日志缺失时直接 404。

## R1. 规则结果入库模型与写入时机

**决策**：新增 `task_rule_results` 表，`(task_id, rule_code)` 唯一；每行存完整 `RuleResult` 契约 JSON，并冗余 `status`、`severity`、`execution_order`、`executed_at`、`finding_count`、`updated_at` 索引列。任务终态由父进程一次性发布：读取 `output/<task_id>/rules/*.json`（含隐藏规则）整批替换该任务的规则行（先删后插，同一事务）。单规则重跑同样在收尾发布时整批替换，天然实现"以最新为准、无版本历史"。

**理由**：契约 JSON 与既有 `RuleResult` 边界完全一致，契约演进不需要改表；索引列足够支撑列表摘要、状态聚合与finding 统计；整批替换避免跟踪增量差异，重跑/重建语义简单。

**备选**：
- 规则结果完全关系化（每 metric/finding 一行）：随契约演进频繁改表，且跨表拼装易偏离既有契约 JSON。
- 规则结果只留在文件：磁盘清理后规则详情、发现与 KPI 均不可查，直接违反 FR-001/FR-002/SC-001。

## R2. KPI 历史数据的长期留存

**决策**：新增 `task_kpi_points` 表，作为任务私有 `kpi/history/index.jsonl` 的 DB 镜像（字段与索引记录一一对应：task_id、rule_code、measurement_unit_id、metric_resource_id、object_key、period_minutes、measured_at、value、source_file、line_number）。父进程在任务收尾发布时读取该文件并整批替换本任务的行；启动回填时对历史任务做同样处理。`kpi_history.iter_history_index` 改为从 DB 读取（文件仅用于回填输入），趋势与版本对比逻辑保持不变。

**理由**：索引文件当前由巡检过程产生且是跨任务趋势/版本对比的唯一数据源，现场清理后若只删文件将丢失历史（违反 SC-003）；镜像表字段与既有记录结构一致，改造量最小。

**备选**：
- 清理时保留 `kpi/` 目录：违背"现场只保留最近 50 个任务"的一致语义，且现场目录残缺会带来更多歧义。
- 趋势查询实时解析全部规则 JSON：查询成本随历史线性增长，不可控。
- 在巡检进程内直接写 DB：worker 进程写 SQLite 与"父进程唯一写入者"的编排约束冲突。

## R3. 运行字段（最后运行时间 / 任务时长）与迁移

**决策**：`tasks` 表增量列 `last_run_at`（DateTime(timezone=True)，可空）与 `duration_ms`（Integer，可空）。运行开始时写 `last_run_at` = 该次运行开始时刻并清空 `duration_ms`；任务进入终态（completed/failed）时写 `duration_ms` = 终态时刻 − `last_run_at`。`created_at` 在重跑/重建时保持不变（DB 行存在则不覆盖）。迁移沿用 `_ensure_task_columns` 的 `ALTER TABLE ADD COLUMN` 模式，旧数据两列均为 NULL。

**理由**：开始时刻独立存储使"运行中"可展示（时长留空），终态再补时长；一次运行只产生一对值，重跑自然覆盖；与既有 `*_at`、UTC 约定一致。

**备选**：
- 只在终态写两个值：运行中无法体现"最近一次运行时间"，且需要额外的运行中状态字段。
- 记录运行结束时刻而非开始时刻：与 spec 澄清结论（开始时刻）冲突。

## R4. 既有历史数据的幂等回填

**决策**：`init_db()` 在完成建表与增量列迁移后执行回填：一次性读取 `output/*/task.json`，对不在 `tasks` 表中的 task_id 导入任务行（含 `stats`、`customer`、`version`、`package_kind`、`created_at`/`completed_at`、`preparation` 摘要），并导入其 `rules/*.json` 与 `kpi/history/index.jsonl`；已在库中的任务整段跳过。单文件解析失败跳过该文件并记录结构化日志，不中断启动。**回填必须先于任何留存清理执行**（清理入口以"回填已完成"为前置条件）。历史任务的 `package_checksum` 不主动回溯哈希（大包成本高），在后续重跑/重建/上传触碰时补齐。

**理由**：保证升级后"自系统首次运行以来的全部历史任务"仍可查（SC-003），并消除"清理早于入库"导致的数据丢失窗口；按存在性跳过使回填幂等且日常启动成本仅为一次目录扫描。

**备选**：
- 惰性回填（读某个任务时才导入）：概览与跨任务 KPI 无法聚合；清理仍可能先删掉未导入任务的现场。
- 每次启动全量重建镜像：对大库产生不必要的写放大。

## R5. 展示读取路径切换到数据库

**决策**：界面展示相关读取全部改为 DB：任务列表、任务详情、`/system`、`/rules/{code}`、概览聚合、KPI 历史/版本对比、测量指标明细均从 `task_db` 读取与拼装；`preparation` 读取任务行中的摘要快照。文件读取仅保留：报告渲染、执行日志、回填输入、以及执行期自身的读写。数据库无数据时返回明确错误，不再回退读文件。

**理由**：这是 FR-001 的直接要求；回填保证 DB 完整后不再需要文件兜底，避免"双源不一致"。

**备选**：DB 优先、文件兜底：看似稳健，但会让"界面数据唯一来源"形同虚设，且掩盖回填缺口。

## R6. 留存清理的触发、保留范围与豁免

**决策**：新增 `app/services/retention.py`：
- **触发**：在终态发布完成后（DB 快照已写、`task.json` 已写）执行一次清理；本地/在线、成功/失败、全量/增量/单规则路径共用同一入口。恢复上传不触发清理。
- **保留范围**：`SELECT task_id FROM tasks ORDER BY COALESCE(last_run_at, created_at) DESC LIMIT 50`，并强制并入所有 `pending`/`running` 状态任务；任务数 ≤ 50 时不做任何删除。
- **清理目标**：`uploads/<task_id>/`、`output/<task_id>/`（不在保留集合内的目录）；`uploads/` 根目录下"已消费"的散包（文件名派生 task_id 且该任务在库中）同样按保留范围清理，未消费的散包（无对应任务）不动。
- **失败容错**：单个任务目录删除失败记录结构化日志（任务、路径、原因）并继续处理其余目录；清理失败不影响任务终态，下次任务结束时自然重试。
- **并发保护**：保留集合显式包含 pending/running 任务；单节点单 worker 顺序执行，不需要额外锁。

**理由**：任务结束触发与 spec 澄清一致；按 DB 运行时间排序避免依赖文件 mtime；pending/running 豁免满足 FR-006 与边界用例。

**备选**：定时任务/启动清理：引入额外调度与时机歧义，且用户已明确"任务结束后自动清理"。

## R7. 重传恢复现场（FR-013）

**决策**：`create_task_v3` 遇到同名任务时按以下顺序判定：
1. 现场包存在 → 与现场文件 checksum 比对（保持现状）：一致返回 `TaskCreated` + `Location`（不重跑），不一致 409 `package_checksum_conflict`。
2. 现场包缺失 → 与 `tasks.package_checksum` 比对：一致则把上传包写入 `uploads/<task_id>/<package_file>` 恢复现场，返回 `TaskCreated` + `Location`，不重跑、不改历史数据、不触发清理；不一致 409 `package_checksum_conflict`。
3. 现场包缺失且库中无 checksum（升级前的历史任务）→ 若存在可读的历史包则以其 checksum 为准并回填数据库；否则拒绝并明确说明"该任务未记录原始包校验和，无法恢复"。

`tasks.package_checksum` 在上传受理（`_receive_upload` 已计算）与本地任务执行（`sha256_file`）时写入。

**理由**：以系统首次接收的 checksum 作为恢复依据，既满足"同名同校验和才恢复"，又避免为历史任务做全量重哈希。

**备选**：仅按文件名接受重传：无法防止内容替换，违背 FR-013；恢复即自动重跑：与"恢复后由用户显式发起重跑/重建"的澄清不一致。

**2026-10-13 修订**：界面重传改为 033 FR-024 的"覆盖确认 + 全量重建"（用户裁决）；本节矩阵降级为创建接口在探测未命中时的兜底，接口语义与状态码不变。

## R8. 现场缺失时的接口语义

**决策**：任务存在但现场目录缺失时：
- 报告接口 → 410 `scene_cleaned`，消息说明报告已随磁盘现场清理、核心数据仍可在任务详情查看；
- 日志接口 → 410 `scene_cleaned`，消息说明执行日志不入库且已随现场清理；
- 重跑/重建按请求前置校验拦截 → 410 `scene_cleaned`，消息说明需重新上传同名数据包、确认覆盖后全量重建；
- 输出目录存在但原始包缺失 → 保留既有 `package_missing`（409），消息补充重传恢复到现场的建议；
- 任务不存在 → 沿用 404 `not_found`。

**理由**：区分"没有这个任务"与"有任务但现场已清理"，满足 FR-011/SC-006"不得静默失败"；410 语义上表示资源曾存在但已不可用。

**备选**：继续 404：无法区分，且与"报告未生成"等临时状态混淆。

## R9. 手动设备 ID 的台账校验

**决策**：`TaskService.update_device_id` 与 `reserve` 在写入前校验非空 `device_id` 是否存在于 `inventory_devices`；不存在则抛 `device_not_found`（400，消息"设备 ID 不存在于设备台账"），不写文件、不写库、不改任务。空值语义保持现状（清空绑定不触发校验）。前端错误提示沿用统一错误消息通路。

**理由**：服务端校验是唯一可靠入口；spec 明确"从台账选择不触发额外校验"，手工输入才校验。

**备选**：仅前端做下拉限制：无法覆盖 API 直调；任务创建后设备被删除的历史任务不受影响（spec 边界已确认），因此只校验写入时刻。

## R10. 前端展示、展示效果与样例包判定

**决策**：
- 任务列表新增"最后运行时间""任务时长"两列的展示与格式化；未运行显示占位，运行中显示"运行中"且不显示时长；详情页元数据同步。
- 现场清理提示：报告/日志入口在 410 时展示错误信息与建议（重传同名包覆盖重建）；重跑/重建失败直接展示 API 消息。
- 展示效果：用代表性样例包（`tests/fixtures/make_real_package.py` 产物）派生多个任务覆盖"清理后追溯"与"重传覆盖重建"两条路径，用 E2E 种子构造 51 个任务的清理场景；本特性不新增巡检数据语义，不扩充样例包内容（与 033 同一判定口径），判定写入 tasks.md 与 analyze 报告。

**理由**：新增能力全部是存储与生命周期语义，样例包内容无法表达"第 51 个任务被清理"这类系统行为；E2E 种子是唯一可复现路径。

**备选**：为凑样例强行新增无关数据：违反"样例必须覆盖功能正常路径与关键边界"的实质要求，且稀释既有样例语义。

## R11. 文档与宪法回写

**决策**：实现阶段同步更新：
- `.specify/memory/constitution.md` §存储与运行时数据（MINOR 升版 2.9.0 → 2.10.0）：磁盘现场按留存策略保留、展示数据长期保留在 SQLite、删除任务仍级联删除两个任务位置；
- `docs/architecture.md`：存储结构、数据源边界（DB 为展示唯一来源）、留存清理生命周期；
- `docs/data-model.md`：任务/规则结果/KPI 的 DB 与文件角色；
- `docs/roadmap.md`：回写"数据层统一与刷新策略""任务保留与磁盘治理"的落地状态。

**理由**：宪法治理要求语义变更显式修正；三份权威文档当前描述"任务和结果长期保留，不自动清理"，不回写会与实现冲突。
