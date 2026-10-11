# 实现计划：任务数据长期留存与磁盘现场治理

**分支**：`034-db-backed-data-retention`（实现目标名；规划在 main 完成，实现阶段创建独立 worktree） | **日期**：2026-10-12 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/034-db-backed-data-retention/spec.md` 的功能规格

## 摘要

把"界面展示数据的唯一来源"从 `output/<task_id>/` 文件迁移到 SQLite，并引入磁盘现场留存治理：

1. **数据入库**：任务表补齐运行字段；新增"任务规则结果"与"任务 KPI 历史点"两张镜像表；任务终态由父进程一次性发布快照（任务元数据 + 全部规则结果 + KPI 历史点 + 数据准备摘要）。启动时对既有 `output/` 任务做幂等回填，保证升级前后历史任务都可查。
2. **磁盘治理**：每次任务结束（完成/失败/重跑/重建/单规则重跑）后自动执行留存清理；`uploads/<task_id>/` 与 `output/<task_id>/` 只保留按"最后运行时间，未运行按创建时间"排序最近 50 个任务；执行中的任务豁免；清理只删磁盘，不删数据库。
3. **现场缺失语义**：现场被清理后，任务列表/详情/规则结果/发现/KPI/台账仍从数据库完整可查；报告与执行日志返回明确错误码 `scene_cleaned`（410）；重跑/重建提示重新上传原始包；重传同名且 checksum 一致即恢复现场（任务记录与历史数据不变），checksum 不一致仍 409 拒绝。首次接收的包 checksum 记入数据库，作为恢复校验依据。
4. **运行元数据**：任务新增 `last_run_at`（最近一次运行的开始时刻）与 `duration_ms`（该次运行耗时，终态写入）；列表与详情展示，未运行/运行中不展示误导性时长。
5. **设备 ID 校验**：手动指定设备 ID（`reserve` 与 `PATCH /api/v2/tasks/{task_id}/device-id`）必须命中设备台账，否则拒绝且不落库。

接口为 `/api/v2`、`/api/v3/tasks` 的非破坏性增量：新增可选字段与错误码语义，无路径与既有字段含义变化；契约改动先落 `docs/api/openapi.yaml` 再落实现与前端生成客户端。磁盘留存策略与宪法"存储与运行时数据"条款冲突，本特性同步提交该条款的 MINOR 修正（2.9.0 → 2.10.0，见"复杂度跟踪"）。

## 技术上下文

**语言/版本**：Python 3.11+（仓库 `.venv` 为 3.12.x）；前端 TypeScript 5.x。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy 2.x、SQLite（后端）；React 18、Vite、Ant Design 5（前端）。不新增任何依赖。

**存储**：
- SQLite（`data/`）：`tasks` 表增量列 `last_run_at`、`duration_ms`、`package_checksum`、`preparation`；新增 `task_rule_results`（task_id + rule_code 唯一，契约 JSON + 少量索引列）与 `task_kpi_points`（任务私有 KPI 历史点的 DB 镜像）。
- `uploads/<task_id>/`、`output/<task_id>/`：保留为执行期现场（原始包、解压数据、规则 JSON、prepared、日志、报告、KPI 索引文件），按留存策略只保留最近 50 个任务。
- 既有 `kpi_measurement_*`、`inventory_*` 表不变；台账与 KPI 配置仍在 DB。

**测试**：pytest（迁移/回填/发布/读取/清理/恢复/设备校验）、OpenAPI-Pydantic 契约一致性（`python build.py contract`）、前端生成客户端（`python build.py gen-web-api`）、Playwright E2E（50+ 任务清理、清理后追溯、列表运行字段、设备 ID 校验）、`python build.py lint/test/verify/e2e/web-build`。

**目标平台**：macOS 开发机 + Linux 单节点容器部署；本地 CLI（`build.py run`/`verify-one`）与在线 API 共用同一执行与发布路径。

**性能目标**：任务列表与详情在 1 万任务量级下 P95 < 300ms（列表查询走索引与聚合，不扫 `output/`）；发布快照单事务写入，规模受规则数（每任务数十条）约束；留存清理在任务收尾内完成，典型 ≤ 1s，删除失败不阻塞终态发布；启动回填为一次幂等扫描，已入库任务直接跳过。

**约束条件**：
- 数据库是界面展示数据的唯一来源；`output/` 文件降级为执行期临时现场，不作为界面查询依据。
- 执行日志不入库；报告不入库；两者随现场清理一同消失，访问时返回明确提示。
- 规则结果以最新一次执行为准，不做版本历史；无自动重试、无断点续跑。
- 不改变"一个包 = 一个任务 = 一个输出目录"隔离模型与既有执行编排（EXTRACT → PREPARE → INSPECT）。
- 持久化时间统一 UTC、`*_at` 命名；分页默认 10 条；不新增依赖。

**规模/范围**：4 个用户故事、13 条功能需求、7 条成功标准；1 次启动迁移与回填、2 张新表 + 4 个 `tasks` 增量列、约 10 个后端读写点改造、2 个前端页面（列表/详情）+ 1 个操作弹窗提示。

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后复核。*

| 宪法条款 | 检查结论 |
| --- | --- |
| 离线优先 | 通过：只读写本地 SQLite 与本地文件，不引入采集或连接被检系统。 |
| 一个包、一个任务 | 通过：`task_id` 派生、目录隔离与任务删除语义不变；清理只针对 `uploads/<task_id>/`、`output/<task_id>/`。 |
| 契约驱动 | 通过（有条件）：先改 `docs/api/openapi.yaml` 再改实现；新增字段（`last_run_at`、`duration_ms`）为可选增量，新增错误码 `scene_cleaned`，不改既有字段含义；`build.py contract` 与生成客户端同步。 |
| 模式同构 | 通过：DB 发布与留存清理落在 CLI/API 共用的发布路径；本地任务同样写库、参与留存与列表展示。 |
| 巡检器插件架构 | 通过：不触达注册表与规则加载；清理是任务收尾动作，不进入规则编排、不硬编码业务规则。 |
| 源文件显式匹配 | 通过：`source_patterns`、`re.fullmatch()` 匹配与规则隔离零变化。 |
| 增量重跑 | 通过：规则结果按 task/rule 覆盖入库；单规则重跑只更新该规则行并刷新任务摘要；解压与 prepare 流程不变。 |
| 解压先行 / 规则私有预处理 | 通过：不修改解压、prepare 与阶段屏障；prepared 数据仍为现场产物。 |
| 幂等与可追溯 | 通过：回填按任务存在性跳过、发布按任务整批替换，可重复执行；恢复以首次接收 checksum 校验；发现证据字段原样保留在 DB。 |
| 轻量默认 | 通过：仍是 SQLite + 文件存储，单节点、无外部服务、无新依赖。 |
| 数据分页默认 | 通过：列表 `page`/`page_size` 默认 10 不变，仅数据源从文件切换为数据库。 |
| 容错 | 通过：单个规则 JSON 损坏在发布时跳过并记录日志，不中断任务；清理失败不改变任务终态，下次任务结束时自然重试。 |
| 输入文本编码兼容 / 安全解压 | 通过：不修改解码与解压；解压防护与限制保持现状。 |
| 存储与运行时数据 | **需修正（门禁条件）**：宪法现行"上传包必须保留在 `uploads/<task_id>/`、现场必须保留在 `output/<task_id>/`"与本特性"最近 50 个之外的现场自动清理"直接冲突。本特性随实现提交该条款的 MINOR 修正（版本 2.9.0 → 2.10.0）：明确磁盘现场按留存策略保留、界面展示数据长期保留在 SQLite、删除任务仍级联删除两个任务位置。修正完成前不得合入实现。 |
| 时间、命名与日志 | 通过：新增 `last_run_at`（UTC、`*_at` 命名）与 `duration_ms`；日志仍为结构化 JSON 且不入库。 |
| 语言策略 | 通过：规格产物、注释与提交信息中文，字段/标识符英文。 |
| 新功能验证与展示效果 | 通过（判定）：本特性不新增巡检数据语义，代表性样例包内容不变；展示效果由"代表性样例包派生多任务 + 51 任务清理场景的 E2E 种子"复现（与 033 同一判定口径），该判定写入 tasks.md 与 analyze 报告。 |
| 双模式兼容性 | 通过：CLI/API 契约 JSON 输出不变；新增 DB 写入不改变文件输出与 rule_version；`verify-one` 路径保持可用。 |

**阶段 1 复核**：设计产物（[data-model.md](./data-model.md)、[contracts/api-delta.md](./contracts/api-delta.md)、[quickstart.md](./quickstart.md)）确认无新增依赖、无破坏性契约变更、无规则/编排改动；唯一门禁条件仍是宪法 §存储与运行时数据 的 MINOR 修正，已列入复杂度跟踪与后续 tasks。

## 项目结构

### 文档（本功能）

```text
specs/034-db-backed-data-retention/
├── plan.md                  # 本文件
├── research.md              # R1-R11 技术决策（阶段 0）
├── data-model.md            # 表结构、字段、校验与状态迁移（阶段 1）
├── contracts/
│   └── api-delta.md         # OpenAPI 增量与错误码、恢复语义（阶段 1）
├── quickstart.md            # 可运行验证步骤（阶段 1）
├── checklists/
│   └── requirements.md      # 规格质量检查（16/16）
└── tasks.md                 # 阶段 2 输出（/speckit.tasks）
```

### 源代码（仓库根目录）

```text
app/
├── models/
│   ├── db.py                        # 增量列迁移 + 新表 + 幂等回填入口
│   └── schemas.py                   # InspectionTask/TaskSummary 增 last_run_at、duration_ms
├── services/
│   ├── task_db.py                   # 新增：任务快照发布、规则结果/KPI 点读写、列表与聚合查询
│   ├── retention.py                 # 新增：保留范围计算与磁盘清理
│   ├── tasks.py                     # 列表/详情/重建/设备 ID 走 DB；终态发布接快照与清理
│   ├── overview.py                  # 概览改为 DB 聚合
│   ├── kpi_history.py               # 历史索引读取改 DB（保留文件回退）
│   └── preparation.py               # 保留计算函数；任务详情读 DB 摘要
├── api/router.py                    # 报告/日志/重跑/重建的现场缺失提示；上传恢复语义
└── cli.py                           # 本地模式写库、运行字段发布、终态清理钩子
docs/
├── api/openapi.yaml                 # 契约先行：新增可选字段与错误码
├── architecture.md                  # 存储结构、生命周期与数据源边界回写
├── data-model.md                    # 任务/规则结果/KPI 的 DB 与文件角色
└── roadmap.md                       # "数据层统一与刷新策略""任务保留与磁盘治理"落地状态回写
.specify/memory/constitution.md      # §存储与运行时数据 MINOR 修正（2.10.0）
tests/
├── test_task_db.py                  # 新增：发布/读取/回填/覆盖语义
├── test_retention.py                # 新增：保留范围、执行中豁免、失败容错
├── test_task_restore.py             # 新增：重传恢复与冲突拒绝
├── test_task_device_id.py           # 扩展：台账存在性校验
└── test_contract.py                 # 扩展：新字段与新错误码契约
web/
├── src/pages/TaskListPage.tsx       # 列表新增最后运行时间、任务时长列
├── src/components/task-detail/      # 详情元数据与运行字段、现场清理提示
├── src/api/                          # 由 OpenAPI 重新生成
└── e2e/retention.spec.ts            # 新增：51 任务清理、清理后追溯、恢复、设备校验
```

**结构决策**：新增单一持久化服务 `app/services/task_db.py` 作为"DB 读写 + 回填"的唯一入口，新增 `app/services/retention.py` 承担磁盘留存；两者都被 `cli.py`（本地）与 `app/services/tasks.py`（在线）复用，避免双模式分叉。不在 `store.py` 内耦合数据库，保持文件工具职责单一。

## 复杂度跟踪

| 违规项/额外复杂度 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 宪法 §存储与运行时数据 MINOR 修正（2.9.0 → 2.10.0） | 解决"现场必须保留"与"最近 50 个自动清理"的直接冲突，是治理要求的显式修正 | 不改宪法直接实现：违反治理条款；不清理磁盘：与 SC-002 及用户既定目标冲突 |
| 规则结果以"契约 JSON + 少量索引列"入 DB | 保留 `RuleResult` 全字段与未来演进；索引列支撑摘要/趋势/聚合查询 | 完全关系化拆表：随契约演进频繁改表，且破坏既有 JSON 契约边界；只存文件：清理后不可查 |
| 启动时幂等回填既有 `output/` 任务 | 升级前后历史任务一致可查；保证清理不会先于入库发生 | 惰性按需回填：无法支撑跨任务 KPI 趋势与概览聚合，且存在"清理早于回填"的数据丢失窗口 |
| 新增 `task_kpi_points` 镜像表 | KPI 历史索引目前是每任务私有文件，清理后趋势与版本对比会失效（SC-003） | 清理时保留 `kpi/` 目录：破坏"最近 50 个任务现场"的一致语义；趋势实时扫全部规则 JSON：查询成本不可控 |
