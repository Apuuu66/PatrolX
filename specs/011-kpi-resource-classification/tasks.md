# 任务：KPI 资源全集登记与在线分类

**输入**：来自 `/specs/011-kpi-resource-classification/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/kpi-resource-metrics.yaml

## 阶段 1：设置（共享基础设施）

- [x] T001 确认分支/worktree，并在 `docs/api/openapi.yaml` 中新增 `/api/v2/kpi/resource-metrics`、`/api/v2/kpi/resource-metrics/classification` 及对应 Schema 契约。
- [x] T002 执行 `python build.py contract`，确认 OpenAPI 契约解析通过。
- [x] T003 执行 `python build.py gen-web-api`，更新 `web/src/api/client.ts` 生成客户端。

## 阶段 2：基础层（阻塞前置条件）

- [x] T004 在 `app/models/schemas.py` 定义 `KpiResourceMetric`、`KpiResourceMetricPage`、`KpiResourceImportReport`、`KpiResourceClassificationRequest`、`KpiResourceClassificationResult` 及域枚举，字段与 data-model.md 一致。
- [x] T005 在 `tests/test_kpi_resource_metrics.py` 编写资源库服务失败用例：非法资源 ID、重复 ID 冲突、`UNIT_` 跳过、占位英文名、括号单位、重复导入幂等。
- [x] T006 在 `app/services/kpi_resources.py` 实现资源指标库模型、文件读写锁、revision、CSV 解析、基础类型推断和资源库登记。
- [x] T007 在 `tools/generate_kpi_config.py` 改为资源 CSV 模式复用 `app/services/kpi_resources.py`，移除 `--domain` 强制依赖；同步更新 `tests/test_kpi_config_generator.py` 和脚本用法。
- [x] T008 执行 `python build.py lint` 和 `pytest tests/test_kpi_resource_metrics.py tests/test_kpi_config_generator.py`，确认资源导入基础层通过。

## 阶段 3：用户故事 1 - 从资源全集生成基础指标库（优先级：P1）🎯 MVP

**目标**：用户导入资源 CSV 后得到完整、未分类、可持久化的基础指标库。

**独立测试**：给定包含 `UNIT_*` 和 `ME_*` 的 CSV，执行导入后检查资源库文件和导入报告；重复导入不增加数量。

### 用户故事 1 的实现

- [x] T009 [US1] 在 `app/services/kpi_resources.py` 添加导入报告统计：`row_count`、`new_metrics`、`updated_metrics`、`skipped_units`、`skipped_rows`、`invalid_rows`、`missing_registered`。
- [x] T010 [US1] 在 `app/services/kpi_resources.py` 添加审计记录写入，导入成功后记录操作时间、summary 和 revision。
- [x] T011 [US1] 在 `docs/architecture.md` 和 `docs/design/entrypoints.md` 补充资源库文件、导入路径和“不自动分类”的职责说明。
- [x] T012 [US1] 用真实样例结构执行 CLI 资源导入预览和登记，确认三个域配置文件不被修改。

**检查点**：资源全集导入可独立使用，所有指标为未分类。

## 阶段 4：用户故事 2 - 查找和审查资源指标（优先级：P1）

**目标**：用户可在专用页面搜索、分页、筛选资源指标并查看基础信息。

**独立测试**：给定 100 个指标，使用资源 ID/中文名/英文名搜索和域筛选，可定位任意指标。

### 用户故事 2 的测试

- [x] T013 [P] [US2] 在 `tests/test_kpi_resource_api.py` 编写列表 API 用例：分页、搜索、域筛选、统计摘要和 404 之外的基础错误响应。
- [x] T014 [P] [US2] 在 `web/src/components/KpiResourceTable.test.ts` 编写前端模型用例：搜索参数、状态文案、行选择和分页映射。

### 用户故事 2 的实现

- [x] T015 [US2] 在 `app/services/kpi_resources.py` 实现分页查询、模糊搜索、域筛选和分类统计摘要。
- [x] T016 [US2] 在 `app/api/router.py` 实现 `GET /api/v2/kpi/resource-metrics`。
- [x] T017 [US2] 在 `web/src/components/kpiResourceModel.ts` 和 `web/src/components/KpiResourceTable.tsx` 实现资源指标表格、状态筛选、搜索和分页。
- [x] T018 [US2] 在 `web/src/pages/KpiResourcesPage.tsx` 组合上传 CSV、表格和反馈；在 `web/src/App.tsx`、`web/src/layouts/MainLayout.tsx` 添加路由和菜单。

**检查点**：资源指标页面可浏览、搜索、筛选，并可上传资源 CSV。

## 阶段 5：用户故事 3 - 在线完成单个或批量分类（优先级：P1）

**目标**：用户可将一个或多个未分类指标原子分类到 `call`、`api` 或 `media`。

**独立测试**：选择若干指标批量分类，刷新后状态和域配置一致；失败时没有部分写入。

### 用户故事 3 的测试

- [x] T019 [P] [US3] 在 `tests/test_kpi_resource_api.py` 编写分类 API 用例：单条、批量、空 keys、非法域、revision 过期、失败后文件不变。
- [x] T020 [P] [US3] 在 `web/src/components/KpiResourceTable.test.ts` 补充分类请求模型和结果反馈用例。

### 用户故事 3 的实现

- [x] T021 [US3] 在 `app/services/kpi_resources.py` 实现批量分类事务：加锁、校验、修改资源库、写入/移除域配置、revision 递增、审计和失败回滚。
- [x] T022 [US3] 在 `app/api/router.py` 实现 `PUT /api/v2/kpi/resource-metrics/classification`。
- [x] T023 [US3] 在 `web/src/components/KpiResourceTable.tsx` 和 `web/src/pages/KpiResourcesPage.tsx` 接入批量选择、目标域选择、分类提交、成功刷新和失败提示。

**检查点**：在线分类完整可用且无自动阈值/公式。

## 阶段 6：用户故事 4 - 保护已引用指标（优先级：P2）

**目标**：被公式或阈值引用的指标禁止重新分类；无引用指标允许换域。

**独立测试**：对已引用指标换域返回明确错误且配置不变；对无引用指标换域成功且只保留新域。

### 用户故事 4 的测试

- [x] T024 [P] [US4] 在 `tests/test_kpi_resource_metrics.py` 编写引用检测用例：公式输入、阈值指标、容量声明和无引用换域。
- [x] T025 [US4] 在 `app/services/kpi_resources.py` 实现跨域引用检测，并在分类事务中阻止冲突操作。

**检查点**：分类安全保护完成。

## 阶段 7：收尾与验证

- [x] T026 运行 `python build.py contract`、`python build.py gen-web-api`，确认无未提交契约差异。
- [x] T027 运行 `python build.py lint`、`python build.py test`、`python build.py web-build`；涉及本地全流程时运行 `python build.py verify`。
- [x] T028 更新 `specs/011-kpi-resource-classification/tasks.md` 完成状态，并做规格/实现一致性自查。
