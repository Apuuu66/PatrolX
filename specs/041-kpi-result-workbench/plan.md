# 实现计划：KPI 巡检结果判读工作台

**分支**：`041-kpi-result-workbench` | **日期**：2026-11-05 | **规格**：[spec.md](./spec.md)

**输入**：来自 [spec.md](./spec.md) 的规划规格；五张 v2 合成效果图已由用户确认，媒体资源成功率证据按源包直出且不重算。

**实现状态**：Plan 已完成结构自检，`tasks.md` 已生成；效果图已确认，待 analyze/review 和规划产物提交完成后，才可从 `main` 创建实现 worktree。

## 1. 摘要

本次重构把 KPI 从“规则详情中的一个长结果面板”提升为面向维护人员的任务级结果工作台，并将巡检范围、团队关注和规则适用性拆成三个独立概念：

1. **任务级 KPI 工作台**：默认进入“需处理”，同时提供“团队关注”和“全部指标”；汇总、筛选、结果表与按需证据共用同一份服务端判定，不在前端重复计算。
2. **按网元类型共享的团队关注**：关注身份为 `network_element_type + measurement_unit_id + metric_resource_id`，同一网元类型跨任务共享，UMF/CSP 完全隔离；关注只影响查看范围，不影响巡检、报告和历史结果。
3. **测量单元级巡检范围**：测量单元是唯一日常启停粒度。单位启用后纳入全部已确认基础指标和已定义派生指标；指标、绑定、派生和维护配置不再通过 `enabled` 抑制巡检。
4. **运行时规则网元归属**：取消公共规则和规则级全局启停。业务规则由运行时配置归属一个或多个网元类型，零归属即“未归属”且不执行、不生成 `skip`。
5. **任务范围冻结与旧任务重建**：任务真正开始时冻结规则集合/版本、归属 revision、KPI 配置指纹和指标集合；旧任务不迁移、不兼容，通过任务行内“重建”按当前配置生成新快照，`task_id` 保持不变。

新能力以 `/api/v6/kpi/...` 的 OpenAPI 契约先行交付；v5 KPI 路径原地冻结；既有 `/api/v5/kpi/measurement-bindings/batch-confirm` 与 `/api/v2/inspector-states*` 仅标记 `deprecated`，不物理删除。

## 2. 技术上下文

**语言/版本**：Python 3.11+；TypeScript + React；浏览器目标为当前稳定版 Chrome。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、structlog；React、Vite、Ant Design、ECharts。

**存储**：SQLite 是界面读取与配置管理的权威来源；任务结果仍以 `output/<task_id>/` 为执行现场并镜像到数据库。新增 v6 作用域表与任务 KPI 快照表；v5 表只读冻结，不做原地语义改造。

**测试**：pytest、FastAPI contract tests、Vitest/Testing Library、Playwright、合成样例包校验。

**目标平台**：离线 Linux 服务端、本地 CLI 与在线 Web；本功能只支持桌面浏览，不增加移动端适配。

**项目类型**：Web 服务 + 本地 CLI + 前端单页应用。

**性能目标**：不对数据量做专项优化，沿用分页、按需加载和单任务范围约束；验收任务为 20 个指标，其中 10 个纳入团队关注。指标证据必须按需加载，单个证据失败不得阻断汇总或其他行。

**约束条件**：桌面宽度 1280–1920；1280px 无页面级横向滚动；1440×900 首屏显示汇总、互斥分组和至少 5 个需处理指标；所有时间 UTC 存储、字段使用 `*_at`；团队关注写入使用 revision 冲突检测。

**规模/范围**：一个包对应一个任务、一个输出目录；一个任务只有一个网元类型，日志补充包可没有规则适用网元类型；一个测量单元只属于一个网元类型；同一规则可归属多个网元类型。

## 3. 宪法检查

### 3.1 阶段 0 前置检查

| 宪法要求 | 结论 | 设计响应 |
| --- | --- | --- |
| 离线优先 | PASS | 仅消费上传归档包，不增加任何被检系统连接或在线采集。 |
| 一个包、一个任务 | PASS | 团队关注跨任务共享，但任务结果、快照与输出仍按 `task_id` 隔离；重建保持同一 `task_id`。 |
| 真实数据隔离 | PASS | 验收只使用 `tests/fixtures/make_real_package.py` 生成的合成包；效果图仅含合成数据。 |
| 效果图确认门禁 | PASS | 用户已明确确认当前 v2 效果图；媒体资源成功率证据为源包直出且不重算。 |
| 契约驱动 | PASS | 先设计 v6 OpenAPI，再更新 Pydantic/FastAPI/生成客户端；v5 字段语义不变。 |
| 模式同构 | PASS | API 与 CLI 共用 `RuleScopeResolver`、任务范围快照和 KPI 范围解析服务。 |
| 巡检器插件架构 | PASS | 规则注册元数据不变；网元归属来自运行时配置，不在规则 Python 中硬编码。 |
| 源文件显式匹配 | PASS | 保留既有 `source_patterns`/`re.fullmatch()` 语义，不引入规则间依赖。 |
| 增量重跑 | PASS | 单规则/增量重跑只允许操作任务既有快照中的规则；不在快照返回 `rule_not_in_task_scope`。 |
| 解压先行/私有 prepare | PASS | 内部解压和分类始终执行；prepare 跟随 owner 是否进入任务快照。 |
| 幂等与可追溯 | PASS | 迁移、关注、恢复、归属写入均使用稳定唯一键、revision/幂等键和追加审计。 |
| 轻量默认/分页 | PASS | 不引入数据量专项架构；工作台列表、目录、审计均分页。 |
| 容错与安全解压 | PASS | 单个证据失败不拖垮页面；既有安全解压边界不变。 |
| 测试与展示效果 | PASS | 设计包含单元、集成、契约、组件、E2E、合成样例和三档桌面视觉验证。 |

**门禁结论**：无未解释的宪法违规，可进入 Phase 0 研究。研究结论见 [research.md](./research.md)。

### 3.2 阶段 1 设计后复查

| 检查项 | 结论 | 设计证据 |
| --- | --- | --- |
| 数据模型是否仍保持隔离和不可变历史 | PASS | 所有 v6 业务键均带 `network_element_type`；任务快照冻结规则版本与 KPI 配置。 |
| 新接口是否破坏 v5 | PASS | v6 新增；v5 不改字段含义，只标 deprecated；前端不保留 v5 fallback。 |
| 是否引入公共规则/公共 KPI | PASS | 无公共归属表或空网元兜底；零归属显式进入 `unassigned`。 |
| 是否仍存在指标级巡检开关 | PASS | v6 配置不含 `enabled` 执行门禁；只保留测量单元 `inspection_enabled`。 |
| 旧任务是否被错误迁移或展示 | PASS | v6 查询旧任务固定 `409 task_result_requires_rebuild`；任务行提供重建。 |
| 是否满足测试和展示双验证 | PASS | 见第 10、11 节及 [quickstart.md](./quickstart.md)。 |

**阶段 1 门禁结论**：PASS。设计自检已完成，进入 Plan Review；用户确认 Review 通过后才进入 tasks。

## 4. Phase 0 研究结论

完整决策、理由与备选方案见 [research.md](./research.md)，本计划采用以下已锁定结论：

- 新工作台、团队关注、测量单元范围和规则归属使用 `/api/v6/...`；v5 冻结。
- v6 KPI 表全部使用复合网元作用域键；旧配置无法唯一判定网元类型时进入待归属，不猜测。
- 团队关注使用差异 PATCH：`expected_revision + add[] + remove[]`，冲突返回 `409 team_focus_revision_conflict`。
- 任务在真正开始执行时冻结规则与 KPI 范围；排队期间允许配置变化。
- 单规则/增量重跑沿用原快照；快照缺规则或版本不一致时明确失败并要求全量重建。
- 日志补充包新增可选单值 `rule_network_element_type`，不写 `product`、不改变 `GENERIC`、不触发台账。
- 旧任务不迁移；v6 查询返回 `409 task_result_requires_rebuild`，复用任务行“重建”。

## 5. 项目结构与真实文件映射

### 5.1 规划产物

```text
specs/041-kpi-result-workbench/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
├── contracts/
│   ├── kpi-workbench.openapi.yaml
│   ├── kpi-team-focus.openapi.yaml
│   ├── kpi-measurement-scope.openapi.yaml
│   ├── rule-network-assignment.openapi.yaml
│   └── task-log-supplement.openapi.yaml
└── assets/
    └── mockups-v2/
```

### 5.2 后端真实文件与计划变更

| 文件 | 计划职责 |
| --- | --- |
| `docs/api/openapi.yaml` | 唯一 API 契约源；实现阶段先合并五份规划契约，新增 v6 路径、Schema、错误码，扩展 v3 表单并标记 v5 deprecated。 |
| `app/api/router.py` | 注册 v6 router；改为调用服务层；不在路由中计算 KPI 分组或规则范围。 |
| `app/api/kpi_v6.py`（新增） | v6 KPI 工作台、团队关注、测量单元范围、规则归属路由。 |
| `app/models/db.py` | 新增 v6 SQLAlchemy 表；保留 v5 表和 `RuleState` 兼容影子。 |
| `app/models/kpi_v6.py`（新增） | v6 请求/响应 Pydantic Schema 与枚举。 |
| `app/services/kpi_v6_migration.py`（新增） | 幂等迁移：仅只读映射可证明唯一归属的 v5 资源、绑定、派生和维护口径；不迁移旧关注或旧启停，写待归属与历史停用恢复审计。 |
| `app/services/kpi_workbench.py`（新增） | 汇总、互斥分组、三视图查询、筛选、证据与技术分析。 |
| `app/services/kpi_team_focus.py`（新增） | 按网元类型的共享关注、revision 原子 PATCH、不可用项保留。 |
| `app/services/kpi_measurement_scope.py`（新增） | 测量单元巡检启停、基础/派生指标计数、单条绑定修正、历史恢复与重试。 |
| `app/services/rule_network_assignments.py`（新增） | 规则归属读写、批量/逐条更新、审计与 revision 冲突。 |
| `app/services/rule_scope.py`（新增） | 统一 `RuleScopeResolver`，冻结规则代码、版本、优先级、注册表指纹与归属 revision。 |
| `app/services/kpi_scope.py`（新增） | 生成 KPI 范围快照，冻结启用单位、指标配置和配置指纹。 |
| `app/services/tasks.py` | 任务开始冻结快照；rerun/rebuild 使用快照；移除 `assert_rule_enabled()` 执行门禁；旧任务 v6 读取走重建错误。 |
| `app/services/task_db.py` | 新增 v6 KPI 结果/点读写；任务级原子发布；所有查询显式携带网元作用域。 |
| `app/cli.py` | 与 API 共用规则和 KPI 范围解析，不再读取全局启用集合作为业务规则门禁。 |
| `app/services/rule_states.py` | 保留为 v2 兼容层，执行器和新服务不读取。 |
| `app/core/registry.py` / 规则注册表 | 提供稳定注册顺序、`rule_version` 和 registry fingerprint；不增加公共范围字段。 |
| `app/services/inventory`、分类、解压模块 | 不需要业务规则归属；只确认日志包不触发台账。 |

### 5.3 前端真实文件与计划变更

| 文件 | 计划职责 |
| --- | --- |
| `web/src/api/client.ts` | 由 OpenAPI 重新生成，禁止手写 v6 请求。 |
| `web/src/api/http.ts` | 仅做生成客户端的薄适配；不得拼出与 OpenAPI 不一致的 v5/v6 路径。 |
| `web/src/App.tsx` | 新增 `/tasks/:taskId/kpi` 结果工作台路由。 |
| `web/src/pages/KpiResultWorkbenchPage.tsx`（新增） | 三视图、顶部汇总、筛选、证据抽屉、团队关注入口、报告/刷新、旧任务重建提示。 |
| `web/src/components/kpi-workbench/KpiSummaryHeader.tsx`（新增） | 数据日期、对比日期、最新测量时间、四个关键计数和互斥分组。 |
| `web/src/components/kpi-workbench/KpiResultViews.tsx`（新增） | 需处理/团队关注/全部指标、搜索筛选、可见数量与空态。 |
| `web/src/components/kpi-workbench/KpiMetricResultsTable.tsx`（新增） | 紧凑结果行、分组顺序、键盘选中、状态文字、昨日趋势。 |
| `web/src/components/kpi-workbench/KpiEvidenceDrawer.tsx`（新增） | 按需证据、加载/失败/重试、阈值/聚合/分母/来源、7 日趋势、技术分析折叠。 |
| `web/src/components/kpi-workbench/TeamFocusDrawer.tsx`（新增） | 唯一关注管理入口、暂存差异、批量加入/移出、revision 冲突处理。 |
| `web/src/pages/MeasurementUnitsPage.tsx` | 删除“关注指标”页签和指标级启用开关；新增测量单元启停、纳入计数、历史恢复/待归属/单条绑定修正。 |
| `web/src/components/MeasurementInspectionPanel.tsx` | 退出维护主入口；保留实际进入任务计划的规则诊断能力，不重复输出 KPI 总览。 |
| `web/src/components/KpiDailyHealthPanel.tsx` | 不再承担任务级维护工作台；仅允许作为证据内部可复用展示片段或删除旧总览用法。 |
| `web/src/components/KpiMetricHealthDetail.tsx` | 证据字段改为 v6 Schema 驱动，不硬编码业务指标名称。 |
| `web/src/pages/InspectorsPage.tsx` | 规则级启停改为网元归属标签、批量/逐条归属、未归属筛选和清空确认。 |
| `web/src/pages/TaskDetailPage.tsx` | 提供进入 KPI 工作台入口；移除重复 KPI 总览；保留任务结论、报告和日志。 |
| `web/src/pages/RuleDetailPage.tsx` | 不再把 KPI 日健康长表作为一级维护界面；仅展示任务范围内的规则执行事实。 |
| `web/src/pages/TaskListPage.tsx` | 增加日志包“规则适用网元类型”三选一、任务行内重建及危险操作确认。 |
| `web/src/hooks/useTaskActions.ts` | 复用全量重建动作；重建成功后刷新任务和 KPI 入口。 |
| `web/src/layouts/MainLayout.tsx` | 基础指标页移出“关注指标”导航入口，仅保留查看团队关注的跳转。 |

### 5.4 测试与样例文件

| 文件 | 计划职责 |
| --- | --- |
| `tests/test_kpi_v6_contract.py`（新增） | v6 OpenAPI/Pydantic/FastAPI 一致性、分页、202+Location、错误结构和 v5 字段冻结。 |
| `tests/test_kpi_v6_fixture.py`（新增） | 20 指标全为 `base`、10 个团队关注、成功率列名归并、固定时间戳与幂等样例。 |
| `tests/test_kpi_v6_migration.py`（新增） | SQLite 幂等迁移、复合键、UMF/CSP 同 ID、待归属、恢复审计和旧启停不迁移。 |
| `tests/test_kpi_workbench_v6.py`（新增） | 汇总对账、三视图、互斥分组、筛选、证据失败和旧任务 409。 |
| `tests/test_kpi_team_focus_v6.py`（新增） | 跨任务共享、类型隔离、不可用保留、revision 冲突和权限。 |
| `tests/test_kpi_measurement_scope_v6.py`（新增） | 测量单元启停、配置保留、恢复部分失败、单条绑定修正。 |
| `tests/test_rule_network_assignments_v6.py`（新增） | 一个或多个归属、零归属、审计、批量、revision 冲突和 v5 影子。 |
| `tests/test_rule_scope.py`、`tests/test_kpi_scope_snapshot.py`（新增） | 任务冻结、排队变更、rerun/增量重跑范围、版本不一致。 |
| `tests/test_task_rebuild_v6.py`（新增） | 旧任务 409、同一 `task_id` 重建、原始包只读和现场缺失边界。 |
| `tests/test_log_supplement_network_scope.py`（新增） | v3 表单字段、冲突顺序、GENERIC、空 product、无台账。 |
| `tests/test_kpi_daily_health.py`、`tests/test_service_boundaries.py` | 成功率 `base` 语义、日健康快照和路由/持久化分层边界。 |
| `web/src/pages/KpiResultWorkbenchPage.test.tsx`（新增） | 三视图、汇总不随筛选变化、空态、切换清理和旧任务重建提示。 |
| `web/src/components/kpi-workbench/*.test.tsx`（新增） | 分组、证据、关注暂存/冲突和视图空态组件。 |
| `web/e2e/kpi-result-workbench.spec.ts`（新增） | 唯一完整 KPI 主路径 E2E，并覆盖规则归属和日志补充包独立场景。 |
| `web/e2e/task-rebuild-v6.spec.ts`（新增） | 旧任务行内重建和原始包只读 E2E。 |
| `web/e2e/measurement-scope-v6.spec.ts`（新增） | 测量单元启停、历史恢复和单条异常修正 E2E。 |
| `tests/fixtures/make_real_package.py` | 追加 20 指标/10 关注、UMF/CSP 同 ID、历史停用、缺配置、revision 冲突和恢复失败边界；固定时间戳、幂等、只增不减。 |

## 6. 架构与分层

### 6.1 分层规则

```text
HTTP / CLI
  → app/api 或 app/cli
    → app/services（业务规则、事务、审计、快照）
      → app/models（SQLAlchemy / Pydantic 契约）
        → SQLite / output 文件
```

- API 层只负责参数、鉴权、状态码、`Location` 和错误映射，不直接查询数据库，不计算分组。
- 服务层负责所有作用域组合键、revision、事务、幂等、审计和旧任务判定。
- 模型层只表达 Schema 与持久化约束；运行时常量来自字典和规则注册表。
- CLI 与 API 必须调用同一 `RuleScopeResolver`、`KpiScopeResolver` 和发布服务。
- 前端只消费生成的 v6 客户端；服务端返回最终分组、排序键和证据，前端不重算判定。

### 6.2 网元类型作用域

- v6 业务表统一使用非空 `network_element_type`；UMF/CSP 即使资源 ID 相同也是不同记录。
- 标准巡检任务的 `network_element_type` 来自 `product`；日志补充包使用独立字段，`product` 保持空。
- 不存在 `"*"`、`"COMMON"`、空字符串或 NULL 表示公共归属。
- 团队关注、测量单元、绑定、派生和维护口径均通过 `(network_element_type, measurement_unit_id, ...)` 读取。
- 日志补充包未选择类型时，规则快照的 `network_element_type` 可为 `NULL`，但此时普通规则集合必须为空。

### 6.3 三视图与判定分组

服务端先计算任务范围内每个指标的最终 `KpiMetricResultV6`，再投影为三个视图：

- `needs_attention`：团队关注中需要处理的指标。
- `team_focus`：团队关注中当前任务可用或不可用的全部项；有结果的正常项也展示。
- `all`：任务 KPI 范围快照中的全部指标，包括未关注、配置不完整、无数据和无法判定项。

`needs_attention_group` 必须唯一，按以下优先级从多信号中选一个：

```text
failure > warning > trend_degraded > unjudgeable > needs_config
```

`not_applicable`、`no_action`、`no_baseline`、`all_zero`、`zero_denominator` 不得计入需处理。每个指标至少保留 `decision` 与 `special_state` 两个维度，确保全零、分母为零、无基线等状态可独立识别。

同组排序键固定为：

```text
group_order ASC, importance_rank ASC, measurement_unit_id ASC, metric_resource_id ASC
```

### 6.4 团队关注共享与并发

- 每个 `network_element_type` 一条 `kpi_team_focus_revisions` 记录；初始 `revision=0`，关注列表为空。
- PATCH 在一个事务中校验 revision、校验加入项属于当前任务可关注范围、去重、应用 add/remove、递增 revision。
- 冲突返回 `409 team_focus_revision_conflict`，`detail.current_revision` 供前端刷新并保留暂存选择。
- 当前任务不存在或所属单位停用的关注项保留在数据库，响应标记 `availability=unavailable`。
- 修改权限沿用 `admin`；所有登录用户可读；无写权限不渲染可提交操作。
- 关注写入只触碰 `kpi_team_focus_items/revisions`，不得更新任务结果、报告或规则快照。

### 6.5 测量单元巡检范围与历史恢复

- `inspection_enabled` 是唯一日常执行门禁。
- 测量单元启用后，所有已确认基础绑定和已定义派生指标进入 KPI 范围；缺少阈值、方向、聚合或基线时仍进入，并在工作台显示待配置/无法判定/无基线。
- 测量单元停用只影响后续任务；绑定、派生、维护配置、团队关注和既有任务结果均保留。
- 历史指标/绑定/派生的 `enabled=false` 在 v6 中不再抑制执行。迁移写入逐对象恢复审计；单位启用状态不由恢复操作隐式改变。
- 恢复和待归属操作支持幂等重试与部分成功；成功项不回滚，失败项保留错误与 attempt count。
- 绑定正常路径自动确认；v6 UI 不提供批量确认，仅保留单条异常诊断/修正。

### 6.6 规则网元归属与任务冻结

- 规则注册表只提供定义、版本和执行元数据；归属来自 `kpi_rule_network_assignments`。
- 规则级全局启停不再读取。`rule_states` 仅作为 deprecated v2 兼容影子。
- 任务启动时执行：
  1. 解析任务网元类型/日志补充包规则适用类型；
  2. 锁定全局归属 revision，读取匹配该类型的规则；
  3. 记录 registry fingerprint；
  4. 写 `task_rule_scope_snapshots` 与 `task_rule_scope_items`；
  5. 写 KPI 范围快照。
- 冻结后归属变化不影响当前任务；后续任务或全量重建读取新 revision。
- 单规则/增量重跑只接受原快照中的规则。规则不存在于快照返回 `rule_not_in_task_scope`；规则版本变化返回 `rule_snapshot_version_mismatch`。
- 未归属和不匹配规则不进入执行计划，不生成 `skip`。
- 隐藏解压/分类技术单元不受归属约束；私有 prepare 只在 owner 位于快照时执行。

### 6.7 任务执行与重建

```text
upload → queue → START FREEZE → EXTRACT → PREPARE(owner in snapshot) → INSPECT(snapshot only)
       → publish rule results/KPI v6/report → completed|failed
```

- 排队期间配置可变化；真正开始执行时一次性冻结。
- 新建成功返回 `202 + Location`；显式重建继续复用 `POST /api/v2/tasks/{task_id}/rebuild`。
- 全量重建保持同一 `task_id`，重新冻结当前规则/KPI 范围并重建输出。
- v6 查询到无 v6 快照的任务固定返回 `409 task_result_requires_rebuild`；前端不渲染旧 KPI 结果兼容层。
- 原始包缺失或现场清理沿用既有 `409 package_missing` / `410 scene_cleaned`，引导上传同名包后重建。

### 6.8 日志补充包独立网元字段

- `POST /api/v3/tasks` 增加可选表单字段 `rule_network_element_type`，仅对 `log_supplement` 生效且最多一个值。
- 冲突判定顺序固定：`checksum → package_kind → product → rule_network_element_type`。
- 巡检包携带该字段返回 `metadata_not_applicable`；非法值返回 `invalid_rule_network_element_type`；同名同包不同选择返回 `package_rule_network_element_type_conflict`。
- 该字段不写 `customer.product`，不改变分类 profile `GENERIC`，不触发台账解析或归档。
- 未选择时普通规则集合为空，页面明确显示“未选择规则适用网元类型”，不能显示为全部通过。

## 7. SQLite 建表与幂等迁移顺序

`init_db()` 的实现顺序固定为：

1. 创建 WAL 引擎。
2. 仅当旧 `tasks.system_id` 或旧台账约束存在时执行既有 legacy rebuild。
3. `Base.metadata.create_all()`：创建所有 v6 表与索引，已有 v5 表不重建。
4. 执行既有增量列与 KPI 约束检查。
5. 为 `tasks` 增加 nullable `rule_network_element_type`（若不存在）。
6. 在单一事务中执行 `migrate_kpi_v6()`：
   - 初始化规则归属全局 revision 和各网元类型团队关注 revision；
   - 按可证明唯一网元类型复制 v5 配置到 v6；
   - 无法唯一归属的记录写 `kpi_pending_attributions`；
   - 为历史 `enabled=false` 对象写 `kpi_legacy_recovery_audits`；
   - 不删除、不重写 v5 数据，不把旧 `enabled` 转成团队关注。
7. 执行既有 `ensure_backfilled()`。
8. 所有写入使用稳定幂等键、`INSERT ... ON CONFLICT DO NOTHING` 或唯一约束；启动重跑不得产生重复关注、归属、审计或快照。

迁移失败策略：单条 v5 配置无法归属或恢复时记录待归属/失败审计并继续；建表或约束失败属于启动错误，必须显式暴露，不得静默跳过。

## 8. API 契约设计

实现阶段以 [docs/api/openapi.yaml](../../docs/api/openapi.yaml) 为唯一事实源，先合并以下规划契约：

| 契约 | 范围 | 关键接口 |
| --- | --- | --- |
| [kpi-workbench.openapi.yaml](./contracts/kpi-workbench.openapi.yaml) | 任务级汇总、三视图、证据、7 日与技术分析 | `GET /api/v6/kpi/tasks/{task_id}/summary`、`.../metrics`、`.../evidence`、`.../technical-analysis` |
| [kpi-team-focus.openapi.yaml](./contracts/kpi-team-focus.openapi.yaml) | 按网元类型共享关注 | `GET/PATCH /api/v6/kpi/team-focus/{network_element_type}` |
| [kpi-measurement-scope.openapi.yaml](./contracts/kpi-measurement-scope.openapi.yaml) | 测量单元启停、恢复、待归属、单条绑定修正 | `/api/v6/kpi/measurement-units/...`、`/api/v6/kpi/pending-attributions/...` |
| [rule-network-assignment.openapi.yaml](./contracts/rule-network-assignment.openapi.yaml) | 规则目录、逐条/批量归属、审计 | `/api/v6/kpi/rule-network-assignments/...` |
| [task-log-supplement.openapi.yaml](./contracts/task-log-supplement.openapi.yaml) | 日志补充包可选规则适用网元类型 | `POST /api/v3/tasks` 增量字段与稳定错误码 |

统一约束：

- 所有错误为 `{code, message, detail}`；`detail` 可为对象。
- 列表均使用 `page` / `page_size` 并返回 `total`。
- 启动恢复、重试类接口返回 `202 + Location`。
- 所有新工作台、关注、测量范围、规则归属接口均位于 `/api/v6/kpi/...`。
- 既有 v5 `batch-confirm` 与 v2 `inspector-states` 仅标 `deprecated`，新前端不调用。
- 旧任务 v6 查询固定 `409 task_result_requires_rebuild`。
- `PATCH` 配置接口使用 `expected_revision`；冲突返回稳定错误码和当前 revision。
- 合并五份规划契约前必须先处理全局组件命名冲突，不得按文件覆盖同名定义：

| 同名组件 | 合并策略 |
| --- | --- |
| `Error`、`HTTPValidationError`、`ValidationError`、`Page`、`PageSize`、`TaskNotFound`、`TaskResultRequiresRebuild` | 合并为共用定义，并汇总各领域示例。 |
| `NetworkElementTypeQueryOptional` | 合并为一个共用查询参数，保留禁止公共范围、`*`、`COMMON` 和空值的完整约束。 |
| `WriteForbidden` | 按领域重命名为 `KpiTeamFocusWriteForbidden`、`KpiMeasurementScopeWriteForbidden`、`KpiRuleAssignmentWriteForbidden`。 |
| `Location` | 按用途重命名为 `KpiMaintenanceLocation`、`KpiRebuildLocation`、`TaskCreateLocation`。 |
| `TaskCreated` | 按接口重命名为 `KpiRebuildAcceptedV2`、`TaskCreatedV3`。 |

## 9. 前端交互设计

### 9.1 结果工作台

- 默认视图 `needs_attention`；顶部汇总始终来自全局 summary，不随视图筛选变化。
- 三视图 tabs 显示各自总数；视图内筛选显示 `当前可见 x / 总计 y`。
- 表格列：状态/分组、测量单元、指标、今日值、昨日趋势、原因、重要度；每行只有一个证据入口。
- 选择行高亮并打开证据抽屉：1440px 及以上保留列表可见，1280px 使用覆盖层。
- 证据失败在抽屉内显示错误与重试，不改变表格汇总。
- 顶部“刷新当前结果”只重新请求当前任务 v6 数据；“查看任务报告”复用既有报告路由。
- 页面无健康分、风险排序、旧 KPI 总览或独立单任务趋势入口。

### 9.2 团队关注

- `TeamFocusDrawer` 是唯一编辑入口；基础指标页只允许跳转查看。
- 支持搜索、测量单元筛选、全选当前结果、批量加入/移出、取消修改和保存。
- 本地暂存差异；关闭 dirty 抽屉弹出“放弃/继续编辑”。
- 保存遇到 revision 冲突时保留本地暂存，展示 `current_revision`，刷新后由用户确认重试。
- 写权限不足时只读并隐藏保存按钮。

### 9.3 测量单元范围与规则归属

- 测量单元页移除“关注指标”tab、指标级启停与批量确认。
- 每个单位展示状态、基础指标数、派生指标数、历史恢复提示；启停前提示“只影响后续巡检”。
- 待归属记录展示原因、候选和重试状态，未指定网元类型前不得进入任务。
- 规则页显示归属标签或“未归属”；支持逐条和批量设置，一个规则可多选网元类型。
- 清空最后一个归属必须二次确认；页首明确“无公共规则、未归属不执行”。

### 9.4 任务创建与重建

- 日志补充包表单显示 UMF/CSP/不指定单选项；巡检包不显示该字段。
- 上传前检查包类型；未指定日志包展示明确说明。
- 任务列表行内“重建”打开危险操作确认，文案包含删除并重建输出、不可撤销、原始包只读。
- 原始包缺失时引导同名包上传；重建成功后跳转/刷新新 KPI 工作台。
- 旧任务 KPI 入口收到 409 时展示重建动作，不渲染降级面板。

## 10. 测试策略

### 10.1 测试分层

- **单元测试**：作用域键、需处理分组优先级、稳定排序、revision 冲突、恢复状态机、规则快照解析、不可用关注项。
- **集成测试**：SQLite 幂等迁移、UMF/CSP 同 ID、任务开始冻结、排队变更、单规则/增量重跑、日志包冲突矩阵、v5 冻结。
- **契约测试**：五份规划契约并入实际 OpenAPI 后，校验路径、Schema、错误结构、分页、202+Location 和 deprecated 标记。
- **前端组件测试**：三视图、汇总对账、筛选可见数、证据加载/失败、关注 dirty/冲突、测量单位启停、规则归属、重建确认。
- **E2E**：保留一个完整 KPI 主路径“打开任务 → 需处理 → 证据 → 关注加入/移出 → 全部指标”；规则归属和日志补充包各一个独立场景，不重复主路径断言。
- **展示效果**：扩充合成包生成器，确保结果在真实页面和 API 中可见；固定时间戳并保持幂等。

### 10.2 TDD 顺序

每组实现按以下顺序执行：先写失败测试 → 运行并确认失败原因 → 最小实现 → 运行通过 → 重构 → 运行受影响测试。不得先写实现后补断言。需要调试时先使用 systematic-debugging，不在未定位根因前改代码。

### 10.3 验收命令

```bash
python build.py lint
python build.py test
python build.py verify
python build.py contract
python build.py gen-web-api
python build.py web-build
python build.py e2e
```

## 11. 合成样例与视觉验收

`tests/fixtures/make_real_package.py` 追加以下固定合成场景：

- 20 个真实呼叫 KPI 指标身份，其中 10 个纳入团队关注，至少 5 个需处理项，覆盖五类互斥分组；
- UMF 与 CSP 使用相同 `measurement_unit_id` 和 `metric_resource_id`；
- 历史指标/绑定/派生 `enabled=false`，其中至少一条恢复失败；
- 缺阈值、缺方向、无基线、无数据、全零、分母为零；
- 规则归属 UMF、归属 CSP、多归属、未归属；
- 日志补充包选择 UMF、选择 CSP、未选择三种；
- 团队关注 revision 冲突与证据加载失败的可重试边界。

### 11.1 真实呼叫 KPI 验收集

全部指标为以下 20 个唯一业务指标；团队关注只取媒体资源创建、修改、删除共 10 项。音视频终止资源更新、音视频流关联设置和数据通道资源更新保留在“全部指标”，不进入团队关注。原始包中的成功率存在两个源列名变体，但每个成功率都是源包直接提供的 `base` 指标，不得把别名拆成两个指标，也不得在 PatrolX 内另建派生指标。

| 分组 | 源指标列名（`role=base`） | 团队关注 |
| --- | --- | --- |
| 媒体资源创建 | `Number of Media Resource Creation Requests(times)`；`Number of Success Responses to Media Resource Creation Requests(times)`；`Number of Failure Responses to Media Resource Creation Requests(times)`；`Media Resource Creation Success Rate(%)` 或 `Media Resource Creation Requests Success Rate(%)` | 是 |
| 媒体资源修改 | `Number of Media Resource Modification Requests(times)`；`Number of Success Responses to Media Resource Modification Requests(times)`；`Number of Failure Responses to Media Resource Modification Requests(times)` | 是 |
| 媒体资源删除 | `Number of Media Resource Deletion Requests(times)`；`Number of Success Responses to Media Resource Deletion Requests(times)`；`Number of Failure Responses to Media Resource Deletion Requests(times)` | 是 |
| 音视频终止资源更新 | `Number of Audio/Video Termination Resource Update Requests(times)`；`Number of Success Responses to Audio/Video Termination Resource Update Requests(times)`；`Number of Failure Responses to Audio/Video Termination Resource Update Requests(times)` | 否，仅全部指标 |
| 音视频流关联设置 | `Number of Requests for Setting Associations Between Audio and Video Stream Resources(times)`；`Number of Success Responses to Requests for Setting Associations Between Audio and Video Stream Resources(times)`；`Number of Failure Responses to Requests for Setting Associations Between Audio and Video Stream Resources(times)` | 否，仅全部指标 |
| 数据通道资源更新 | `Number of Data Channel Resource Update Requests(times)`；`Number of Success Responses to Data Channel Resource Update Requests(times)`；`Number of Failure Responses to Data Channel Resource Update Requests(times)`；`DC Resource Update Success Rate(%)` 或 `Data Channel Resource Update Requests Success Rate(%)` | 否，仅全部指标 |

全部 20 个指标均按源包直接提供的 `base` 指标读取；团队关注 10 个，也全部是 `base` 指标。成功率不根据请求数、成功响应数重算或回填，源值为空时按缺失处理；相邻请求数、成功响应数和失败响应数只作为判读证据。真实包只提供指标身份，验收中的失败、预警、趋势恶化、无法判定和待配置状态使用明确标注的受控合成数据。

视觉验收使用 Chrome：

1. 打开 `assets/mockups-v2/review-v2.html` 及五张已确认 PNG；
2. 实际页面分别在 1280×900、1440×900、1920×1080 验证；
3. 1280px 无页面级横向滚动；
4. 1440×900 首屏可见汇总、分组和至少 5 个需处理指标；
5. 状态不只依赖颜色，键盘可操作关注和证据。

## 12. 实施工作流与顺序

| ID | 工作流 | 主要交付 |
| --- | --- | --- |
| W0 | 契约先行 | OpenAPI v6、deprecated 标记、v3 字段、Pydantic/FastAPI/生成客户端一致性 |
| W1 | 数据模型与迁移 | v6 表、复合键、幂等迁移、待归属、恢复审计 |
| W2 | 范围冻结与重建 | `RuleScopeResolver`、KPI 快照、rerun/rebuild、旧任务 409 |
| W3 | 工作台后端 | summary、三视图、互斥分组、证据、技术分析 |
| W4 | 团队关注 | revision、共享、不可用项、权限、原子 PATCH |
| W5 | 测量范围 | 测量单元启停、基础/派生计数、单条绑定修正、恢复/重试 |
| W6 | 规则归属 | 规则目录、逐条/批量归属、审计、未归属 |
| W7 | 日志补充包 | v3 字段、冲突矩阵、GENERIC 与台账隔离 |
| W8 | 结果工作台前端 | 三视图、证据抽屉、汇总、空态与失败重试 |
| W9 | 关注与范围前端 | TeamFocusDrawer、测量单元范围、恢复/待归属 |
| W10 | 规则/上传/重建前端 | 归属配置、日志包单选、任务行重建 |
| W11 | 旧能力退出 | 移除旧 KPI 总览、关注 tab、指标级开关、批量确认入口；v5 deprecated |
| W12 | 验证与展示 | 单测、集成、契约、组件、E2E、合成样例、Chrome 三档视觉 |

每个 W 在 tasks 阶段拆成可独立验证的任务；本文件不维护第二份任务清单。

## 13. 风险与处置

| 风险 | 处置 |
| --- | --- |
| v5 冻结与“退出批量确认”冲突 | 新 UI/v6 不提供该能力；v5 接口仅 deprecated，物理删除另立下线功能。 |
| 升级后全部规则未归属导致无业务规则执行 | 这是 FR-044 的明确语义；规则页展示未归属，任务页提示“未配置可执行业务规则”，不伪造通过。 |
| v5 配置无法证明网元类型 | 进入待归属，不默认 UMF/CSP；完成指定前不进入巡检范围。 |
| SQLite 旧唯一键不含网元类型 | 新建 v6 表，不原地修改 v5 主键；所有新唯一约束包含 `network_element_type`。 |
| 任务排队期间配置变化 | 真正开始执行时冻结；快照记录 revision、版本和注册表指纹。 |
| 规则代码版本变化 | 快照版本不一致直接失败并提示全量重建，不静默换版本。 |
| 关注并发覆盖 | 差异 PATCH + revision；冲突保留本地暂存。 |
| 恢复部分失败 | 逐对象审计、成功项保留、失败项可重试，不声称整体完成。 |
| 20 指标首屏拥挤 | 紧凑表格、短列名、稳定分组；页面无横向滚动，长文本省略并以证据展示。 |
| 旧任务误显示 | v6 固定 409；任务行重建是唯一升级路径。 |
| 旧任务结果被配置变更污染 | KPI 点和指标结果同时写入任务快照；查询不实时读取当前阈值/启用状态。 |

## 14. 需求覆盖映射

### 14.1 FR-001～FR-044

| 需求 | 工作流 | 覆盖方式 |
| --- | --- | --- |
| FR-001 | W3, W8 | 三视图由汇总/列表查询的 view 参数严格分离；需处理由关注交集判定派生。 |
| FR-002 | W1, W4, W8 | 关注复合唯一键、跨任务共享、类型隔离、权限和空初始状态。 |
| FR-003 | W3, W8 | summary 返回日期、时间、四个计数、互斥分组。 |
| FR-004 | W3, W8 | 服务端唯一 `needs_attention_group` 与固定优先级。 |
| FR-005 | W3, W8 | needs_attention 查询固定 group/importance/稳定键排序。 |
| FR-006 | W3, W8 | team_focus 返回关注项当前任务全部可用结果与正常项。 |
| FR-007 | W3, W8 | all 视图读取任务 KPI 范围快照，不受关注过滤。 |
| FR-008 | W4, W8 | 唯一 TeamFocusDrawer；搜索、单位筛选、批量增删、取消、保存。 |
| FR-009 | W4, W8 | 前端暂存 dirty 状态；关闭时放弃/继续编辑确认。 |
| FR-010 | W1, W4, W3 | 关注写表不触碰任务结果、报告、快照或启停。 |
| FR-011 | W4 | 关注按类型持久化；不可用项保留并标记原因。 |
| FR-012 | W3, W8 | 四类搜索字段、测量单元/判定/昨日趋势筛选。 |
| FR-013 | W3, W8 | 返回 visible/total；一键清除；区分无匹配、无指标、关注空。 |
| FR-014 | W8 | 行选中、证据抽屉、宽屏同映/窄屏覆盖、关闭恢复上下文。 |
| FR-015 | W3, W8 | Evidence Schema 覆盖判定、趋势、阈值、聚合、点数、分组、分子分母、来源。 |
| FR-016 | W1, W3, W8 | 证据由配置和契约字段驱动；成功率按源包 `base` 指标读取，同名变体归并，源值缺失不重算。 |
| FR-017 | W3, W8 | 证据按需 GET；loading/error/retry 局部状态。 |
| FR-018 | W8, W11 | 删除健康分、风险排序、旧 KPI 总览/长表；证据只保留次级技术信息。 |
| FR-019 | W3, W8 | 顶部报告链接复用既有接口；刷新只重读 v6 结果。 |
| FR-020 | W2, W10 | 旧任务 409 + 行内二次确认重建、同 task_id、包缺失引导。 |
| FR-021 | W8 | 状态文字标签、键盘焦点与操作；不只靠颜色。 |
| FR-022 | W8, W12 | 三档桌面宽度、无页面横向滚动、E2E 固定视口。 |
| FR-023 | W8, W12 | 切换任务或重载时清空选择、筛选、未保存关注和证据；按网元类型重载关注配置并验证无残留。 |
| FR-024 | W9, W11 | 删除基础指标“关注指标”tab；只保留查看共享关注跳转。 |
| FR-025 | W1, W5, W9 | v6 配置无指标级执行门禁；仅 measurement unit `inspection_enabled`。 |
| FR-026 | W5, W9 | 启用单位纳入全部已确认基础指标和已定义派生指标。 |
| FR-027 | W3, W5 | 缺配置指标保留在 all，显示 needs_config/unjudgeable/no_baseline。 |
| FR-028 | W1, W5 | 历史 enabled=false 不再抑制；逐对象恢复审计、可重试、部分失败。 |
| FR-029 | W5, W9 | 停用只影响后续任务，配置与关注保留，重启按单位规则恢复。 |
| FR-030 | W5, W9 | 单位页展示启停、基础/派生计数和“只影响后续巡检”提示。 |
| FR-031 | W5, W9, W11 | 自动确认正常绑定；删除批量确认 UI；保留诊断和单条修正。 |
| FR-032 | W3, W8 | 结果行昨日趋势、证据 7 日趋势；无独立单任务趋势页。 |
| FR-033 | W3, W8 | 跨任务历史/版本对比放入次级 technical-analysis，按需加载。 |
| FR-034 | W0, W11 | v6 全量新契约；v5 字段冻结、不 fallback、不双写。 |
| FR-035 | W1, W4, W5 | 所有查询和写入校验复合网元类型；同名 ID 不串域。 |
| FR-036 | W6, W10 | 规则实现不声明归属；运行时共享配置管理，无公共范围。 |
| FR-037 | W6, W10 | 规则页展示全部规则、归属标签、未归属和多选编辑。 |
| FR-038 | W2, W6 | 执行计划只含当前类型命中规则；未归属/不匹配不执行、不生成 skip；无全局启停。 |
| FR-039 | W7, W10 | 日志补充包单个可选 rule_network_element_type；不写 product、不改 GENERIC/台账。 |
| FR-040 | W7, W10 | 未选类型时内部单元可执行、普通规则为空并明确说明。 |
| FR-041 | W2, W6 | 归属写审计、只影响后续冻结、执行中不变、历史不改写。 |
| FR-042 | W2, W6 | 隐藏解压/分类不归属；prepare 仅 owner 命中快照时执行。 |
| FR-043 | W6, W10 | 规则目录按类型/未归属筛选；任务结果只显示快照内规则。 |
| FR-044 | W1, W6, W10 | 升级初始未归属，不把 RuleState/disabled_rules 转换为归属。 |

### 14.2 SC-001～SC-024

| 成功标准 | 工作流 | 验证方式 |
| --- | --- | --- |
| SC-001 | W8, W12 | 1440×900、20 个指标且 10 个团队关注的合成任务首屏快照断言。 |
| SC-002 | W8 | 行到证据 1 次点击；1440+ 抽屉与表格同屏。 |
| SC-003 | W3, W8 | 需处理+无需处理=团队关注，全部指标独立；summary 不随筛选变。 |
| SC-004 | W8, W12 | 1280/1440/1920 无页面级横向溢出。 |
| SC-005 | W3, W8, W12 | 各特殊状态 fixture 与独立标签断言。 |
| SC-006 | W4, W8 | 打开→批量选择→保存不超过 3 个明确动作；dirty 关闭确认。 |
| SC-007 | W3, W4, W12 | 关注前后结果/报告不变；移出后切换 all 一次可找到。 |
| SC-008 | W8, W12 | 证据和关注失败均显示原因与重试/刷新动作。 |
| SC-009 | W5, W12 | 启停单位改变后续范围；关注/绑定确认/派生编辑不排除指标。 |
| SC-010 | W1, W5, W12 | 历史停用恢复后指标全部纳入；审计逐项；旧结果校验不变。 |
| SC-011 | W9 | 1280/1440 无关注 tab、无指标级开关；三个入口首屏可识别。 |
| SC-012 | W2, W10, W12 | 旧任务行重建确认、同 task_id、完成后 v6 展示。 |
| SC-013 | W8, W11 | DOM/文本断言无健康分、风险排序、旧总览。 |
| SC-014 | W9, W11 | 无批量确认入口；单条异常修正有反馈。 |
| SC-015 | W3, W8 | 无独立趋势入口；昨日/7日/跨任务/版本均在证据可追溯。 |
| SC-016 | W1, W4, W12 | 升级后各类型关注为空；旧 enabled 不生成关注。 |
| SC-017 | W0, W12 | 抓取请求均命中 v6；契约回归 v5 字段不变。 |
| SC-018 | W1, W4, W12 | UMF/CSP 同 ID 双类型隔离测试。 |
| SC-019 | W2, W6, W12 | 无公共选项；未归属不进入任何执行计划。 |
| SC-020 | W2, W6, W12 | UMF/CSP/未归属规则分别执行，任务只含命中结果且无伪造 skip。 |
| SC-021 | W7, W12 | 日志包选类型仅匹配该类型；product 空、GENERIC、无台账；未选空规则。 |
| SC-022 | W2, W6, W12 | 执行中修改归属，当前快照不变；后续使用新 revision 且审计可查。 |
| SC-023 | W6, W12 | 清空最后归属后停止；改配后来源不执行、目标后续执行。 |
| SC-024 | W1, W3, W12 | 20 个指标均为 `base`；成功率列名变体归并；空源值保持缺失且不重算。 |

## 15. 验收门槛与 Plan Review 边界

### 15.1 Plan 自检结果

- [x] 本计划无占位符、无 `NEEDS CLARIFICATION`；`FR-001～FR-044` 与 `SC-001～SC-024` 全部映射且无重复；
- [x] `data-model.md` 的复合作用域、revision、批量事务、审计和不可变历史约束与服务层设计一致；
- [x] 五份契约均为可解析的 OpenAPI 3.1 草案，路径参数、operationId、响应和本地 `$ref` 校验通过；
- [x] v5 `batch-confirm` 与 v2 `inspector-states*` 均明确标记 `deprecated`，新前端和 v6 不调用；
- [x] `quickstart.md` 覆盖结果工作台、团队关注、测量范围、规则归属、日志补充包、重建和失败边界；
- [x] 五张 v2 效果图的整体界面结构已写入设计参照；成功率证据已修订为源包直出且不展示重算公式，当前版本已由用户确认；
- [x] Plan 目录内 Markdown 链接与 HTML 资源引用均无缺失。

自检结论：**结构自检通过；效果图确认门禁已通过，待 analyze/review 后进入实施。**

### 15.2 Plan Review 边界

Plan Review 通过后才进入：

```text
tasks → analyze → review
→ 提交 Speckit 产物到 main
→ 创建实现分支/worktree → implement
```

本文件不生成 `tasks.md`，不创建实现分支，不修改业务代码、OpenAPI、Schema、测试、迁移或数据模型。
