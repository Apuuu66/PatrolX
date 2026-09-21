---
description: "界面新增动态派生指标实现任务列表"
---

# 任务：界面新增动态派生指标

**输入**：来自 `/specs/016-ui-derived-metrics/` 的设计文档

**前置条件**：plan.md（必须）、spec.md（用户故事必须）、research.md、data-model.md、contracts/openapi-contract.md、quickstart.md

**测试**：项目质量门禁要求测试；以下任务按 TDD 执行，先确认失败再实现。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事（US1、US2、US3）

## 阶段 1：设置（共享基础设施）

**目的**：先固化 API 契约和生成客户端，避免实现漂移。

- [ ] T001 在 `docs/api/openapi.yaml` 新增 `/api/v4/kpi/config/derived-metrics` 相关 paths、`KpiDerivedMetric*V4` schemas、`derived_metric` 审计类型和 snapshot schema version 3
- [ ] T002 运行 `python build.py contract` 与 `python build.py gen-web-api`，确认 `web/src/api/client.ts` 更新且无手写 API 路径

**检查点**：OpenAPI 与前端生成客户端已准备好，后续实现必须与之一致。

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：建立共享持久化、公式和快照能力。

- [ ] T003 [P] 在 `app/models/db.py` 新增 `KpiDerivedMetric` 表及 UTC 时间字段，字段约束遵循 `specs/016-ui-derived-metrics/data-model.md`
- [ ] T004 [P] 在 `app/models/schemas.py` 按新契约实现 `KpiDerivedMetric*V4`、`KpiDerivedFormula*V4` 和 `KpiTaskCatalogSnapshot` 的 `derived_metrics` 兼容字段
- [ ] T005 在 `app/inspectors/kpi/catalog.py` 扩展受控公式模型：`ratio` 保持现有行为，`inverse_ratio` 表示 `(1 - 分子 / 分母) × scale`，并扩展配置/快照校验
- [ ] T006 在 `app/inspectors/kpi/common.py` 为 `inverse_ratio` 实现先聚合输入再计算的逻辑，并保留缺失输入、分母为零、输入溯源和公式类型
- [ ] T007 在 `app/services/kpi_catalog.py` 将启用派生指标写入新任务快照 schema 3，并在读取旧/新快照时注入对应业务域；历史快照文件不重写

**检查点**：不含界面和 CRUD 的前提下，给定派生配置可以进入新任务并正确计算。

---

## 阶段 3：用户故事 1 - 在界面创建派生指标（优先级：P1）🎯 MVP

**目标**：授权用户能在配置中心选择同业务域 raw 指标，创建正向或反向比率派生指标，并让新任务展示结果。

**独立测试**：管理员创建 `ratio` 或 `inverse_ratio` 指标后，新任务详情出现按公式计算的值、单位、状态和输入来源；普通用户无写操作入口。

### 用户故事 1 的测试

- [ ] T008 [P] [US1] 在 `tests/test_kpi_config_derived_metrics.py` 编写创建、列表、详情和权限失败测试，覆盖正向/反向比率保存成功
- [ ] T009 [P] [US1] 在 `tests/test_kpi_single_rule.py` 增加新任务正向/反向派生指标计算测试，覆盖单位、状态、输入来源和反向公式

### 用户故事 1 的实现

- [ ] T010 [US1] 在 `app/services/kpi_config.py` 实现 `create_derived_metric`、分页 `list_derived_metrics` 和 `get_derived_metric`，写入修订与审计
- [ ] T011 [US1] 在 `app/api/router.py` 按契约挂载派生指标 `GET list/detail` 和 `POST` 路由，操作人取 `AuthSession.username`
- [ ] T012 [US1] 在 `web/src/components/KpiDerivedMetricEditor.tsx` 实现列表和新增表单，分子/分母只提供同业务域 raw 指标，公式类型支持正向/反向
- [ ] T013 [US1] 在 `web/src/pages/KpiResourcesPage.tsx` 挂载“派生指标”配置入口；无管理员权限时不显示写操作
- [ ] T014 [US1] 在 `web/src/components/kpiMetricCatalogModel.ts` 和测试中支持格式化 `inverse_ratio` 公式展示

**检查点**：MVP 可通过界面创建派生指标，并用新任务验证结果。

---

## 阶段 4：用户故事 2 - 在界面维护已有派生指标（优先级：P2）

**目标**：授权用户能查看、编辑、启停和删除未被引用的派生指标；历史任务不变。

**独立测试**：修改公式/scale 或停用指标后，已有任务结果不变，新任务使用新口径；删除被引用指标被拒绝，未引用指标删除成功。

### 用户故事 2 的测试

- [ ] T015 [P] [US2] 在 `tests/test_kpi_config_derived_metrics.py` 编写编辑、启停、删除成功和引用保护测试，覆盖审计前后内容
- [ ] T016 [P] [US2] 在 `tests/test_kpi_task_snapshot.py` 增加配置变更后历史快照不可变、新快照使用新口径/停用后排除的测试

### 用户故事 2 的实现

- [ ] T017 [US2] 在 `app/services/kpi_config.py` 实现 `update_derived_metric` 和 `delete_derived_metric`，原子保存、递增修订、审计并检查阈值/容量/展示引用
- [ ] T018 [US2] 在 `app/api/router.py` 按契约挂载派生指标 `PUT` 和 `DELETE` 路由并转换业务错误
- [ ] T019 [US2] 在 `web/src/components/KpiDerivedMetricEditor.tsx` 增加编辑、启停、删除、确认提示和失败原因展示
- [ ] T020 [US2] 在 `web/src/pages/KpiResourcesPage.tsx` 将配置审计类型透传给现有审计表，使 `derived_metric` 操作可见

**检查点**：配置维护闭环完成，历史任务不可变。

---

## 阶段 5：用户故事 3 - 配置错误得到即时阻断（优先级：P2）

**目标**：所有非法配置在保存前被阻断，错误原因可理解且不产生部分生效配置。

**独立测试**：分别提交缺少输入、未知/未分类/跨域/派生输入、重复 key、非法 scale、回退输入重复和循环风险请求；全部被 400/409 阻断且数据库无变更。

### 用户故事 3 的测试

- [ ] T021 [P] [US3] 在 `tests/test_kpi_config_derived_metrics.py` 编写参数化校验失败测试，覆盖 `data-model.md` 全部校验规则和审计不写入
- [ ] T022 [P] [US3] 在 `web/src/components/KpiDerivedMetricEditor.test.ts` 编代表单校验和错误提示测试

### 用户故事 3 的实现

- [ ] T023 [US3] 在 `app/services/kpi_config.py` 实现统一校验与稳定错误码：key 冲突、输入未知、未分类、跨业务域、公式非法、回退重复和分母保护
- [ ] T024 [US3] 在 `app/api/router.py` 确保校验错误转换为统一 `ErrorV2` 状态码与中文消息，不泄露堆栈

**检查点**：错误配置无法进入数据库或任务快照。

---

## 阶段 6：收尾与横切关注点

**目的**：保证契约、同构、报告和质量门禁完整。

- [ ] T025 检查任务详情、指标目录、HTML 报告和导出对在线派生指标复用同一结果结构；必要时在 `app/reports/templates/report.html.j2` 调整展示但不新增第二套口径
- [ ] T026 在 `docs/architecture.md` 或 `docs/design/mechanisms.md` 补充在线派生指标快照语义；不复制 OpenAPI 完整字段
- [ ] T027 运行 `python build.py lint`、`python build.py test`、`python build.py verify`、`python build.py contract`、`python build.py gen-web-api` 和 `cd web && npm run build`
- [ ] T028 执行 `specs/016-ui-derived-metrics/quickstart.md` 的四个验证场景并记录结果

---

## 依赖与执行顺序

### 阶段依赖

- 设置（阶段 1）最先执行，契约先行。
- 基础层（阶段 2）依赖契约模型，但不得修改业务路由。
- US1 依赖阶段 2；US2 依赖 US1 的服务和界面；US3 可在服务实现过程中并行开发，但必须在 MVP 验证前完成。
- 收尾依赖所有用户故事完成。

### 用户故事依赖

- **US1**：基础层完成后可独立交付 MVP。
- **US2**：依赖 US1 的创建/查询数据；可独立验证维护闭环。
- **US3**：与 US1/US2 服务共享校验实现；最终必须覆盖所有错误场景。

### 并行机会

- T003、T004 可并行。
- T008、T009 以及 T015、T016、T021、T022 的测试文件互不冲突，可并行先写。
- 前端编辑器与后端服务在契约冻结后可由不同执行者并行推进。

## 实现策略

### MVP 优先

1. 完成阶段 1、2。
2. 完成 US1 后运行 `python build.py verify`，验证新任务正向/反向公式。
3. 完成 US2 和 US3 后再做收尾。

### 质量门禁

- 每个用户故事内部先写失败测试，再实现。
- 涉及契约时必须同步 OpenAPI、Pydantic、生成客户端和测试。
- 最终必须通过 `python build.py lint` 和 `python build.py test`；涉及全流程时必须通过 `python build.py verify`。
