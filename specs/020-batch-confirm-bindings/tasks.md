# 任务：指标绑定批量确认

**输入**：来自 `/specs/020-batch-confirm-bindings/` 的设计文档

**前置条件**：plan.md（必须）、spec.md（用户故事必须）、research.md、data-model.md、contracts/

## 阶段 1：契约与测试基线

- [ ] T001 [P] 在 `docs/api/openapi.yaml` 中新增批量确认路径和 `KpiMeasurementBindingBatchConfirmRequest`、`KpiMeasurementBindingConfirmResult`、`KpiMeasurementBindingBatchConfirmResponse` Schema，约束 `binding_ids` 非空且最多 200 项
- [ ] T002 [P] 在 `tests/test_kpi_measurement_binding.py` 中先编写批量确认服务测试，覆盖批量成功、幂等确认、去重、未选中不变和更新时间不回写
- [ ] T003 [P] 在 `tests/test_kpi_measurement_api.py` 中先编写接口测试，覆盖 admin 成功响应、部分失败逐项原因、请求体为空和权限拒绝

## 阶段 2：用户故事 1 - 批量确认候选绑定

**目标**：已关联 ME 指标的候选绑定可在一次请求中全部确认。

**独立测试**：提交多条候选绑定 ID 后，目标绑定状态全部变为 `confirmed`，未选中绑定保持不变。

### 实现

- [ ] T004 [US1] 在 `app/models/schemas.py` 中新增批量确认请求、结果和响应模型，字段与 OpenAPI 契约一致
- [ ] T005 [US1] 在 `app/services/kpi_measurement_units.py` 中实现去重、候选校验、状态更新、幂等返回和 UTC `updated_at` 维护
- [ ] T006 [US1] 在 `app/api/router.py` 中新增 `POST /api/v5/kpi/measurement-bindings/batch-confirm`，使用 admin 权限并映射统一业务错误
- [ ] T007 [US1] 在 `web/src/api/http.ts` 中接入生成的批量确认契约方法

**检查点**：API 批量确认闭环可用，后端测试通过。

## 阶段 3：用户故事 2 - 明确处理不可确认项

**目标**：批量结果能区分成功、幂等成功和失败，失败原因可定位。

**独立测试**：混合选择缺少指标、不存在、冲突和忽略绑定时，成功项确认，失败项保持原状态并返回原因。

### 实现

- [ ] T008 [US2] 在批量确认服务中补充缺少指标、不存在、状态不可确认和状态冲突的错误码与消息
- [ ] T009 [US2] 在 `web/src/pages/MeasurementUnitsPage.tsx` 中展示批量结果摘要，失败时使用警告提示并显示失败原因
- [ ] T010 [US2] 在后端测试中补充混合成功/失败场景，验证失败项数据和未选中绑定不变

**检查点**：部分失败行为可观察、可解释、可定位。

## 阶段 4：用户故事 3 - 保持绑定冲突保护

**目标**：批量确认不产生跨测量单元的同 ME 指标冲突。

**独立测试**：同指标跨单元候选和已有确认绑定场景下，相关候选失败且数据不变。

### 实现

- [ ] T011 [US3] 在批量确认服务中实现请求内候选按 ME 指标/测量单元聚合，以及与数据库已有确认绑定的冲突判断
- [ ] T012 [US3] 在后端测试中覆盖请求内跨单元、请求外已确认跨单元和同单元重复指标场景

**检查点**：冲突场景与现有单条确认语义一致且结果顺序无关。

## 阶段 5：前端多选交互

**目标**：维护人员可在绑定关系表格中多选并触发批量确认。

**独立测试**：选择多条绑定后提交，界面显示结果并刷新列表。

### 实现

- [ ] T013 [US1] 在 `web/src/pages/MeasurementUnitsPage.tsx` 的绑定关系表格中增加 row selection、批量确认按钮、禁用态和提交中状态
- [ ] T014 [US1] 提交成功后刷新当前页、清理选中项，并根据响应展示成功、幂等和失败数量

**检查点**：前端交互完整并保持桌面端现有风格。

## 阶段 6：收尾与验证

- [ ] T015 [P] 检查 `specs/020-batch-confirm-bindings/quickstart.md` 与实际 API 字段一致，必要时修正文档
- [ ] T016 运行 `python build.py contract` 和 `python build.py gen-web-api`，确认 OpenAPI、Pydantic 和前端客户端一致
- [ ] T017 运行 `python build.py lint` 和 `python build.py test`
- [ ] T018 运行 `cd web && npm run build`
- [ ] T019 运行 `python build.py verify`
- [ ] T020 对照 spec 的 FR-001 到 FR-012 做完成审计并更新 `tasks.md` 复选框

## 依赖与执行顺序

- T001-T003 可并行；契约与测试先于实现。
- T004 → T005 → T006 → T007。
- T008/T009/T010 依赖批量确认基础实现。
- T011/T012 依赖 T005。
- T013/T014 依赖 T007 和 T009 的响应语义。
- 阶段 6 依赖全部用户故事完成。

## 并行机会

- 契约和两类后端测试初稿可并行。
- 前端结果展示与多选交互最终需顺序合并到同一文件。
- 文档检查可与代码验证并行。

## MVP 范围

阶段 1 + 阶段 2 可完成“批量确认候选绑定”的核心 API 闭环；失败可观察和冲突保护是完整交付要求。
