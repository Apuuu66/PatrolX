# 任务：KPI 同设备版本对比

**输入**：来自 `specs/026-kpi-device-version-compare/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/version-compare.md

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：任务所属用户故事

## 阶段 1：设置与契约

- [x] T001 [P] [基础] 在 `docs/api/openapi.yaml` 中新增 `MeasurementVersionCandidateList`、`MeasurementVersionCandidate`、`MeasurementVersionCandidateTask`、`MeasurementVersionComparisonTask`、`MeasurementVersionComparisonSummary`、`MeasurementVersionComparison` schema，以及 version-candidates 和 version-compare 两个 path。
- [x] T002 [基础] 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确认后端 Pydantic Schema 与前端客户端同步。

## 阶段 2：基础模型与服务

- [x] T003 [P] [US1/US2] 在 `tests/fixtures/kpi-version-compare/` 添加可展示 fixture 和 README，覆盖当前版本、基线版本、同版本、版本未知和索引缺失场景。
- [x] T004 [P] [US1/US2] 在 `app/models/schemas.py` 添加版本候选和版本对比模型、方向枚举与字段校验。
- [x] T005 [US1/US2] 在 `app/services/kpi_history.py` 添加版本读取、候选分组和最新任务选择函数。
- [x] T006 [US2] 在 `app/services/kpi_history.py` 添加按当前/基线任务流式读取同维度点位、均值摘要和降级原因函数。

## 阶段 3：用户故事 1 - 选择同设备历史版本（P1）

**目标**：用户能看到同设备候选版本并选择不同版本。

**独立测试**：用同设备不同版本 fixture 调用候选接口，确认版本分组、最新任务、当前任务排除和版本未知展示。

### 测试

- [x] T007 [P] [US1] 在 `tests/test_kpi_device_version_compare.py` 中先编写候选服务测试：同设备过滤、同版本最新任务、不同设备不进入候选、版本未知保留为候选。
- [x] T008 [P] [US1] 在 `tests/test_kpi_version_compare_api.py` 中先编写候选 API 契约测试。

### 实现

- [x] T009 [US1] 在 `app/services/kpi_history.py` 实现 `get_version_candidates`。
- [x] T010 [US1] 在 `app/api/router.py` 实现 version-candidates 接口。
- [x] T011 [US1] 运行候选相关测试并确认通过。

**检查点**：同设备版本候选独立可用。

## 阶段 4：用户故事 2 - 展示不同版本曲线（P1）

**目标**：用户选择基线任务后能看到两条独立曲线和涨跌摘要。

**独立测试**：用两个同设备不同版本任务调用对比接口，确认点位、摘要、版本和任务来源。

### 测试

- [x] T012 [P] [US2] 在 `tests/test_kpi_device_version_compare.py` 中先编写对比服务测试：维度一致匹配、均值摘要、独立曲线、同版本拒绝、版本未知明确展示。
- [x] T013 [P] [US2] 在 `tests/test_kpi_device_version_compare.py` 中先编写失败边界测试：设备缺失、当前/基线索引缺失、维度不匹配、任务不存在。
- [x] T014 [P] [US2] 在 `tests/test_kpi_version_compare_api.py` 中先编写对比 API 契约测试和 404/422 测试。

### 实现

- [x] T015 [US2] 在 `app/services/kpi_history.py` 实现 `get_version_compare` 和稳定 `reason_code`。
- [x] T016 [US2] 在 `app/api/router.py` 实现 version-compare 接口。
- [x] T017 [US2] 运行对比相关测试并确认通过。

**检查点**：版本对比服务与 API 独立可用。

## 阶段 5：用户故事 3 - 前端版本对比入口（P1/P2）

**目标**：趋势弹窗中可加载候选、选择基线并展示两条曲线和摘要。

**独立测试**：Vitest 覆盖候选 label、摘要解释、图表 option；关键交互有组件/E2E验证。

### 测试

- [x] T018 [P] [US3] 在 `web/src/utils/measurementVersionCompare.test.ts` 先编写工具测试：版本未知 label、平均摘要方向解释、两条曲线 option。
- [x] T019 [P] [US3] 在现有前端测试中补充加载候选、选择基线、错误提示的关键交互测试；如现有架构无组件测试基建，则在 quickstart 记录可重复演示路径并执行 npm build。

### 实现

- [x] T020 [US3] 在 `web/src/utils/measurementHistory.ts` 或新增 `measurementVersionCompare.ts` 实现候选展示、摘要和图表工具。
- [x] T021 [US3] 在 `web/src/components/MeasurementTrendChart.tsx` 增加版本对比模式、候选选择、任务来源、摘要和失败提示。
- [x] T022 [US3] 运行 `cd web && npm test -- --run && npm run build`。

**检查点**：前端入口到曲线、摘要和降级提示完整可用。

## 阶段 6：收尾与横切关注点

- [x] T023 [P] [收尾] 检查 `docs/api/openapi.yaml` 与实现一致；如契约工具生成文件有变更，一并提交。
- [x] T024 [收尾] 运行 `.venv/bin/python build.py lint`、`.venv/bin/python build.py test` 和前端测试/build。
- [x] T025 [收尾] 按 quickstart.md 执行展示效果验证，并在任务说明中记录结果。

## 依赖与执行顺序

- T001/T002 是所有实现的前置。
- 基础模型 T004 阻塞服务测试和实现。
- US1 候选能力可先于 US2 完成。
- US2 服务/API 阻塞前端对比入口。
- 收尾依赖全部功能任务完成。

## 并行机会

- T003、T004、T007/T008、T012-T014、T018/T019 分别操作不同文件时可并行。
- 契约生成后再启动 API 客户端相关前端任务。

## 实施记录

- 展示效果验证通过：E2E 通过种子任务选择基线版本 `V1`，确认当前版本 `V2`、基线任务、完成时间、均值上涨摘要和趋势图渲染。
- 后端：契约一致，lint 通过，pytest 499 passed。
- 前端：Vitest 44 passed，production build 通过，指定 E2E 1 passed。
