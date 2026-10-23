# 实现计划：设备台账版本以 LST ME 执行时间为准

**分支**：`035-lst-me-execution-time`（实现目标名；规划在 main 完成，实现阶段创建独立 worktree） | **日期**：2026-10-23 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/035-lst-me-execution-time/spec.md` 的功能规格

## 摘要

把设备台账"观测时间"的来源从"任务完成时间"改为"`LST ME.txt` 头部行尾记录的执行时间"，让"当前版本"由执行时间裁决，而不是由上传/完成顺序裁决：

1. **执行时间解析**：台账解析器在 `LST ME.txt` 头部区域（设备记录开始之前）取**第一个**行尾匹配 `YYYY-MM-DD` + 空白 + `HH:MM:SS` 的行，作为该文件内全部设备记录的执行时间；按北京时间（UTC+8，固定偏移）解释、转换为 UTC 存储。解析不到或明显不可信（晚于任务完成时间 5 分钟以上）时回退任务完成时间。每个来源文件独立解析一个时间。
2. **观测时间口径**：设备观测时间取该设备所有来源文件中可用的最近执行时间；`inventory_observations` 新增 `time_source`（`lst_me` / `task`）与 `time_source_reason`（回退原因）两列并回归契约。当前版本、最近观测、首次观测、观测次数、版本历史排序与质量问题检测时间统一使用该口径。
3. **证据与契约**：`inventory.json` 证据 `schema_version` 2 → 3，新增 `execution_time` 段（按来源文件记录原文、行号、解析结果与状态）；`parser_version` 3 → 4；任务详情台账面板展示执行时间与来源，设备列表/详情展示时间来源标识。
4. **存量与回滚语义**：不回填存量观测；历史证据缺 `execution_time` 时按"任务完成时间"语义读取，不报错、不显示空白；重跑/重建后按新口径生效。

接口为 `/api/v2` 的非破坏性增量（只新增可选字段），无路径与既有字段含义变化；契约改动先落 `docs/api/openapi.yaml` 再落实现与前端生成客户端。

## 技术上下文

**语言/版本**：Python 3.11+（仓库 `.venv` 为 3.12.x）；前端 TypeScript 5.x。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy 2.x、SQLite（后端）；React 18、Vite、Ant Design 5（前端）。不新增任何依赖；时区用固定 `timezone(timedelta(hours=8))`，不依赖 tzdata（Windows 默认无 tz 数据库）。

**存储**：
- SQLite `inventory_observations` 增量列：`time_source`（`VARCHAR(16)`，默认 `task`）、`time_source_reason`（`VARCHAR(32)`，可空）；沿用既有 `_ensure_*_columns` 幂等迁移方式。
- `inventory_parse_results.snapshot`：承载新的 `execution_time` 证据段，不新增列。
- `output/<task_id>/inventory.json`：证据现场副本，schema 升级为 3；`inventory_devices`、KPI 表结构不变。

**测试**：pytest（解析、口径、排序、回退、证据兼容）、OpenAPI-Pydantic 契约一致性（`python build.py contract`）、前端生成客户端（`python build.py gen-web-api`）、前端组件测试（`web/src/**` vitest）与 Playwright E2E（乱序补传当前版本不回退）、`python build.py lint/test`。

**目标平台**：macOS 开发机 + Linux 单节点容器部署；本地 CLI（`build.py run`/`verify-one`）与在线 API 共用同一解析与归档路径。

**性能目标**：头部时间解析只扫描文件头部区域（设备记录起点即停止），对现有解析耗时影响可忽略；台账查询仍为单表索引查询，无新增 N+1 或全表扫描。

**约束条件**：
- 时间统一 UTC 存储、`*_at` 命名；北京时间仅在解析边界转换。
- 解析失败不得中断任务：时间解析失败只回退时间来源，不影响归档与任务终态。
- 不改变版本冲突语义、设备身份（省份 + 规范化设备名）、"一个包 = 一个任务 = 一个输出目录"隔离模型与执行编排。
- 不改变 KPI 与任务的关联口径、任务自身时间字段与留存清理策略。
- 输入解码仍走统一入口（UTF-8 / GB18030），本特性只读取已解码文本。

**规模/范围**：3 个用户故事、12 条功能需求、5 条成功标准；1 张表 2 个增量列、1 个证据 schema 升级、约 6 个后端读写点改造、3 个前端展示点（任务详情台账面板、设备列表、设备详情）、1 组代表性样例包增量。

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后复核。*

| 原则 | 结论 |
| --- | --- |
| 离线优先 | 通过：只消费包内文件，不引入任何在线采集。 |
| 一个包、一个任务 | 通过：不改变任务/目录隔离与 `task_id` 派生。 |
| 契约驱动 | 通过：先改 `docs/api/openapi.yaml` 再改实现；仅新增可选字段与证据 schema 版本，非破坏性变更，不新开版本前缀。 |
| 模式同构 | 通过：解析与归档在 CLI 与 API 共用同一服务；本地模式证据与在线一致。 |
| 巡检器插件架构 / 源文件显式匹配 | 通过：台账解析不是巡检规则，不改注册表与 `source_patterns`；`LST ME.txt` 匹配模式保持 `^config/(?:.*/)?LST ME\.txt$`。 |
| 增量重跑 / 解压先行 / 规则私有预处理 | 通过：不涉及规则执行器与 prepare；重跑/重建沿用既有覆盖语义。 |
| 幂等与可追溯 | 通过：证据保存原始时间文本、行号与解析结果；同一任务重跑覆盖得到相同观测。 |
| 轻量默认 | 通过：无外部服务、无新依赖，时间解析为纯标准库。 |
| 数据分页默认 | 通过：分页默认 10 条不变。 |
| 容错 | 通过：头部时间缺失/格式异常/不可信均只回退时间来源并记录原因，不中断任务、不丢观测。 |
| 输入文本编码兼容 / 安全解压 | 通过：复用统一解码入口与既有解压防护，不做改动。 |
| 存储与运行时数据 | 通过：证据与观测写入 SQLite 并保留，磁盘现场仍为可重建副本；不新增磁盘依赖。 |
| 时间、命名与日志 | 通过：观测时间仍为 `observed_at` 且 UTC 存储；新增字段 `time_source` / `time_source_reason` 为英文标识符，非时间字段不使用 `*_at` 命名。 |
| 语言策略 | 通过：规格产物、注释与提交信息中文，字段/标识符英文。 |
| 新功能验证与展示效果 | 通过：`tests/fixtures/make_real_package.py` 的 `LST ME.txt` 样例**只增不减**地补入头部执行时间行（固定时间戳，保持幂等），并新增"头部无时间"边界样例文件；展示效果由 E2E 覆盖设备列表/详情与任务详情。 |
| 双模式兼容性 | 通过：CLI 与 API 走同一解析与归档路径，证据 JSON 语义一致。 |

**阶段 1 复核**：设计产物（[data-model.md](./data-model.md)、[contracts/api-delta.md](./contracts/api-delta.md)、[quickstart.md](./quickstart.md)、[research.md](./research.md)）确认无新增依赖、无破坏性契约变更、不触及规则执行器与编排；宪法检查无违例，复杂度跟踪为空。

## 项目结构

### 文档（本功能）

```text
specs/035-lst-me-execution-time/
├── plan.md                  # 本文件
├── research.md              # R1-R7 技术决策（阶段 0）
├── data-model.md            # 实体、增量字段、校验与排序语义（阶段 1）
├── contracts/
│   └── api-delta.md         # OpenAPI 增量与台账证据 schema 增量（阶段 1）
├── quickstart.md            # 可运行验证步骤（阶段 1）
├── checklists/
│   └── requirements.md      # 规格质量检查
└── tasks.md                 # 阶段 2 输出（/speckit.tasks）
```

### 源代码（仓库根目录）

```text
app/
├── models/
│   ├── db.py                        # inventory_observations 增量列迁移
│   └── schemas.py                   # InventoryObservation/TaskInventory 增时间来源与执行时间证据
├── services/inventory/
│   ├── parser.py                    # 头部执行时间解析 + 证据 execution_time 段 + 版本号递增
│   ├── ledger.py                    # 观测时间取执行时间/回退、写入时间来源
│   └── queries.py                   # 当前版本、最近观测、版本历史、质量问题时间口径统一
docs/
├── api/openapi.yaml                 # 契约先行：新增可选字段
├── data-model.md                    # 台账观测时间口径与证据结构回写
└── example/real-package-structure.md # LST ME.txt 头部时间行说明与样例
tests/
├── fixtures/make_real_package.py    # 代表性样例包补入头部执行时间行（只增不减）
├── fixtures/inventory/*             # 台账解析/归档单测样例数据
├── test_inventory_parser.py         # 头部时间解析与容错
├── test_inventory_ledger.py         # 观测时间口径、回退、乱序补传不回退
└── test_contract.py                 # 新增字段契约一致性
web/
├── src/components/task-detail/TaskInventoryPanel.tsx  # 展示执行时间与来源
├── src/pages/InventoryPage.tsx                        # 最近观测列展示来源标识
├── src/pages/InventoryDevicePage.tsx                  # 观测时间/版本历史展示来源标识
├── src/api/                                           # 由 OpenAPI 重新生成
└── e2e/inventory-execution-time.spec.ts               # 乱序补传与来源展示端到端
```

**结构决策**：沿用既有分层 `api → services → inspectors/models`，台账解析/归档改动全部落在 `app/services/inventory/` 与 `app/models/`，前端只做展示与来源标识，不改变接口调用形状。

## 复杂度跟踪

无宪法的例外与违规项，不需要说明。
