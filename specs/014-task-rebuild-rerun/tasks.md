---
description: "任务重建重跑实现任务列表"
---

# 任务：任务重建重跑

**输入**：来自 `specs/014-task-rebuild-rerun/` 的规格与设计产物

**前置条件**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/rebuild-api.yaml`、`quickstart.md` 已就绪

**测试**：包含测试任务；契约变更必须先更新 `docs/api/openapi.yaml`，再同步 Pydantic、API、生成客户端和前端。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事
- 描述中包含精确的文件路径

## 路径约定

- 后端代码位于 `app/`
- 前端代码位于 `web/src/`
- 后端测试位于 `tests/`
- 契约源文件是 `docs/api/openapi.yaml`

---

## 阶段 1：契约与基础模型

**目的**：先固化 API、请求模型和错误语义，防止实现漂移。

- [X] T001 [Contract] 在 `docs/api/openapi.yaml` 中新增 `POST /api/v2/tasks/{task_id}/rebuild`；按 `specs/014-task-rebuild-rerun/contracts/rebuild-api.yaml` 定义 `RebuildModeV2`、`RebuildRequestV2`、`202 + Location`、`400`、`404`、`409` 响应，以及 `invalid_rebuild_request`、`task_busy`、`package_missing`、`kpi_snapshot_invalid` 错误码；不得修改既有普通 rerun 契约。
- [X] T002 [P] 在 `app/models/schemas.py` 中新增 `RebuildMode` 与 `RebuildRequest`：`mode` 支持 `full` / `incremental`，`confirmed` 必须为 `true`，`trigger_source` 默认 `ui` 且只允许 `ui` / `api`；增量必须携带去重非空 `rule_codes`，全量必须禁止 `rule_codes`。
- [X] T003 [P] 在 `tests/test_task_rebuild.py` 中覆盖 `RebuildRequest` 合法请求、`confirmed` 非真拒绝、增量规则去重/非空、全量携带规则拒绝和非法 `trigger_source`。

**检查点**：OpenAPI、Pydantic 模型与增量契约一致，实现前可执行 `python build.py contract`。

---

## 阶段 2：共享服务与安全预检

**目的**：提供重建入口的状态、包、规则和快照保护，避免无效请求破坏任务现场。

- [X] T004 在 `app/services/tasks.py` 中新增 `rebuild` 预检与入队能力：任务存在、状态允许 `completed` / `failed`、不在活跃执行或删除取消集合、原始上传包存在可读且非空；增量规则必须为已注册普通规则并拒绝 `pkg.extract.*` 等隐藏规则；增量重建还必须校验既有任务 KPI 快照存在且可解析，否则拒绝；预检失败不得修改 `output/<task_id>`。
- [X] T005 在 `app/services/tasks.py` 的执行分支中接入重建任务：记录 `operation=rebuild`、`mode`、`rule_codes`、`trigger_source` 和开始/成功/失败结构化日志；保持任务完成或失败状态由 `TaskService` 统一更新。
- [X] T006 [P] 在 `tests/test_task_rebuild.py` 中覆盖任务忙、任务不存在、原始包缺失、隐藏规则、未知规则和增量 KPI 快照缺失/损坏的前置拒绝；断言失败请求前后任务输出 checksum 不变。

**检查点**：无效重建请求永远不会删除历史输出，也不进入执行阶段。

---

## 阶段 3：用户故事 1 - 全量重建重跑（P1）

**目标**：对历史任务强制重建解压现场，按当前有效配置重算全部普通规则。

**独立测试**：对已完成任务发起全量重建，验证解压现场、全部规则结果、摘要、报告和 KPI 快照重建；原始包字节不变；普通 rerun 行为不变。

### 用户故事 1 的测试

- [X] T007 [US1] 在 `tests/test_task_rebuild.py` 中先编写全量重建成功测试：调用服务/API 辅助发起 `mode=full`，验证 `output/<task_id>` 重建、全部普通规则重跑、KPI 快照按当前配置生成、任务状态和报告更新。
- [X] T008 [P] [US1] 在 `tests/test_task_rebuild.py` 中补充保护测试：历史解压现场缺失/损坏仍可全量重建；重建前后原始上传包 checksum 不变；全量请求不会写入 `uploads/`。

### 用户故事 1 的实现

- [X] T009 [US1] 在 `app/services/tasks.py` 与 `app/cli.py` 中实现全量重建执行：预检通过后删除并重建 `output/<task_id>`，不删除原始包；调用共享 `run_task` 完成安全解压、全部规则私有 prepare、普通规则执行、摘要和报告重建。
- [X] T010 [US1] 在 `app/services/kpi_catalog.py` 或现有加载路径中保证全量重建生成新任务 KPI 快照，不沿用旧快照；失败时记录失败原因且任务不得呈现完成。
- [X] T011 [US1] 在 `app/api/router.py` 中实现 `rebuild_task_v2`，调用服务预检与入队，返回 `202 + Location: /api/v2/tasks/{task_id}`，并把服务错误映射为统一错误码。

**检查点**：全量重建可独立完成，旧现场、旧快照和历史输出不会残留为当前结果；普通 rerun 回归保持通过。

---

## 阶段 4：用户故事 2 - 增量重建重跑（P2）

**目标**：强制重建解压现场后只执行指定普通规则及其私有 prepare，并保留其他历史结果与快照。

**独立测试**：选择有效普通规则发起增量重建，验证解压现场重建、目标规则及私有 prepare 更新、未选规则和 KPI 快照保留、摘要和报告重新汇总。

### 用户故事 2 的测试

- [X] T012 [US2] 在 `tests/test_task_rebuild.py` 中先编写增量重建成功测试：单规则和多规则请求均重建解压现场，只覆盖目标规则结果，未选规则结果保持不变，KPI 快照内容不变。
- [X] T013 [P] [US2] 在 `tests/test_task_rebuild.py` 中补充增量失败保护：目标规则私有 prepare 或规则失败时任务呈现失败，输出不会被误标完成；目标 KPI 规则在快照缺失/损坏时执行前拒绝。

### 用户故事 2 的实现

- [X] T014 [US2] 在 `app/services/executor.py` 与 `app/cli.py` 中增增强制重建解压现场的单规则执行路径：先备份任务 KPI 快照，删除 manifest 与工作分类目录，从原始包重新解压，然后恢复快照并执行目标规则私有 prepare 和目标普通规则。
- [X] T015 [US2] 在 `app/services/tasks.py` 中实现增量重建结果汇总：保留未选规则结果与 `prepared/<owner_code>/`，重新生成任务摘要、系统结果、`task.json` 和报告；失败状态语义与全量重建一致。
- [X] T016 [US2] 在 `app/cli.py` 中提供与在线 API 相同的重建服务调用或共享函数，确保本地 CLI、API 双模式行为一致。

**检查点**：增量重建可独立完成，且不隐式刷新未选规则或既有 KPI 快照。

---

## 阶段 5：用户故事 3 - 界面确认与操作入口（P1）

**目标**：为全量与增量重建提供明确入口、破坏性确认和状态反馈。

**独立测试**：在任务列表发起全量重建，在任务详情选择规则发起增量重建；确认提示、请求体和刷新行为符合契约。

- [X] T017 [Contract] 运行 `python build.py contract` 和 `python build.py gen-web-api`，更新 `web/src/api/client.ts` 及相关生成类型；禁止手写与 OpenAPI 不一致客户端。
- [X] T018 [US3] 在 `web/src/api/http.ts` 中新增类型化 `rebuildTask` 调用，支持 `full` / `incremental`、确认字段、触发来源和规则列表；统一处理 400 / 404 / 409 错误。
- [X] T019 [US3] 在 `web/src/pages/TaskListPage.tsx` 中新增“全量重建”入口：展示破坏性确认，说明历史输出会重建；请求 `mode=full`、`confirmed=true`，提交后提供任务状态反馈。
- [X] T020 [US3] 在 `web/src/pages/TaskDetailPage.tsx` 中新增“增量重建”入口：只允许选择普通规则，提交 `mode=incremental`、去重非空 `rule_codes` 和 `confirmed=true`；执行中禁用重复提交并轮询或刷新任务摘要。
- [X] T021 [P] [US3] 在 `web/src` 相关测试或组件测试中覆盖破坏性确认、请求负载、增量规则选择和错误提示；如项目无既有组件测试，至少通过构建与类型检查验证。

**检查点**：界面不会把重建入口混入普通重跑，用户必须显式确认破坏性动作。

---

## 阶段 6：回归、文档与交付门禁

**目的**：保证普通重跑不受影响，文档与实现一致，质量门禁全部通过。

- [X] T022 [P] 在 `tests/test_task_rebuild.py` 中补普通 rerun 回归：普通重跑仍复用有效解压现场和有效 KPI 快照，不清理输出、不刷新快照。
- [X] T023 [P] 更新 `docs/architecture.md`、`docs/data-model.md`、`docs/design/task-rerun.md` 和 `docs/roadmap.md`：区分普通重跑、全量重建和增量重建；记录 KPI 快照刷新/保留、强制解压、保护语义和日志字段。
- [X] T024 运行 `python build.py contract` 与 `python build.py gen-web-api`，确认 OpenAPI、Pydantic 和前端生成客户端无漂移。
- [X] T025 运行 `python build.py lint` 和 `python build.py test`，修复所有失败。
- [X] T026 运行 `python build.py verify`，确认本地全流程中安全解压、KPI 快照、规则结果、摘要、报告与重建语义一致。
- [X] T027 运行 `cd web && npm run build`，确认前端类型、生成客户端和界面代码可构建。
- [X] T028 按 `specs/014-task-rebuild-rerun/quickstart.md` 执行最终验证：验证全量重建、增量重建、原始包保护、普通 rerun 行为和错误拒绝场景。

---

## 依赖与执行顺序

### 阶段依赖

1. 阶段 1 契约与模型完成后进入阶段 2。
2. 阶段 2 预检阻塞所有用户故事。
3. 用户故事按 US1 → US2 → US3 执行。
4. 阶段 6 依赖全部用户故事完成。

### 用户故事内部依赖

- **US1**：T007/T008 测试先于 T009/T010；T009/T010 完成后实现 T011。
- **US2**：T012/T013 测试先于 T014/T015；T016 依赖服务实现。
- **US3**：T017 依赖 OpenAPI 与 Pydantic 稳定；T018 依赖生成客户端；T019/T020 依赖 T018；T021 覆盖界面实现。

### 并行机会

- T002/T003 可并行编写，但契约 T001 先完成。
- T006 属于服务预检测试，可与部分实现准备并行。
- T008、T013、T021 和文档任务分别位于不同测试/文档边界，可并行。
- T023/T024 之后可运行 T025/T026/T027 门禁；若相互改动，需重新执行受影响门禁。

## 实现策略

### MVP 优先

1. 完成契约与预检。
2. 完成全量重建并独立验证。
3. 完成增量重建，保持普通重跑回归通过。
4. 最后接入界面并执行完整门禁。

### 完成标准

- 全部任务复选框为 `[X]`。
- `spec.md`、`plan.md`、`tasks.md` 无未解决矛盾。
- OpenAPI、Pydantic、前端生成客户端一致。
- 全量与增量重建均不复用历史解压数据。
- 全量刷新 KPI 快照；增量保留快照。
- 原始上传包字节不变。
- 普通重跑行为不变。
- `lint`、`test`、`contract`、`gen-web-api`、`verify` 和前端构建全部通过。
