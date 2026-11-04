# 任务：KPI 当前判定与昨日趋势

**输入**：`specs/040-kpi-daily-health/spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`

**测试策略**：规格要求自动化测试和真实展示验收。先写失败测试，再实现；同一行为只在最合适的测试层保留一处权威断言。

## 阶段 1：设置（共享基础设施）

**目的**：在契约和测试边界就绪前完成实现现场准备。

- [ ] T001 确认实现 worktree、分支、规划提交与真实数据保护边界
- [ ] T002 检查现有 KPI 规则、结果摘要、报告、API、前端和数据库模型的实际结构与兼容点
- [ ] T003 [P] 梳理现有 KPI 测试与 `tests/fixtures/make_real_package.py`，标记需要扩展而非重复的测试层

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：完成契约、共享模型与纯业务核心，任何用户故事都依赖这些能力。

- [ ] T004 在 `docs/api/openapi.yaml` 中先行合并日健康详情、维护配置、审计和派生配置读取/更新契约
- [ ] T005 [P] 在 `app/models/schemas.py` 中新增与 OpenAPI 一致的 Pydantic 请求/响应模型和枚举
- [ ] T006 [P] 在 `tests/test_kpi_daily_health.py` 中编写纯业务失败测试：UTC+8 日界、状态优先级、阈值、全零、零分母、pp 趋势和对象周期隔离
- [ ] T007 在 `app/services/kpi_daily_health.py` 中实现纯日聚合、对象周期分组、当前判定和昨日趋势函数
- [ ] T008 [P] 在 `tests/test_kpi_maintenance_config.py` 中编写模型/迁移失败测试：配置默认值、审计、派生重复去重与唯一约束
- [ ] T009 在 `app/models/db.py` 中新增维护配置、审计表，并为派生配置实现去重后唯一索引迁移
- [ ] T010 在 `app/services/kpi_measurement_units.py` 或独立服务中实现维护配置读取、更新、审计和派生配置更新事务
- [ ] T011 修正派生成功率日聚合：仅使用当日分子总和 ÷ 当日分母总和，分目为零返回不适用，保持受控反向模板
- [ ] T012 [P] 在 `tests/test_kpi_daily_health_api.py` 中编写 API 契约/集成失败测试，覆盖稳定排序、分页、404、409、422 和按指标过滤查询
- [ ] T013 实现单指标日健康详情查询，使用 `task_id + measurement_unit_id + metric_resource_id + measured_at` 窗口过滤，不调用全量 `list_kpi_points()`

**检查点**：契约、共享模型、纯业务判定和存储基础可用，用户故事可以开始集成。

---

## 阶段 3：用户故事 1 - 首屏直接回答“今天是否正常、较昨日如何”（优先级：P1）🎯 MVP

**目标**：KPI 首屏直接展示两套独立结论、范围说明、重点关注和指标结论表。

**独立测试**：含全部当前/趋势状态的合成任务打开后，两组统计与表格逐项一致，重点项默认可见，无数据/待配置不计正常。

### 用户故事 1 的测试

- [ ] T014 [P] [US1] 在 `tests/test_kpi_measurement_scenarios.py` 中新增首屏 metadata、状态分布、范围说明和旧任务降级测试
- [ ] T015 [P] [US1] 在 `web/src/components/KpiDailyHealthPanel.test.tsx` 中编写统计与表格一致、重点项排序、筛选与降级测试
- [ ] T016 [P] [US1] 在 `web/e2e/kpi-daily-health.spec.ts` 中编写从任务详情进入 KPI 首屏的完整用户路径

### 用户故事 1 的实现

- [ ] T017 [US1] 在 KPI 巡检器中生成紧凑 `metadata.daily_health`（指标级结论，不携带 7 日全量点），并将 `rule_version` 升级到 `3.4.0`
- [ ] T018 [US1] 在 `app/services/results.py` 中保留并裁剪 `metadata.daily_health`，保证摘要和规则结果均为指标级
- [ ] T019 [US1] 在 `web/src/components/KpiDailyHealthPanel.tsx` 中实现当前判定、较昨日、数据日期、范围说明和重点关注
- [ ] T020 [US1] 在 `web/src/components/MeasurementInspectionPanel.tsx` 和 `web/src/pages/MeasurementUnitsPage.tsx` 中接入日健康首屏，同时保留既有指标/发现入口
- [ ] T021 [US1] 在 `web/src/api/http.ts` 中使用生成契约类型封装日健康 API，移除相关手写 KPI metadata 类型
- [ ] T022 [US1] 在 `web/src/theme.css` 中补齐六种当前状态、五种趋势状态和重点项的克制视觉样式

**检查点**：首屏可独立回答“今天是否正常、较昨日如何”，统计与表格一致。

---

## 阶段 4：用户故事 2 - 成功率按正确口径聚合并可核对（优先级：P1）

**目标**：成功率详情展示分子、分母、公式、昨日同口径值、一致性校验和 7 日趋势；四个相近成功率独立。

**独立测试**：分钟成功率波动且分母不同的样例中，日值等于日分子总和 ÷ 日分母总和，不等于分钟均值；零分母显示不适用。

### 用户故事 2 的测试

- [ ] T023 [P] [US2] 在 `tests/test_kpi_daily_health.py` 中补充不同分母、原始成功率一致性、依赖缺失、四个相似指标独立和 7 日查询窗口测试
- [ ] T024 [P] [US2] 在 `web/src/components/KpiMetricHealthDetail.test.tsx` 中编写成功率证据与 7 日趋势展示测试
- [ ] T025 [P] [US2] 在 `web/e2e/kpi-daily-health.spec.ts` 中补充点击成功率进入对象/周期详情并核对分子分母的路径

### 用户故事 2 的实现

- [ ] T026 [US2] 在 `app/services/kpi_daily_health.py` 中实现受控成功率公式、反向模板、对象/周期严格匹配和原始列加权一致性校验
- [ ] T027 [US2] 在日健康详情 API 中返回组级今日/昨日证据、公式、阈值来源、变化阈值和最近 7 个自然日
- [ ] T028 [US2] 在 `web/src/components/KpiMetricHealthDetail.tsx` 中使用 ECharts 和表格展示 7 日趋势、分子分母、公式及一致性证据
- [ ] T029 [US2] 在 KPI 配置/结果中保持四个名称相近成功率各自独立 `metric_resource_id`、派生配置和结论，不按名称推测依赖

**检查点**：聚合成功率日值可复算，零分母与依赖缺失不会显示 0% 或正常。

---

## 阶段 5：用户故事 3 - 基础指标使用明确日聚合与全零语义（优先级：P2）

**目标**：基础指标按配置的 latest/mean/sum/max/min 聚合，并明确展示全零语义、有效点数和时间范围。

**独立测试**：同一多日样例中五种聚合方式与全零语义都得到预期日值和理由，未知全零不为正常。

### 用户故事 3 的测试

- [ ] T030 [P] [US3] 在 `tests/test_kpi_daily_health.py` 中补充五种基础日聚合、未知/预期/未触发全零和昨日无基线测试
- [ ] T031 [P] [US3] 在 `tests/test_kpi_maintenance_config.py` 中补充配置 PATCH 后重新生成结论与审计的集成测试
- [ ] T032 [P] [US3] 在 `web/src/components/KpiMetricHealthDetail.test.tsx` 中补充基础指标聚合证据和全零待配置展示测试

### 用户故事 3 的实现

- [ ] T033 [US3] 在 `app/services/kpi_daily_health.py` 中实现基础指标日聚合、有效时间范围、来源文件和无昨日基线判定
- [ ] T034 [US3] 在维护配置服务中实现方向、阈值、日聚合、变化阈值、百分比、零值语义、一致性容差和启用状态的读取与更新
- [ ] T035 [US3] 在 `app/api/router.py` 中实现配置列表/详情/更新和审计列表，写操作记录 actor 并保持事务原子性
- [ ] T036 [US3] 在 `web/src/components/KpiMetricMaintenancePanel.tsx` 中实现指标维护配置查看、编辑、校验和审计入口
- [ ] T037 [US3] 保证巡检器与报告使用同一配置来源，配置变化只影响后续生成/查看结论且旧字段语义不变

**检查点**：维护人员能解释每个今日值的日聚合方式和全零处理依据。

---

## 阶段 6：用户故事 4 - 采集范围与历史兼容不制造噪音（优先级：P3）

**目标**：仅统计启用单元、确认绑定、启用指标；停用文件计入范围外；旧任务优雅降级。

**独立测试**：停用测量单元文件不进入未匹配异常；旧结果缺 `daily_health` 时页面、API 和报告均不崩溃并展示原因。

### 用户故事 4 的测试

- [ ] T038 [P] [US4] 在 `tests/test_kpi_measurement_scenarios.py` 中补充停用单元、未确认绑定、无有效点预期指标和旧任务降级测试
- [ ] T039 [P] [US4] 在 `web/src/components/KpiDailyHealthPanel.test.tsx` 中补充 `legacy_fallback` 缺失/存在两种展示测试
- [ ] T040 [P] [US4] 在报告测试中断言旧任务可渲染且范围外计数不进入业务异常

### 用户故事 4 的实现

- [ ] T041 [US4] 修复 `inspect_measurement_files()` 的范围分类，将停用单元和未确认绑定文件归入范围外而非 `unmatched`
- [ ] T042 [US4] 在 `metadata.daily_health.scope` 中输出启用单元数、绑定数、预期指标数、范围外文件数和排除原因计数
- [ ] T043 [US4] 在页面和报告中展示范围说明与旧任务降级原因，不阻断既有指标和发现查看
- [ ] T044 [US4] 增加派生配置列表/详情/更新 API，验证分子分母属于同一测量单元已确认绑定并保持旧创建接口兼容

**检查点**：统计分母可解释，停用文件不制造未匹配噪音，旧任务可打开。

---

## 阶段 7：报告与展示闭环

**目的**：确保页面、API、CLI 和 HTML 报告消费同一结论。

- [ ] T045 [US1] 在 `app/services/report.py` 和 `app/reports/templates/report.html.j2` 中展示当前判定分布、较昨日分布和重点关注指标
- [ ] T046 [P] [US1] 在报告自动化测试中覆盖分布合计、重点项、零分母与旧任务降级
- [ ] T047 [US1] 在 `tests/fixtures/make_real_package.py` 中新增固定时间戳、幂等的日健康场景，含至少 20 个指标及所有关键边界
- [ ] T048 [US1] 补充 CLI 与 API 对相同合成任务输出一致日健康结论的集成断言
- [ ] T049 [US1] 完成 Playwright E2E 对首屏、重点项、成功率详情、维护配置和旧任务降级的完整路径

---

## 阶段 8：收尾与横切关注点

**目的**：质量门禁、性能、文档和真实页面验收。

- [ ] T050 [P] 更新 `docs/architecture.md`、`docs/data-model.md` 和必要的规则/API 文档，保持与实现一致
- [ ] T051 增加首屏不调用 `list_kpi_points()` 的性能保护测试，并验证详情查询使用单指标日期窗口
- [ ] T052 [P] 检查 TypeScript 无未使用手写契约类型，生成客户端可重复且构建通过
- [ ] T053 运行 `.venv/bin/python build.py lint` 并修复全部问题
- [ ] T054 运行 `.venv/bin/python build.py test` 并修复全部问题
- [ ] T055 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`
- [ ] T056 运行 `.venv/bin/python build.py web-build`、前端单测与 Playwright E2E
- [ ] T057 使用隔离临时数据库运行 `.venv/bin/python build.py verify`，记录合成样例验证结果
- [ ] T058 使用只读真实任务或合成任务启动 `.venv/bin/python build.py run`，在浏览器打开并实际检查首屏、成功率详情、重点项与维护配置
- [ ] T059 检查 `git status --short` 与暂存路径，确认未包含真实包、数据、日志、报告或截图

---

## 依赖与执行顺序

### 阶段依赖

- 阶段 1 → 阶段 2：设置和现状检查完成后再改契约/模型。
- 阶段 2 → 阶段 3~6：纯业务、存储和契约是全部用户故事前置。
- US1、US2 可分别验收；US3 的配置能力依赖已有资源/绑定读取。
- US4 的范围统计与历史降级独立于 US2 的公式细节，但复用同一 metadata。
- 阶段 7 依赖 US1~US4 的可展示结论。
- 阶段 8 依赖全部功能和测试。

### 每个故事内部

- 先测试并确认失败，再实现纯函数/模型，最后接 API、页面、报告。
- 同一文件中的实现任务串行执行。
- 不同组件或测试文件可并行，但不得重复断言同一行为。

## 并行示例

```text
T005 模型契约、T006 纯业务测试、T008 配置迁移测试可以并行。
T014 集成测试、T015 组件测试、T016 E2E 入口测试可以并行。
T023 业务边界测试、T024 详情组件测试可以并行。
T050 文档更新、T052 TypeScript 契约检查、T058 真实页面验收准备可在对应实现稳定后并行。
```

## 实现策略

1. 完成阶段 1~2，尤其先提交 OpenAPI 并让契约测试失败。
2. 交付 US1 与 US2 构成 MVP：首屏结论、正确成功率和重点项。
3. 增加 US3 配置/基础聚合与 US4 范围/兼容。
4. 完成报告、fixture、E2E 和真实页面打开验收。
