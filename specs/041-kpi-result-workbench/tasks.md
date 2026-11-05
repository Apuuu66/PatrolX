---
description: "KPI 巡检结果判读工作台实现任务列表"
---

# 任务：KPI 巡检结果判读工作台

**输入**：来自 `/specs/041-kpi-result-workbench/` 的规划设计文档

**前置条件**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`，且 v2 效果图已经用户确认

**测试**：项目宪法要求自动化测试和展示效果；以下任务严格按 TDD 执行，先写失败测试并确认失败原因，再实现最小代码。

**组织方式**：任务按六个用户故事分组，故事完成顺序为 P1 → P6；每个故事完成后必须独立验证，再进入下一优先级。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：用户故事阶段必填，阶段 1、2、收尾不填
- 每条描述包含精确文件路径

## 路径约定

- 后端：`app/api/`、`app/models/`、`app/services/`、`app/inspectors/`
- 前端：`web/src/`、`web/e2e/`
- 契约：`docs/api/openapi.yaml`
- 测试：`tests/`、`web/src/**/*.test.ts(x)`、`web/e2e/`

---

## 阶段 1：设置（共享基础设施）

**目的**：先固化 v6 契约、生成客户端和代表性合成样例，防止实现漂移。

- [ ] T001 [P] 在 `tests/test_kpi_v6_contract.py` 编写失败契约测试，覆盖五份规划契约中的 v6 路径、统一错误结构 `{code,message,detail}`、分页 `page/page_size/total`、`202 + Location`、团队关注 PATCH 的 `task_result_requires_rebuild` 与 `team_focus_revision_conflict` 两种 409、v5 冻结字段和 v5/v2 旧入口 `deprecated` 标记（FR-034、SC-017）
- [ ] T002 将 `specs/041-kpi-result-workbench/contracts/` 合并进 `docs/api/openapi.yaml`，先按 [plan.md](./plan.md) 第 8 节完成共用组件归一和领域化重命名，禁止同名覆盖；再新增 `/api/v6/kpi/...` paths、v6 Schemas、稳定错误码、`POST /api/v3/tasks` 的 `rule_network_element_type` 单值表单字段，并给 v5 batch-confirm 与 v2 inspector-states 标记 `deprecated`（FR-034、FR-039、SC-017、SC-021）
- [ ] T003 运行 `.venv/bin/python build.py contract` 与 `.venv/bin/python build.py gen-web-api`，校验 `docs/api/openapi.yaml` 可导出且 `web/src/api/client.ts` 仅由生成器更新（FR-034、SC-017）
- [ ] T004 [P] 在 `tests/test_kpi_v6_fixture.py` 编写失败样例测试，断言固定时间戳与幂等生成、20 个指标均为 `role=base`、媒体资源创建/修改/删除共 10 个关注项、两个成功率源列名变体各归并为单一指标且保留映射证据（SC-024）
- [ ] T005 扩展 `tests/fixtures/make_real_package.py`，追加 20 个真实呼叫 KPI 身份、10 个团队关注、UMF/CSP 同 ID、五类需处理状态、历史停用恢复、规则归属和日志包变体；固定时间戳且既有样例只增不减（FR-016、SC-024）
- [ ] T006 [P] 在 `tests/conftest.py` 增加 v6 合成数据库与任务快照夹具，确保 UMF/CSP、20 指标/10 关注、证据失败和 revision 冲突可直接复用于服务与 API 测试

**检查点**：v6 契约、生成客户端和代表性样例已就绪；后续实现不得手写绕过生成契约的请求。

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：建立所有用户故事共用的 v6 持久化、Schema、迁移、任务镜像和路由骨架。

**⚠️ 关键**：本阶段完成前不得开始用户故事实现。

- [ ] T007 [P] 在 `tests/test_kpi_v6_migration.py` 编写失败测试，覆盖 SQLite 幂等建表、复合唯一键、v5 可唯一归属配置的只读映射、无法唯一归属进入待归属、历史 `enabled=false` 写入恢复审计且不转成团队关注或执行开关（FR-002、FR-028、SC-016）
- [ ] T008 在 `app/models/db.py` 新增 `data-model.md` 4.1～4.19 的 v6 表与索引；所有配置类业务表必须使用非空 `network_element_type`，任务快照与审计表仅在 `data-model.md` 明示的空场景允许 NULL；任何表都禁止用 `"*"`、`"COMMON"`、空字符串或 NULL 表示公共范围，并保留 v5 表只读共存
- [ ] T009 [P] 在 `app/models/kpi_v6.py` 按 `docs/api/openapi.yaml` 实现 v6 Pydantic 枚举、请求和响应 Schema，覆盖 `expected_revision`、分页、证据、恢复、待归属、规则归属和任务范围快照
- [ ] T010 在 `app/services/kpi_v6_migration.py` 实现幂等迁移：仅复制可证明唯一归属的 v5 资源、绑定、派生和维护口径，初始化团队关注 revision，写待归属与历史停用恢复审计；不复制旧团队关注、不把旧 `enabled` 转为关注或执行门禁，不删除或改写 v5 数据（FR-002、FR-028、FR-035、SC-016）
- [ ] T011 在 `app/models/db.py::init_db()` 接入 `migrate_kpi_v6()`，按“建表 → 增量列 → tasks 增加 nullable `rule_network_element_type` → v6 迁移 → 既有回填”顺序执行并保持单条失败隔离
- [ ] T012 在 `app/services/task_db.py` 实现 v6 任务 KPI 结果/点、规则快照和 KPI 快照的基础读写与原子发布接口，所有查询显式携带网元作用域和 `task_id`
- [ ] T013 在 `app/api/kpi_v6.py` 创建 v6 APIRouter 骨架，并在 `app/api/router.py` 注册；路由层只做参数、鉴权、状态码和错误映射，不直接查询数据库或计算分组
- [ ] T014 在 `tests/test_service_boundaries.py` 增加失败断言，禁止 `app/api/kpi_v6.py` 直接导入 `Session`、`app.models.db` 或实现 KPI 分组计算
- [ ] T015 在 `tests/test_kpi_v6_migration.py` 补齐迁移重跑、部分失败继续、幂等键和启动顺序测试，确认启动重跑不产生重复关注、归属、审计或快照（FR-028、SC-016）

**检查点**：v6 表、Schema、迁移、任务镜像和路由骨架完成，所有用户故事可在同一基础上独立开发。

---

## 阶段 3：用户故事 1 - 首屏判断今天哪些团队关注指标需要处理（优先级：P1）🎯 MVP

**目标**：打开任务即看到全局汇总与互斥“需处理”分组，首屏无需打开证据即可判断处理重点。

**独立测试**：20 指标/10 关注的合成任务在 1440×900 首屏显示数据日期、对比日期、最新测量时间、启用单位数、全部/关注/需处理计数、五类互斥分组和至少 5 条需处理指标；筛选不改变顶部汇总。

### 用户故事 1 的测试

- [ ] T016 [P] [US1] 在 `tests/test_kpi_workbench_v6.py` 编写 summary/list 失败测试，覆盖默认 `needs_attention`、五类分组优先级 `failure > warning > trend_degraded > unjudgeable > needs_config`、稳定排序和汇总/视图计数对账（FR-001、FR-003、FR-004、FR-005、SC-001、SC-003、SC-005）
- [ ] T017 [P] [US1] 在 `web/src/components/kpi-workbench/KpiSummaryHeader.test.tsx` 编写失败组件测试，验证汇总只读全局 summary、分组不随筛选变化、状态同时有文字与颜色且键盘可访问（FR-003、FR-004、FR-021、SC-003）
- [ ] T018 [P] [US1] 在 `web/src/pages/KpiResultWorkbenchPage.test.tsx` 编写失败页面测试，验证默认视图、空态、加载失败、刷新只重读结果以及“查看任务报告”入口（FR-003、FR-005、FR-019、SC-008）
### 用户故事 1 的实现

- [ ] T019 [US1] 在 `app/services/kpi_workbench.py` 实现任务 summary、默认需处理查询、互斥分组、重要度排序和稳定排序键，所有结果由服务端一次判定生成（FR-001、FR-003、FR-004、FR-005、SC-001、SC-003、SC-005）
- [ ] T020 [US1] 在 `app/api/kpi_v6.py` 实现 `GET /api/v6/kpi/tasks/{task_id}/summary` 与 `GET /api/v6/kpi/tasks/{task_id}/metrics` 的默认视图参数和 v6 响应映射（FR-003、FR-005）
- [ ] T021 [US1] 在 `web/src/components/kpi-workbench/KpiSummaryHeader.tsx` 实现数据日期、对比日期、最新测量时间、四个关键计数和五类互斥分组（FR-003、FR-004、FR-021、SC-001、SC-003）
- [ ] T022 [US1] 在 `web/src/components/kpi-workbench/KpiMetricResultsTable.tsx` 实现紧凑结果行、状态文字、今日值、昨日趋势、原因、重要度和单一证据入口
- [ ] T023 [US1] 在 `web/src/pages/KpiResultWorkbenchPage.tsx` 组装 summary、默认需处理表、刷新、报告和加载/空态，并在 `web/src/App.tsx` 注册 `/tasks/:taskId/kpi`；任务切换时清除上一任务选择、筛选和证据（FR-019、FR-023、FR-032）
**检查点**：US1 可独立演示；1440×900 首屏满足汇总、分组和至少 5 条需处理数据。

---

## 阶段 4：用户故事 2 - 在当前列表上下文中核验指标证据（优先级：P2）

**目标**：任一结果行最多一次点击打开对应证据；证据失败可局部重试，关闭后保留原视图、筛选、排序和列表位置。

**独立测试**：从需处理视图打开失败、数据不足和趋势恶化指标，验证证据身份一致、上下文不丢、宽屏列表保留、窄屏覆盖展示，并验证派生指标公式与源包成功率 `base` 语义。

### 用户故事 2 的测试

- [ ] T024 [P] [US2] 在 `tests/test_kpi_daily_health.py` 编写成功率口径失败测试，覆盖两个源列名变体归并、源值空值缺失、无数据/分母为零/无基线独立状态，以及只有派生指标展示公式、源包成功率不按请求/响应数重算（FR-016、SC-005、SC-024）
- [ ] T025 [P] [US2] 在 `tests/test_kpi_workbench_v6.py` 增加证据失败测试，覆盖今日/昨日、变化、原因、有效点、阈值来源、方向、聚合、7 日趋势、对象/周期、仅派生指标的分子分母、来源文件和缺失原因，并覆盖跨任务历史趋势与同设备版本对比按需加载、网元作用域隔离和空历史边界（FR-014～FR-017、FR-032、FR-033、SC-002、SC-008、SC-015）
- [ ] T027 [P] [US2] 在 `web/src/components/kpi-workbench/KpiEvidenceDrawer.test.tsx` 编写失败组件测试，覆盖加载中、失败重试、关闭恢复上下文、技术分析折叠、键盘访问，以及源包成功率不显示公式、派生指标显示公式（FR-014～FR-017、FR-032、SC-002、SC-008、SC-015、SC-024）
- [ ] T028 [P] [US2] 在 `web/src/pages/KpiResultWorkbenchPage.test.tsx` 增加失败集成测试，验证选中行高亮、1440px 列表保留、1280px 覆盖层展示、切换指标只请求对应证据和键盘操作（FR-014、FR-021、FR-022、SC-002、SC-004）

### 用户故事 2 的实现

- [ ] T026 [US2] 在 `app/services/kpi_daily_health_snapshot.py` 与 `app/services/kpi_measurement_units.py` 实现并满足 T024：成功率源字段按 `base` 指标入库、源值空值保持缺失、同一指标多个源列名归并且证据保留 `raw_source_names`，禁止从请求数/成功数重算或回填（FR-016、SC-005、SC-024）
- [ ] T029 [US2] 在 `app/services/kpi_workbench.py` 实现按测量单元与指标 ID 获取证据、证据缺失原因和单指标失败隔离，不把分钟级结果均值当作日结果（FR-015～FR-017）
- [ ] T030 [US2] 在 `app/services/kpi_workbench.py` 实现跨任务历史趋势与同设备版本对比的按需技术分析查询，默认不进入首屏（FR-033、SC-015）
- [ ] T031 [US2] 在 `app/api/kpi_v6.py` 实现 evidence 与 technical-analysis 两个 GET 接口，并把不存在、证据不可读和旧任务错误映射为稳定错误码（FR-014～FR-018）
- [ ] T032 [US2] 在 `web/src/components/kpi-workbench/KpiEvidenceDrawer.tsx` 实现证据抽屉、字段分组、7 日趋势、技术分析折叠、加载失败与重试；源包成功率展示 `base`、来源列和独立关联证据，不展示公式（FR-014～FR-017、SC-024）
- [ ] T033 [US2] 在 `web/src/components/kpi-workbench/KpiMetricResultsTable.tsx` 与 `web/src/pages/KpiResultWorkbenchPage.tsx` 接入选中行高亮、一次性证据入口、宽/窄桌面布局、键盘操作和任务切换上下文清理（FR-014、FR-021～FR-023）

**检查点**：US2 可独立验证；证据失败不影响汇总、其他行和当前筛选。

---

## 阶段 5：用户故事 3 - 按需维护网元类型内共享的关注列表（优先级：P3）

**目标**：维护人员从当前任务指标目录手动批量加入/移出团队关注；同一网元类型跨任务共享，UMF/CSP 完全隔离，初始为空且不迁移旧 `enabled`。

**独立测试**：两个不同任务、两个维护会话在 UMF 保存关注后共享相同列表；相同 ID 的 CSP 关注不受影响；未保存关闭有确认；revision 冲突保留暂存选择。

### 用户故事 3 的测试

- [ ] T034 [P] [US3] 在 `tests/test_kpi_team_focus_v6.py` 编写失败服务测试，覆盖三元组身份、UMF/CSP 同 ID 隔离、跨任务共享、不可用项保留、初始为空和旧 `enabled` 不迁移（FR-002、FR-008、FR-010、FR-011、SC-016、SC-018）
- [ ] T035 [US3] 在 `tests/test_kpi_team_focus_v6.py` 增加 API 契约测试，覆盖 GET/PATCH、`expected_revision`、原子 add/remove、`409 task_result_requires_rebuild`、`409 team_focus_revision_conflict` 和读写权限（FR-002、FR-008、SC-008）
- [ ] T036 [P] [US3] 在 `web/src/components/kpi-workbench/TeamFocusDrawer.test.tsx` 编写失败组件测试，覆盖搜索、测量单元筛选、批量加入/移出、dirty 关闭确认、revision 冲突重试和只读权限（FR-008、FR-009、SC-006）
- [ ] T037 [P] [US3] 在 `web/src/pages/KpiResultWorkbenchPage.test.tsx` 增加失败集成测试，验证“管理团队关注”为唯一入口、保存后三视图计数更新且巡检/报告数据不变（FR-008～FR-010、FR-023、SC-007）

### 用户故事 3 的实现

- [ ] T038 [US3] 在 `app/services/kpi_team_focus.py` 实现按 `network_element_type + measurement_unit_id + metric_resource_id` 的共享关注读取、差异 PATCH、revision 冲突、不可用项保留和原子事务（FR-002、FR-008～FR-011）
- [ ] T039 [US3] 在 `app/api/kpi_v6.py` 实现 `GET/PATCH /api/v6/kpi/team-focus/{network_element_type}`，复用现有登录与 `admin` 写权限，映射旧任务重建和 revision 两类 409，不新增个人关注或设备维度（FR-002、FR-008、SC-008）
- [ ] T040 [US3] 在 `web/src/components/kpi-workbench/TeamFocusDrawer.tsx` 实现当前网元类型共享标识、搜索、筛选、批量选择、暂存、放弃确认、保存、冲突状态和任务切换清理（FR-009、FR-023）
- [ ] T041 [US3] 在 `web/src/pages/KpiResultWorkbenchPage.tsx` 接入唯一关注管理入口，并在保存成功后重新加载 summary 与当前视图，不重跑巡检
- [ ] T042 [US3] 在 `web/src/pages/MeasurementUnitsPage.tsx` 移除独立“关注指标”编辑 tab，只保留跳转到 `/tasks/:taskId/kpi` 的团队关注查看入口（FR-008、FR-024、SC-011）

**检查点**：US3 可独立验证；关注只改变查看范围，不影响巡检、报告或历史结果。

---

## 阶段 6：用户故事 4 - 以测量单元控制巡检范围（优先级：P4）

**目标**：测量单元启停成为唯一日常巡检门禁；启用纳入全部已确认基础指标与已定义派生指标，停用只影响后续任务，历史配置可恢复且有审计。

**独立测试**：停用单位后新任务不包含其指标；重启后全部指标重新纳入；历史指标/绑定/派生 `enabled=false` 不再抑制巡检；单条绑定异常可修正且无批量确认入口。

### 用户故事 4 的测试

- [ ] T043 [P] [US4] 在 `tests/test_kpi_measurement_scope_v6.py` 编写失败测试，覆盖测量单元唯一开关、基础/派生计数、停用只影响后续、重启恢复全部指标、配置不完整指标保留和指标级 `enabled` 不参与门禁（FR-025～FR-027、FR-029～FR-031、SC-009、SC-011、SC-014）
- [ ] T044 [US4] 在 `tests/test_kpi_measurement_scope_v6.py` 增加恢复与待归属失败测试，覆盖逐对象审计、部分成功 `partial_success`、失败项重试、幂等键和绑定单条异常修正（FR-028、FR-031、SC-010、SC-014）
- [ ] T045 [P] [US4] 在 `web/src/pages/MeasurementUnitsPage.test.tsx` 编写失败测试，验证唯一启停开关、基础/派生数量、历史恢复提示、无指标空态、无指标级开关、单条异常修正、无批量确认和关注入口跳转（FR-024、FR-027、FR-030、FR-031、SC-011、SC-014）
- [ ] T046 [P] [US4] 在 `tests/test_kpi_v6_migration.py` 增加测试，确认单位启用状态不被历史恢复隐式改变，历史停用只产生恢复审计（FR-028、SC-010）

### 用户故事 4 的实现

- [ ] T047 [US4] 在 `app/services/kpi_measurement_scope.py` 实现测量单元列表/详情、唯一启停、基础与派生指标计数、revision 并发、“只影响后续巡检”审计和配置不完整指标保留（FR-027、FR-030）
- [ ] T048 [US4] 在 `app/services/kpi_measurement_scope.py` 实现历史停用逐对象恢复、部分成功、失败重试、幂等键、待归属解析和单条绑定修正，成功项不回滚（FR-028、FR-031）
- [ ] T049 [US4] 在 `app/api/kpi_v6.py` 实现测量单元 GET/PATCH、绑定 GET/PATCH、恢复审计 GET/POST retry、待归属 GET/POST resolve 和维护操作 GET，匹配 202+Location 契约
- [ ] T050 [US4] 在 `web/src/pages/MeasurementUnitsPage.tsx` 重构为测量单元级启停、基础/派生数量、恢复审计提示、待归属处理和单条绑定异常修正
- [ ] T051 [US4] 从 `web/src/pages/MeasurementUnitsPage.tsx` 移除批量确认绑定与指标级巡检开关，前台不再调用 `/api/v5/kpi/measurement-bindings/batch-confirm`（FR-031、SC-014）
- [ ] T052 [US4] 在 `app/services/kpi_daily_health_snapshot.py` 改为读取 v6 测量单元启停与 v6 已确认绑定/派生，不再用指标、绑定或派生 `enabled` 排除执行（FR-025、FR-026、FR-029）

**检查点**：US4 可独立验证；测量单元是唯一日常巡检启停粒度，历史配置可审计恢复。

---

## 阶段 7：用户故事 5 - 查看全部指标全貌并快速定位（优先级：P5）

**目标**：“全部指标”展示任务范围全部指标，支持名称/ID/单位搜索与单位、判定、趋势筛选；无匹配、无指标和关注为空必须区分。

**独立测试**：切换三视图后顶部汇总不变；全部指标始终包含未关注、待配置和无数据项；清除筛选一次恢复；无匹配空态与任务无指标空态文案不同。

### 用户故事 5 的测试

- [ ] T053 [P] [US5] 在 `tests/test_kpi_workbench_v6.py` 增加全部指标与筛选失败测试，覆盖 `all/team_focus/needs_attention` 三视图、名称/ID/单位搜索、判定/趋势筛选、`visible/total` 和稳定排序（FR-001、FR-006、FR-007、FR-012、FR-013、SC-007）
- [ ] T054 [P] [US5] 在 `web/src/components/kpi-workbench/KpiResultViews.test.tsx` 编写失败组件测试，覆盖三视图计数、筛选可见数、清除筛选、关注为空、任务无指标、筛选无匹配三类空态及键盘操作（FR-006、FR-007、FR-012、FR-013、FR-021、FR-022）
- [ ] T055 [P] [US5] 在 `web/src/pages/KpiResultWorkbenchPage.test.tsx` 增加失败测试，验证切换视图或筛选不改变全局 summary，切换任务会清除上一任务的指标选择、筛选和证据（FR-003、FR-012、FR-014、FR-023）

### 用户故事 5 的实现

- [ ] T056 [US5] 在 `app/services/kpi_workbench.py` 完成 `team_focus` 与 `all` 投影，包含未关注、配置不完整、无数据、无法判定和关注不可用项，配置不完整项显示待配置或无法判定（FR-001、FR-006、FR-007、FR-027）
- [ ] T057 [US5] 在 `app/services/kpi_workbench.py` 实现名称/ID/单位搜索、测量单元/判定/趋势筛选、可见数与总数计算，保持服务端排序权威（FR-012、FR-013）
- [ ] T058 [US5] 在 `app/api/kpi_v6.py` 扩展 metrics 查询参数与响应，三视图均只返回服务端最终分组和稳定排序键（FR-006、FR-007、FR-012、FR-013）
- [ ] T059 [US5] 在 `web/src/components/kpi-workbench/KpiResultViews.tsx` 实现三视图 tabs、筛选栏、可见数量、清除筛选和三类空态（FR-006、FR-007、FR-012、FR-013、FR-021、FR-022）
- [ ] T060 [US5] 在 `web/src/pages/KpiResultWorkbenchPage.tsx` 接入三视图、筛选状态和任务切换清理逻辑，禁止前端重算判定分组（FR-003、FR-012、FR-023）

**检查点**：US5 可独立验证；三视图计数、筛选与空态一致且全部指标可追溯。

---

## 阶段 8：用户故事 6 - 按网元类型动态配置业务规则（优先级：P6）

**目标**：业务规则不设公共归属，运行时至少归属一个网元类型；任务开始时冻结规则/KPI 范围，日志补充包单选规则适用类型，旧任务通过同一 `task_id` 重建。

**独立测试**：UMF、CSP、多归属和未归属规则分别进入正确任务；未归属不生成 `skip`；执行中改归属不影响当前任务；日志包只执行所选类型规则；旧任务 v6 返回 409 并可在任务行重建。

### 用户故事 6 的测试

- [ ] T061 [P] [US6] 在 `tests/test_rule_network_assignments_v6.py` 编写失败服务/API 测试，覆盖逐条与批量归属、一个规则多个类型、清空归属进入未归属、revision 冲突、审计、“无公共规则”、升级后初始未归属、旧启停不转归属和清空最后归属确认（FR-035～FR-038、FR-041、FR-043、FR-044、SC-019、SC-023）
- [ ] T062 [P] [US6] 在 `tests/test_rule_scope.py` 编写失败解析器测试，覆盖规则注册表指纹、归属 revision、UMF/CSP 过滤、未归属不执行、隐藏解压/分类不受限和 prepare 跟随 owner（FR-036～FR-040、FR-042、SC-020）
- [ ] T063 [P] [US6] 在 `tests/test_kpi_scope_snapshot.py` 编写失败测试，覆盖任务开始冻结启用单位、已确认基础指标、已定义派生指标、配置指纹和排队期间变更不进入当前任务（FR-028、FR-039、FR-041、SC-022）
- [ ] T064 [P] [US6] 在 `tests/test_task_rebuild_v6.py` 编写失败测试，覆盖旧任务 v6 固定 `409 task_result_requires_rebuild`、行内重建保持 `task_id`、重建刷新输出、原始包只读、`package_missing` 和 `scene_cleaned` 边界（FR-020、SC-012）
- [ ] T065 [P] [US6] 在 `tests/test_log_supplement_network_scope.py` 编写失败测试，覆盖日志包单选 UMF/CSP/不指定、冲突顺序 `checksum → package_kind → product → rule_network_element_type`、`GENERIC` profile、`product` 为空且不产生台账观测（FR-039、FR-040、SC-021）
- [ ] T066 [P] [US6] 在 `web/src/pages/InspectorsPage.test.tsx` 编写失败测试，覆盖规则归属标签、多选网元类型、批量设置、未归属、初始未归属、清空最后归属二次确认和写权限（FR-037、FR-043、FR-044、SC-019、SC-023）
- [ ] T067 [P] [US6] 在 `web/src/pages/TaskListPage.test.tsx` 编写失败测试，覆盖日志补充包单选规则适用网元类型、巡检包隐藏字段、矛盾包上传预检、行内重建危险操作确认和重建失败引导（FR-020、FR-039、FR-040、SC-012、SC-021）
- [ ] T068 [P] [US6] 在 `web/src/pages/TaskDetailPage.test.tsx` 编写失败测试，覆盖旧任务 KPI 入口 409 时展示重建动作且不渲染降级面板，并确认健康分、风险排序和旧总览已移除（FR-018、FR-020、SC-012、SC-013）

### 用户故事 6 的实现

- [ ] T069 [US6] 在 `app/services/rule_network_assignments.py` 实现规则目录、逐条/批量归属、清空归属、revision、幂等和审计；任何规则不得写入公共范围，升级后既有规则初始未归属且不读取旧启停（FR-035～FR-038、FR-041、FR-043、FR-044）
- [ ] T070 [US6] 在 `app/services/rule_scope.py` 实现统一 `RuleScopeResolver`，按任务网元类型、归属 revision 和注册表指纹冻结规则代码、版本、优先级与归属 revision（FR-036～FR-038、FR-041、FR-042）
- [ ] T071 [US6] 在 `app/services/kpi_scope.py` 实现 `KpiScopeResolver`，按启用测量单元冻结已确认基础指标、已定义派生指标、配置快照和指纹（FR-025～FR-028、FR-035、FR-041、SC-009、SC-022）
- [ ] T072 [US6] 在 `app/services/tasks.py`、`app/services/executor.py` 和 `app/cli.py` 接入统一规则/KPI 范围解析，任务开始时写快照，移除 `assert_rule_enabled()` 业务门禁，未归属与不匹配规则不生成 `skip`（FR-038～FR-042）
- [ ] T073 [US6] 在 `app/services/tasks.py` 实现单规则/增量重跑只读原快照，快照缺规则返回 `rule_not_in_task_scope`，版本变化返回 `rule_snapshot_version_mismatch`，禁止静默换版本（FR-038、FR-041）
- [ ] T074 [US6] 在 `app/services/tasks.py` 更新全量重建：保持同一 `task_id`、重新冻结当前规则/KPI 范围、原子替换输出并保留原包只读；旧任务 v6 读取统一返回 `409 task_result_requires_rebuild`（FR-020、FR-041、SC-012）
- [ ] T075 [US6] 在 `app/api/kpi_v6.py` 实现规则归属列表、批量更新、逐条 PATCH 和审计接口；在 `app/api/router.py` 保持 v2 inspector-states 为 deprecated 兼容影子，执行器和新服务不读取，新工作台只调用 v6（FR-034、FR-037、FR-038、FR-041、FR-043、SC-019）
- [ ] T076 [US6] 在 `POST /api/v3/tasks` 上传链路实现 `rule_network_element_type` 单值校验与冲突矩阵，只影响业务规则匹配，不写 `product`、不改变 `GENERIC`、不触发台账（FR-039、FR-040、SC-021）
- [ ] T077 [US6] 在 `web/src/pages/InspectorsPage.tsx` 实现规则归属标签、逐条与批量多选网元类型、未归属状态和清空最后归属确认，移除规则级全局启停入口（FR-037、FR-043、FR-044、SC-019、SC-023）
- [ ] T078 [US6] 在 `web/src/pages/TaskListPage.tsx` 实现日志包单选“不指定/UMF/CSP”、上传预检和任务行内“重建”危险确认，成功后刷新同一任务（FR-020、FR-039、FR-040、SC-012、SC-021）
- [ ] T079 [US6] 在 `web/src/pages/TaskDetailPage.tsx` 移除旧 KPI 总览、健康分、风险排序和独立单任务趋势入口，改为昨日行内趋势 + 证据内 7 日趋势，跳转到新工作台；旧任务 409 时只展示重建动作（FR-018、FR-032、SC-013）
- [ ] T080 [US6] 更新 `web/src/pages/TaskListPage.tsx` 与 `web/src/pages/TaskDetailPage.tsx` 的旧任务行为，保证不迁移旧结果、不在错误路径提供回退面板、不在不合规时伪造 `skip` 或全绿结论（FR-020、FR-040、SC-012、SC-013）

**检查点**：US6 可独立验证；规则归属、日志包、任务冻结和旧任务重建形成完整闭环。

---

## 阶段 9：收尾与横切关注点

**目的**：移除废弃入口，完成文档、E2E、视觉和全流程验收。

- [ ] T081 [P] 更新 `docs/architecture.md`、`docs/data-model.md`、`docs/design/mechanisms.md` 和 `docs/api/openapi.yaml` 的说明，记录 v6 范围、旧入口弃用、无公共规则和重建语义
- [ ] T082 [P] 从 `web/src/pages/TaskDetailPage.tsx`、`web/src/pages/MeasurementUnitsPage.tsx` 和 `web/src/components/` 移除旧 KPI 总览、关注 tab、指标级开关和批量确认交互，保留可复用展示组件但不保留废弃数据源
- [ ] T083 [P] 在 `tests/test_service_boundaries.py` 与 `tests/test_contract.py` 增加最终边界断言：路由不直连数据库、v5 字段语义冻结、v6 只能由生成客户端调用、未归属规则不执行
- [ ] T084 在 `web/e2e/kpi-result-workbench.spec.ts` 增加唯一完整主路径 E2E：打开任务 → 需处理 → 证据 → 团队关注加入/移出 → 全部指标；另在独立场景覆盖规则归属和日志补充包
- [ ] T085 在 `web/e2e/task-rebuild-v6.spec.ts` 增加旧任务行内重建 E2E，验证确认文案、同一 `task_id`、重建后新工作台和原始包不被修改（FR-020、SC-012）
- [ ] T086 在 `web/e2e/measurement-scope-v6.spec.ts` 增加测量单元启停与历史恢复 E2E，验证只影响后续任务和单条异常修正（FR-025～FR-028、FR-030、FR-031、SC-009～SC-011、SC-014）
- [ ] T087 按 `specs/041-kpi-result-workbench/quickstart.md` 执行真实合成样例的 API/页面全流程，记录结果并确保未使用真实数据包或把运行产物加入暂存区
- [ ] T088 使用 Google Chrome 在 1280×900、1440×900、1920×1080 验证已确认 `specs/041-kpi-result-workbench/assets/mockups-v2/review-v2.html` 和实际页面，确认无页面级横向滚动、1440 首屏至少 5 条需处理、状态不只依赖颜色、键盘可操作关注与证据
- [ ] T089 执行 `.venv/bin/python build.py lint`、`.venv/bin/python build.py test`，修复所有失败并保存验证输出
- [ ] T090 执行 `.venv/bin/python build.py contract`、`.venv/bin/python build.py gen-web-api`、`.venv/bin/python build.py web-build`、`.venv/bin/python build.py e2e`，确认契约、生成客户端、构建和 E2E 全部通过
- [ ] T091 执行 `.venv/bin/python build.py verify`，并逐项对照 FR-001～FR-044、SC-001～SC-024、六用户故事和 quickstart 记录验收证据；未通过项不得宣告完成

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 1（设置）**：无依赖，先完成契约与样例。
- **阶段 2（基础层）**：依赖阶段 1，阻塞全部用户故事。
- **阶段 3～8（用户故事）**：均依赖阶段 2；按 P1～P6 顺序交付，故事内部按测试 → 模型/服务 → API → 前端 → 独立验证执行。
- **阶段 9（收尾）**：依赖 US1～US6 全部完成。

### 用户故事依赖

- **US1（P1）**：基础层后即可开始，交付 MVP 首屏。
- **US2（P2）**：依赖 US1 的结果行和服务端最终判定。
- **US3（P3）**：依赖 US1 的三视图和基础层关注表；关注写入不得改变巡检结果。
- **US4（P4）**：依赖基础层与 KPI 范围快照；影响后续任务，不改历史。
- **US5（P5）**：依赖 US1 和 US3 的视图/关注投影，完成全貌与筛选。
- **US6（P6）**：依赖 US4 的 KPI 范围和基础层任务快照，完成规则归属、日志包和重建。

### 每个故事内部

- 先写测试并运行确认失败，再写最小实现。
- 服务端先定契约与最终判定，前端只渲染生成客户端返回结果。
- 同一行为只保留一个权威测试层：单元测判定，集成测事务与持久化，契约测 Schema，组件测交互，E2E 只测完整用户路径。
- 每个故事完成后在检查点独立验证，再进入下一优先级。

### 并行机会

- T001、T004、T006 可并行编写。
- T007、T009 可并行；T008 完成后再做 T010、T011、T012。
- 每个故事的测试任务可在实现前并行编写，但实现任务必须按依赖顺序执行。
- T081、T082、T083 可在所有用户故事完成后并行。
- T084～T086 可在对应功能完成后并行编写和运行。

---

## 并行示例

```text
T001 在 tests/test_kpi_v6_contract.py 编写 v6 契约失败测试
T004 在 tests/test_kpi_v6_fixture.py 编写合成样例失败测试
T006 在 tests/conftest.py 建立 v6 合成数据库夹具
```

```text
T081 更新 docs/architecture.md 等架构文档
T082 移除旧 KPI 前端入口与废弃交互
T083 增加路由/契约边界测试
```

---

## 实现策略

### MVP 优先

1. 完成阶段 1：契约、生成客户端、合成样例。
2. 完成阶段 2：v6 表、迁移、任务镜像和路由骨架。
3. 完成 US1：汇总 + 默认需处理首屏。
4. **停止并验证**：20 指标/10 关注样例在 1440×900 首屏满足 SC-001～SC-005。
5. 继续 US2～US6，最后执行阶段 9 全部门禁。

### 增量交付

1. 契约 + 基础层 → v6 可读写、迁移幂等。
2. US1 → 首屏需处理（MVP）。
3. US2 → 证据核验与技术分析。
4. US3 → 团队关注共享。
5. US4 → 测量单元级巡检范围。
6. US5 → 全部指标全貌与筛选。
7. US6 → 规则归属、日志包、任务冻结与重建。
8. 收尾 → 旧能力退出、视觉验收、lint/test/contract/web/E2E/verify。

---

## 注意事项

**[P]** 任务必须对应不同文件或无未完成依赖；不得把同一文件的并行任务误标为 [P]。
- 所有新接口先改 `docs/api/openapi.yaml`，再改 Pydantic/FastAPI 和 `web/src/api/client.ts`。
- 永不修改真实上传包；禁止把 `uploads/`、`output/`、`data/`、真实日志、报告或截图加入 Git。
- 成功率始终是源包直接提供的 `base` 指标，不得按请求数、成功响应数或失败响应数重算、回填或另建派生指标；空源值按缺失处理。
- 删除或替换旧 KPI 功能前先确认新用户路径可用；旧任务不迁移，只允许同一 `task_id` 行内重建。
- 完成定义以 `quickstart.md`、FR-001～FR-044、SC-001～SC-024 和全部质量门禁为准，不以局部函数通过为准。
