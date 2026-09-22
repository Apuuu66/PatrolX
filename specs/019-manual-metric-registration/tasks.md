---
description: "人工注册指标实现任务列表"
---

# 任务：人工注册指标

**输入**：来自 `/specs/019-manual-metric-registration/` 的设计文档

## 阶段 1：设置

- [ ] T001 在实现 worktree 中确认 `git worktree list`、`git branch --show-current` 和 Speckit 产物已提交到 `main`
- [ ] T002 [P] 在 `app/services/kpi_measurement_units.py` 增加人工指标 ID 生成函数，固定 `ME__MANUAL_` 前缀并保证 ASCII、下划线和 128 字符约束

**检查点**：实现分支与 worktree 就绪，ID 生成规则可独立测试。

## 阶段 2：用户故事 1 - 从绑定现场注册未注册指标 [US1]

**目标**：维护人员可在未注册绑定上补录 ME 指标并保持绑定候选。

**独立测试**：创建空指标绑定，调用注册接口或界面提交后，绑定关联新 ME 资源且状态仍为 `candidate`。

### 测试

- [ ] T003 [P] [US1] 在 `tests/test_kpi_measurement_resources.py` 中先添加 ID 生成与人工资源创建测试，验证空英文名、长英文名、唯一后缀和长度限制
- [ ] T004 [P] [US1] 在 `tests/test_kpi_measurement_api.py` 中先添加注册接口测试，验证空绑定关联成功、状态保持候选、非候选/已关联绑定拒绝

### 实现

- [ ] T005 [US1] 在 `app/services/kpi_measurement_units.py` 实现绑定现场注册服务：校验候选空绑定、创建 `kind=me` 的人工资源并只更新当前绑定 `metric_resource_id`
- [ ] T006 [US1] 在 `app/models/schemas.py` 增加 `KpiMeasurementMetricRegisterRequest` 与资源/绑定响应所需 Pydantic Schema
- [ ] T007 [US1] 先更新 `docs/api/openapi.yaml`，新增 `POST /api/v5/kpi/measurement-bindings/{binding_id}/register-metric` 契约
- [ ] T008 [US1] 在 `app/api/router.py` 实现注册端点，使用 admin 权限并映射 `KpiMeasurementError`
- [ ] T009 [US1] 更新 `web/src/api/http.ts` 与生成客户端所需的调用层，接入绑定注册接口
- [ ] T010 [US1] 在 `web/src/pages/MeasurementUnitsPage.tsx` 为空指标候选绑定增加注册表单，预填基础列名和展示单位，提交后刷新绑定列表

**检查点**：API 与界面均可从未注册绑定完成注册，绑定仍未确认。

## 阶段 3：用户故事 2 - 标识人工注册指标 [US2]

**目标**：人工注册指标在 ID 和界面上可识别。

**独立测试**：注册成功后资源 ID 以 `ME__MANUAL_` 开头，界面显示“人工注册”标识。

### 测试

- [ ] T011 [P] [US2] 在 `tests/test_kpi_measurement_api.py` 中验证注册返回的绑定 `metric_resource_id` 带人工前缀
- [ ] T012 [US2] 在 `web/src/pages/MeasurementUnitsPage.tsx` 对 `ME__MANUAL_` 前缀指标渲染“人工注册”标签

**检查点**：接口数据与界面展示均可区分人工指标。

## 阶段 4：用户故事 3 - 维护人工注册指标 [US3]

**目标**：人工指标中文名、英文名、启用状态可维护，其他字段不变。

**独立测试**：编辑人工指标成功后 ID、绑定来源、状态不变；编辑 CSV 导入指标被拒绝。

### 测试

- [ ] T013 [P] [US3] 在 `tests/test_kpi_measurement_resources.py` 中先添加编辑服务测试：人工指标可更新三个字段，非人工指标拒绝，中文名冲突拒绝
- [ ] T014 [P] [US3] 在 `tests/test_kpi_measurement_api.py` 中先添加编辑接口测试：字段级更新、404、非人工资源和冲突错误

### 实现

- [ ] T015 [US3] 在 `app/services/kpi_measurement_units.py` 实现人工指标编辑服务，仅更新 `name_zh`、`name_en`、`enabled`
- [ ] T016 [US3] 在 `app/models/schemas.py` 增加 `KpiMeasurementResourceUpdateRequest` 和资源响应 Schema
- [ ] T017 [US3] 先更新 `docs/api/openapi.yaml`，新增 `PATCH /api/v5/kpi/measurement-resources/{resource_id}` 契约
- [ ] T018 [US3] 在 `app/api/router.py` 实现编辑端点，使用 admin 权限并映射业务错误
- [ ] T019 [US3] 更新 `web/src/api/http.ts` 与生成客户端所需的调用层，接入人工指标编辑接口
- [ ] T020 [US3] 在 `web/src/pages/MeasurementUnitsPage.tsx` 为人工指标提供编辑弹窗，仅展示可编辑字段并显示不可变 ID

**检查点**：人工指标维护闭环可用，CSV 导入资源不受影响。

## 阶段 5：用户故事 4 - 防止重复和脏数据 [US4]

**目标**：重复中文名不产生重复资源，已有资源可绑定，其他绑定不被批量修改。

**独立测试**：同名注册返回冲突；选择既有 ME 资源后当前绑定关联成功且其他绑定不变。

### 测试

- [ ] T021 [P] [US4] 在 `tests/test_kpi_measurement_resources.py` 中先添加同名冲突与改绑既有 ME 资源测试，验证不创建重复资源和不影响其他绑定
- [ ] T022 [P] [US4] 在 `tests/test_kpi_measurement_api.py` 中先添加同名冲突、选择非 ME 资源和不存在资源的接口错误测试

### 实现

- [ ] T023 [US4] 在 `app/services/kpi_measurement_units.py` 注册服务中实现同类 ME 中文名冲突检测、绑定既有资源分支和事务边界
- [ ] T024 [US4] 先在 `app/models/schemas.py` 和 `docs/api/openapi.yaml` 中新增 `GET /api/v5/kpi/measurement-resources` 契约，并补充 `bind_existing_resource_id` 校验
- [ ] T025 [US4] 在 `app/services/kpi_measurement_units.py` 实现全局 ME 资源分页查询，支持 `kind`、搜索、启用过滤和默认每页 10 条
- [ ] T026 [US4] 在 `app/api/router.py` 实现 ME 资源查询端点，使用 admin 权限并保持契约优先
- [ ] T027 [US4] 在 `web/src/api/http.ts` 中接入资源查询，并在 `web/src/pages/MeasurementUnitsPage.tsx` 处理同名冲突提示和既有 ME 资源选择器

**检查点**：重复与误绑场景均有明确错误或受控改绑路径。

## 阶段 6：收尾与验证

- [ ] T028 [P] 检查 `specs/019-manual-metric-registration/quickstart.md` 与实际 API 字段一致，必要时修正文档
- [ ] T029 运行 `python build.py contract` 和 `python build.py gen-web-api`，确认 OpenAPI、Pydantic 和前端客户端一致
- [ ] T030 运行 `python build.py lint` 和 `python build.py test`
- [ ] T031 运行 `python build.py verify`
- [ ] T032 对照 spec 的 FR-001 到 FR-012 做完成审计并更新 `tasks.md` 复选框

## 依赖与执行顺序

- T001 → T002 → 阶段 2。
- US1 先完成服务、契约、API、前端。
- US2 依赖 US1 的注册结果。
- US3 依赖 T002 的人工 ID 语义。
- US4 依赖 US1 的注册服务。
- 阶段 6 依赖全部用户故事完成。

## 并行机会

- T003、T004 可并行。
- T011、T013、T014、T021、T022 可在对应服务实现前并行设计。
- 文档检查 T028 与代码验证 T029-T031 无相互写入冲突时可并行。

## MVP 范围

阶段 1 + 阶段 2 已可完成“从现场注册未注册指标”的核心价值；标识、编辑和防重复是完整交付要求。
