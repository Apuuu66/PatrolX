# KPI 当前判定与昨日趋势 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 KPI 首屏直接回答每个指标“当前是否正常”和“较昨日改善/稳定/恶化”，并提供可追溯的对象/周期证据、日聚合成功率、维护配置和 7 日趋势。

**Architecture:** 新增纯业务服务 `app/services/kpi_daily_health.py`，由巡检器在已有内存时间序列上生成紧凑 `metadata.daily_health`；摘要、页面和 HTML 报告只消费该结构。维护配置写入独立 SQLite 配置/审计表，旧阈值字段保持兼容。单指标 7 日详情通过按任务、测量单元、指标过滤的查询生成，禁止首屏调用全量 `list_kpi_points()`。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy/SQLite、Jinja2、React、TypeScript、Vite、Ant Design、原生 SVG、pytest、Playwright。

**Spec:** `specs/040-kpi-daily-health/spec.md`

## Global Constraints

- 不连接被检系统、不做在线采集；只读取任务解压后的 CSV 和本地 SQLite 元数据。
- 不修改原始上传包、真实数据库、真实样例包或现场报告；开发验收使用隔离数据库与合成 fixture。
- OpenAPI 先于实现变更；所有新增前端调用来自生成客户端类型。
- 不改变旧 `business_status`、`health_score`、`metric_coverage` 字段含义；新结论只写入 `metadata.daily_health` 或新增接口。
- 当前判定仅允许 `normal/warn/fail/pending_config/unable_to_judge/not_applicable`。
- 较昨日仅允许 `improved/stable/worsened/observe/no_baseline`。
- 聚合成功率只按 `当日分子总和 / 当日分母总和 × 100` 计算；分母为零为“不适用”。
- 四个名称相近的成功率不合并、不按名称猜测依赖；没有独立配置时显示待配置或无法判定。
- 全零未确认不得为正常；无阈值、无方向、无有效数据不得为正常。
- 只统计测量单元启用、绑定已确认、指标资源启用的范围；停用单元文件进入范围外，不计未匹配业务异常。
- 首屏禁止读取 `TaskKpiPoint` 全量点；详情接口单次只读取单测量单元、单指标、限定日期窗口的数据。
- 趋势对比严格使用同设备、同测量单元、同指标、同对象、同周期。
- 自然日锚点为任务内最新有效测量时间的 UTC+8 日期；存储仍为 UTC。
- KPI 规则逻辑变化后 `rule_version` 升级到 `3.4.0`。
- FR-037 本期只交付现有 HTML 报告；仓库没有 Markdown 报告产物，不新增虚构的 Markdown 交付项。
- 所有新功能必须增加代表性样例包数据和端到端展示验证。

## 技术上下文

- **语言/版本：** Python 3.11+；React 18 + TypeScript 5.6。
- **主要依赖：** FastAPI、Pydantic v2、SQLAlchemy、Jinja2、Ant Design；7 日趋势使用原生 SVG，不引入 ECharts。
- **存储：** SQLite 保存任务/规则镜像和维护配置；任务私有 JSON 与历史索引仍在 `output/<task_id>/`。
- **测试：** pytest 后端；Node test + Vitest 前端；Playwright E2E。
- **目标平台：** 桌面浏览器访问的离线巡检系统。
- **性能目标：** 已完成任务首屏不读取全量约 190 万 KPI 点；摘要只保留约 77 个指标级结论和每个指标的对象/周期计数。单指标 7 日详情仅查询该指标日期窗口。
- **约束条件：** 保持离线、单包单任务、契约驱动、本地/在线共享巡检器；不破坏已有任务读取。

## 宪法检查

### 阶段 0：研究前

- [x] 离线优先：只消费已上传包与本地数据库。
- [x] 一个包、一个任务：新表与接口均以 `task_id` 隔离读取，不引入跨任务合并身份。
- [x] 真实数据隔离：计划和实现只修改合成 fixture；真实验收数据库只读。
- [x] 契约驱动：先更新 OpenAPI，再实现 Schema/API/前端生成客户端。
- [x] 模式同构：日健康在巡检器内生成，CLI 与 API 复用同一结果。
- [x] 插件架构：不修改调度器，只升级 `kpi.measurement_units` 规则及其私有服务。
- [x] 源文件显式匹配：沿用规则声明的 `source_patterns`，不新增跨规则依赖。
- [x] 增量重跑：规则结果仍按规则落盘，元数据向后兼容。
- [x] 解压先行：不改变 `EXTRACT → PREPARE → INSPECT` 阶段屏障。
- [x] 规则私有预处理：日健康只消费本规则已匹配/解析的数据。
- [x] 确定性执行：固定排序、固定容差、UTC+8 日界，不使用页面当前时间。
- [x] 真实数据保护：不暂存 `data/`、`output/`、`uploads/`、截图或报告。

### 阶段 1：设计后复核

- [x] 新配置表只新增、不改旧字段语义；旧资源阈值仍可读取。
- [x] 派生定义去重并建立唯一约束，避免同名多结论漂移。
- [x] API 全部新增路径或新增响应字段，不改变 `/api/v2`、`/api/v5` 既有字段含义。
- [x] 首屏只消费 `metadata.daily_health`，不调用全量历史点接口。
- [x] 报告与页面从同一 `daily_health` 生成，不复制判定算法。
- [x] 配置变更写审计记录，审计不包含真实数据内容。
- [x] 旧任务缺少新字段时展示降级提示，不重算或阻断原有结果。

## 项目结构

### 文档（本功能）

```text
specs/040-kpi-daily-health/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── kpi-daily-health.openapi.yaml
│   └── maintenance-config-contract.md
├── checklists/requirements.md
└── tasks.md
```

### 源代码（真实仓库布局）

```text
app/
├── api/router.py
├── inspectors/kpi/measurement.py
├── models/db.py
├── models/schemas.py
├── reports/templates/report.html.j2
└── services/
    ├── kpi_daily_health.py          # 新增：纯日聚合/判定/趋势
    ├── kpi_measurement_units.py     # 集成范围、派生与 metadata
    ├── results.py                   # 保留摘要中的 daily_health
    └── report.py                    # HTML 报告上下文
web/
├── src/api/client.ts                # 生成，不手改
├── src/api/http.ts                  # 薄封装生成类型
├── src/components/
│   ├── KpiDailyHealthPanel.tsx      # 新增首屏结论与筛选
│   ├── KpiMetricHealthDetail.tsx    # 新增对象/周期与 7 日证据
│   └── MeasurementInspectionPanel.tsx
├── src/pages/MeasurementUnitsPage.tsx
├── src/theme.css
└── e2e/kpi-daily-health.spec.ts
tests/
├── fixtures/make_real_package.py
├── test_kpi_daily_health.py
├── test_kpi_daily_health_api.py
├── test_kpi_maintenance_config.py
└── test_kpi_measurement_scenarios.py
docs/api/openapi.yaml
```

**结构决策：** 日健康计算不进入 API 层或 React；纯函数服务是唯一判定实现。巡检器负责将点、资源和配置组装成输入，API 只读取已生成结论或按需生成详情。前端不做业务判定，只做状态展示和筛选。

## API 与数据设计摘要

### 首屏

`RuleResult.metadata.daily_health` 新增：

- `schema_version: 1`
- `data_date`、`previous_date`、`latest_measured_at`、`timezone`
- `current_counts`、`trend_counts`
- `scope`：启用单元数、绑定指标数、预期指标数、范围外文件数、未确认绑定数
- `metrics[]`：指标级结论，包含角色、今日值、当前判定、昨日值、较昨日、阈值/容差来源、对象/周期计数和首要原因
- `legacy_fallback`：旧任务或无法生成时的降级原因

`summarize_kpi_result()` 不删除 `daily_health`，但会继续移除点级明细；首屏数据必须控制为指标级。

### 单指标详情

新增只读接口：

```text
GET /api/v2/tasks/{task_id}/rules/{rule_code}/daily-health/{measurement_unit_id}/{metric_resource_id}
```

返回当前/昨日对象周期组、7 日趋势、分子分母、原始成功率一致性、来源文件、配置来源与判定依据。服务使用过滤条件 `task_id + measurement_unit_id + metric_resource_id + measured_at window`，不调用全量列表函数。

### 维护配置

新增：

```text
GET   /api/v5/kpi/metric-maintenance-configs
GET   /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}
PATCH /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}
GET   /api/v5/kpi/metric-maintenance-configs/{measurement_unit_id}/{metric_resource_id}/audits
GET   /api/v5/kpi/measurement-derived
GET   /api/v5/kpi/measurement-derived/{id}
PATCH /api/v5/kpi/measurement-derived/{id}
```

配置字段覆盖角色、日聚合、日变化阈值、百分比语义、零值语义、一致性容差、对象匹配口径；方向与当前阈值通过既有资源字段读写并在同一事务中审计。

## 实现顺序（TDD）

1. 更新 OpenAPI 契约与 Pydantic Schema，生成前端客户端。
2. 先写纯业务失败测试，再实现 `kpi_daily_health`：日聚合、阈值、全零、分母为零、趋势、pp。
3. 新增配置/审计表与派生唯一性迁移测试，再实现服务层。
4. 集成巡检器并升级 `rule_version=3.4.0`；修复停用文件范围统计。
5. 实现单指标 7 日详情 API 和维护配置 API。
6. 实现摘要、HTML 报告和 React 首屏/详情/配置交互。
7. 扩充合成样例包和 E2E，覆盖正常、预警/失败、无基线、全零、分母为零、范围外和旧任务降级。
8. 执行 lint/test/contract/gen-web-api/web-build/verify/e2e，启动应用并打开已完成任务页面。

## 指标级聚合与下钻规则

- 一个测量单元内同一指标可能包含多个对象和周期；指标行用于首屏汇总，不能丢失底层组。
- 当前判定聚合优先级：`fail > warn > unable_to_judge > pending_config > not_applicable > normal`。
- 较昨日聚合优先级：`worsened > improved > observe > no_baseline > stable`；任何对象恶化都进入重点关注。
- 详情按 `object_key + period_minutes` 分组，逐组展示今日/昨日值和依据；不把不同对象或周期混合计算趋势。
- 指标级今日值只作摘要：单组直接显示日值；多组显示组数并由详情下钻，禁止用跨对象均值掩盖最差对象。
- 四个名称相近的成功率保持独立 `metric_resource_id`、独立派生配置、独立证据和独立结论。

## 需求映射

| 需求 | 实现/验证 |
| --- | --- |
| FR-001~007 | `KpiDailyHealthPanel` 两组独立分布、指标表、数据日期与范围；组件/E2E 断言 |
| FR-008~015 | 纯判定函数、状态原因、配置缺失证据；单测覆盖每类状态 |
| FR-016~025 | UTC+8 锚点、同对象周期匹配、受控日聚合、pp 与默认容差；聚合单测 |
| FR-026~032 | 配置表/API、独立派生定义、范围快照和停用文件测试 |
| FR-033~034 | 单指标详情 API + React 详情，聚合/基础指标分别断言 |
| FR-035 | `legacy_fallback` 与前端提示；旧结果 fixture 测试 |
| FR-036 | CLI/API 共用 inspector 结果；集成测试比较 metadata |
| FR-037 | HTML 报告读取 `metadata.daily_health`；报告测试断言分布和重点项 |
| FR-038 | 现有字段不删除、不改含义；契约测试和旧任务读取测试 |
| SC-001~003 | 首屏统计与表格总和一致、无依据正常为 0 的组件/E2E 断言 |
| SC-004~006 | 波动分母样例、四个独立成功率、零分母状态单测 |
| SC-007 | 合成样例包含无数据与全零指标，API/页面验收 |
| SC-008 | 停用单元范围外计数与未匹配异常断言 |
| SC-009 | ≥20 指标样例的 Playwright 路径，定位全部重点项 |
| SC-010 | 旧任务 fixture 打开成功、无新增字段报错 |

## 复杂度跟踪

| 项目 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 独立维护配置与审计表 | 日聚合、零值语义和变化阈值不能复用现有单值阈值字段 | 直接扩展资源表会让历史 CSV 导入覆盖配置，且无审计 |
| 单指标详情接口 | 首屏不能扫描全量 KPI 点 | 首屏携带 1466 组 × 7 日证据会使摘要过大 |
| 派生唯一约束 | 防止同名派生配置出现多份互相矛盾的结论 | 仅靠应用层查重无法约束并发和旧库重复数据 |

## 风险与缓解

- **SQLite 迁移耗时/失败：** 先在事务内对重复派生行去重，再创建唯一索引；测试覆盖旧表已有重复行。
- **首屏性能退化：** 摘要只保留指标级数据；测试断言详情查询路径不调用 `list_kpi_points`。
- **旧任务不可读：** 所有新增 metadata 访问使用防御式类型检查；缺字段展示降级提示。
- **历史回退跨任务误匹配：** 只有设备 ID、对象、周期全部一致才回退；无设备 ID 时只使用当前任务。
- **配置误判为正常：** 任何不完整配置、全零未确认或数据缺口都优先进入待配置/无法判定。

## 验收门槛

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
.venv/bin/python build.py web-build
.venv/bin/python build.py verify
.venv/bin/python build.py e2e
```

最终必须启动应用，使用代表性合成样例或已存在任务在真实 UI 中打开验证，截图仅留在临时目录，不进入 Git。
