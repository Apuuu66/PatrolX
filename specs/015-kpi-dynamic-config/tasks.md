---
description: "KPI 按需分类与动态口径配置任务列表"
---

# 任务：KPI 按需分类与动态口径配置

**输入**：`specs/015-kpi-dynamic-config/spec.md` 及同目录设计文档。

## 阶段 0：研究与规划

- [x] T000 完成功能边界与关键设计研究，固化 `research.md` 与 `plan.md`：SQLite 动态配置权威、不做规则 JSON 迁移、快照 v2、按需线索匹配、受控 ratio 边界、版本审计、`/api/v4` 与失败策略。
- [x] T000.1 确认阶段 0–6 的交付范围、依赖顺序和验收路径，确保规格、计划与任务清单一致。

**检查点**：范围、数据来源、契约版本、快照机制和验证策略在实现前已评审确定。

## 阶段 1：设置

- [x] T001 在 `docs/api/openapi.yaml` 固化 `/api/v4` KPI 配置、审计、按需分类线索和快照响应契约。
- [x] T002 在 `app/models/db.py` 增加 KPI 指标规则、公式、阈值、容量规则、展示规则、公共配置、规则配置修订和审计表。
- [x] T003 在 `app/models/schemas.py` 增加 `/api/v4` 请求/响应模型和 `schema_version=2` 快照模型。
- [x] T004 在 `app/inspectors/kpi/catalog.py` 将聚合能力收敛为 `sum`、`min`、`max`、`mean`、`count`、`median`、`stddev`、`success_rate`，保留受控 `ratio` 公式。

**检查点**：契约、持久化模型、API 模型和受控聚合基础就绪。

## 阶段 2：动态配置基础

- [x] T005 在 `app/services/kpi_config.py` 实现基础资源校验、动态配置 CRUD、事务、审计和 `rule_config_version` 递增。
- [x] T006 实现公式、分类、阈值、容量和展示配置之间的引用保护与循环检查。
- [x] T007 在 `app/services/kpi_catalog.py` 组合 Git base、SQLite 分类和动态配置，生成原子快照 v2。
- [x] T008 确保已有快照单规则重跑复用，全量重建按当前配置新建快照。
- [x] T009 在 `app/tools/kpi_catalog.py` 增加离线基础资源替换保护，拒绝移除数据库仍引用的指标。
- [x] T010 增加动态配置和快照组合的单元测试。

**检查点**：数据库为权威配置源，空配置可生成合法任务快照。

## 阶段 3：按需分类线索与配置 API

- [x] T011 在 `app/services/kpi_classification_clues.py` 解析任务内真实 KPI 列，输出 `unclassified`、`classified`、`unregistered`、`ambiguous` 线索。
- [x] T012 在 `app/api/router.py` 增加 `/api/v4` KPI metric-rules、thresholds、capacity-rules、display-rules、common-config、audits 和任务线索路由。
- [x] T013 保证 `/api/v3` 分类接口语义不变，且线索不改变规则 `pass/warn/fail/error/skip` 状态。
- [x] T014 增加 `/api/v4` 契约、分页、错误处理、审计和任务线索集成测试。

**检查点**：前端可基于契约完成全部配置和按需分类操作。

## 阶段 4：前端 KPI 配置中心

- [x] T015 生成并接入 `/api/v4` OpenAPI 客户端。
- [x] T016 将 `web/src/pages/KpiResourcesPage.tsx` 升级为 KPI 配置中心入口。
- [x] T017 在 `web/src/components/KpiFormulaEditor.tsx` 实现 raw 聚合 `sum`、`min`、`max`、`mean`、`count`、`median`、`stddev` 和派生 `success_rate` 的受控 ratio 编辑。
- [x] T018 在 `web/src/components/KpiThresholdEditor.tsx` 实现默认阈值和 5/15/30/60 分钟周期阈值编辑。
- [x] T019 实现容量规则、展示规则、公共配置和审计管理界面。
- [x] T020 在 `web/src/components/KpiClassificationClues.tsx` 和任务详情实现线索展示、分类跳转和手动重跑提示。
- [x] T021 增加前端关键交互测试并确保桌面构建通过。

**检查点**：分类、阈值、聚合公式和全部动态口径均可在前台维护。

## 阶段 5：退役 Git 规则 JSON

- [x] T022 从运行时加载链路移除 `rules/metric-rules.json`、`rules/thresholds.json`、`rules/capacity-rules.json` 和 `rules/display-rules.json` 依赖。
- [x] T023 从运行时加载链路退役 `rules/common.json`，并在文档中保留其过渡期备份说明。
- [x] T024 更新 `docs/architecture.md`、`docs/data-model.md`、`docs/roadmap.md` 和相关说明。

**检查点**：移除 rules JSON 后新任务仍可执行。

## 阶段 6：集成验证与收尾

- [x] T025 执行 `python build.py contract` 与 `python build.py gen-web-api`。
- [x] T026 执行 `python build.py lint` 和 `python build.py test`。
- [x] T027 执行 `python build.py verify` 和 `cd web && npm run build`。
- [x] T028 按 `quickstart.md` 完成人工场景检查，并修复发现的问题。

**检查点**：契约、后端、前端、离线巡检全流程均通过。

## 依赖关系

1. 阶段 0 → 阶段 1 → 阶段 2 → 阶段 3。
2. 阶段 3 完成后可进入阶段 4。
3. 阶段 4 依赖生成的 API 客户端。
4. 阶段 5 需要动态配置和快照链路稳定。
5. 阶段 6 是最终交付门禁。

## 并行机会

- T001/T002/T003 可在设计确认后并行准备，但契约仍作为实现校验源。
- T017/T018/T019 在模型和客户端稳定后可并行开发。
- 后端测试和前端组件测试可按对应用户故事并行编写。
