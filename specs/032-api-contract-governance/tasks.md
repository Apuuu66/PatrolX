---
description: "功能实现任务列表：API 契约治理与持续集成门禁（批次 A）"
---

# 任务：API 契约治理与持续集成门禁

**输入**：来自 `specs/032-api-contract-governance/` 的设计文档

**前置条件**：plan.md（必须）、spec.md（用户故事必须）、research.md、data-model.md、contracts/、quickstart.md

**测试**：本批次为治理改造，规格显式要求守卫以自动化测试固化（FR-011）且失败信息可定位（FR-012），因此包含测试任务并遵循先红后绿。本批次不新增业务能力，`tests/fixtures/make_real_package.py` 无需新增样例数据。

**组织方式**：任务按用户故事分组，支持独立实现与验证。实现顺序遵循 research.md：契约先行（T003）→ 路由删除（T005–T006）→ 守卫先红后绿（US2）→ 测试调用迁移（US1 后半）→ 客户端再生成 → CI → 文档与规格状态同步。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事（US1、US2、US3、US4）
- 描述中包含精确的文件路径

## 路径约定

- 单一项目：仓库根目录的 `app/`、`tests/`、`docs/`、`web/`、`.github/`
- 实现现场：`.worktrees/feature-032-api-contract-governance`（分支 `feature/032-api-contract-governance`，从 `main` 创建并复用）

---

## 阶段 1：设置（共享基础设施）

**目的**：确认实现现场与改造前基线

- [ ] T001 在实现 worktree（`.worktrees/feature-032-api-contract-governance`）执行实现前置检查：`git worktree list`、`git branch --show-current`，确认当前分支为 `feature/032-api-contract-governance` 且 Speckit 产物已提交在 `main`
- [ ] T002 运行改造前基线并记录：`python build.py lint`、`python build.py test`、`python build.py contract` 全绿；用 grep 记录契约中唯一跨版本重复能力组为 `POST /tasks`（v2+v3）

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：契约先行——OpenAPI 是唯一接口契约源，先改契约再改实现（与 T005 同批落到绿）

**⚠️ 关键**：本阶段完成前不得开始用户故事实现

- [ ] T003 更新 `docs/api/openapi.yaml`：删除 `POST /api/v2/tasks` path、`createTaskV2` operation 与 `Body_createTaskV2` schema；不动 `/api/v2` 其余路径与任何 v1/v3/v5 内容

**检查点**：契约已表达目标表面——基础就绪，用户故事实现可以开始

---

## 阶段 3：用户故事 1 - 接口入口收敛（优先级：P1）🎯 MVP

**目标**：`/api/v3/tasks` 成为唯一任务创建入口；v2 其余接口冻结；v4 空壳路由彻底消失；第一方调用方与生成客户端全部迁移

**独立测试**：`POST /api/v2/tasks` 返回 404/405；`/api/v4/**` 返回 404；v3 创建全流程可用；`python build.py contract` 通过；既有套件（迁移后）全绿；生成客户端无旧创建操作

### 用户故事 1 的测试（先写，确认失败）

- [ ] T004 [US1] 在 `tests/test_api.py` 增加 `test_v2_create_entry_removed`（`POST /api/v2/tasks` 返回 404/405）与 `test_v4_prefix_not_registered`（`/api/v4/**` 返回 404），并断言 `POST /api/v3/tasks` 路由仍存在（缺表单返回 422）；运行 `.venv/bin/python -m pytest -k "v2_create_entry_removed or v4_prefix_not_registered"` 确认为红

### 用户故事 1 的实现

- [ ] T005 [US1] 删除 `app/api/router.py` 中 `create_task_v2` 路由函数（含 Location 头与失败回收逻辑），保留 v2 列表/详情/重跑/重建/报告/日志/删除等全部路由
- [ ] T006 [US1] 删除 `app/api/router.py` 中 `v4_router` 定义，并移除 `app/main.py` 中对它的导入与 `include_router` 注册
- [ ] T007 [US1] 运行 `.venv/bin/python -m pytest -k "v2_create_entry_removed or v4_prefix_not_registered"` 与 `python build.py contract`，确认 T003 的契约与实现一致转绿
- [ ] T008 [P] [US1] 迁移 `tests/baseline_helpers.py` 的 `upload_package` 与 `tests/test_api.py` 的 `_upload` 到 `/api/v3/tasks`，在助手内默认补齐 `package_kind="inspection"`、`province`、`operator`
- [ ] T009 [P] [US1] 迁移 `tests/test_api_robustness.py` 的两个上传助手与裸 multipart 调用到 `/api/v3/tasks`，按需补默认元数据，保持文件名/空包/超长名等边界断言不变
- [ ] T010 [P] [US1] 迁移 `tests/test_baseline_pipeline.py`（3 处）与 `tests/test_baseline_upload.py`（4 处）创建调用到 `/api/v3/tasks`，保持同名同包复用与同名异包冲突语义不变
- [ ] T011 [P] [US1] 迁移 `tests/test_auth.py`、`tests/test_observability.py`、`tests/test_task_rebuild.py` 的创建调用到 `/api/v3/tasks`，同样补齐必填元数据
- [ ] T012 [US1] 全仓库检索确认第一方调用为零（`specs/` 历史记录除外）：`grep -rn '"/api/v2/tasks"' app tests web --include='*.py' --include='*.ts' --include='*.mjs'`
- [ ] T013 [US1] 客户端再生成：`python build.py gen-web-api`（等价 `cd web && npm run gen-api`），确认 `web/src/api/client.ts` 中 `createTaskV2` 消失、diff 仅由契约删除引起
- [ ] T014 [US1] 运行 `python build.py test`（迁移后 8 个测试文件全部改走 v3）确认既有套件全绿、v2 其余接口行为不变

**检查点**：US1 独立可用——入口唯一、契约/实现/客户端三者一致

---

## 阶段 4：用户故事 2 - 契约守卫自动拦截版本债务（优先级：P1）

**目标**：重复 operationId、空版本前缀、未标注的废弃入口在测试阶段被直接拦截；守卫失败信息可定位

**独立测试**：分别构造四类违规（重复 operationId、只剩空壳的版本前缀、契约变更未重新生成客户端、旧入口未标废弃/替代），守卫以可定位信息拦截；恢复后全绿

### 用户故事 2 的测试与实现

- [ ] T015 [US2] 在 `tests/test_contract.py` 增加 G-01 `test_operation_ids_unique_and_non_empty`：先以合成契约用例（重复 operationId、缺失 operationId）写下失败断言，再实现检查逻辑转绿；并对真实契约断言通过
- [ ] T016 [US2] 在 `tests/test_contract.py` 增加 G-02 `test_no_empty_version_prefix`：枚举 `app.api.router` 中 `*_router` 变量取得 prefix 集合，与契约版本前缀集合双向求差；合成用例覆盖"代码注册但契约无操作"与"契约出现但代码未注册"；对真实契约断言通过
- [ ] T017 [US2] 在 `tests/test_contract.py` 增加 G-03 `test_single_current_entry_per_capability`：按 `(method, 去版本前缀路径)` 分组，最高版本入口必须未废弃，其余必须 `deprecated: true` 且描述含替代入口路径（确无替代时须显式说明不适用）；合成用例覆盖"旧入口未标废弃"与"缺替代入口"；对真实契约断言无违规组
- [ ] T018 [US2] 校验 `tests/test_contract.py` 三条守卫的失败信息包含违规的具体路径/operationId/版本前缀（FR-012），不得只输出笼统失败
- [ ] T019 [US2] 运行 `python build.py test` 与 `python build.py contract`，确认包含三条守卫且全绿

**检查点**：US1 与 US2 均独立可用——版本债务此后由自动守卫拦截

---

## 阶段 5：用户故事 3 - 每次推送自动跑最小门禁（优先级：P2）

**目标**：推送主分支与合并请求自动执行后端与前端门禁，15 分钟内给出结论

**独立测试**：本地按 workflow 同序执行 8 条命令得到与门禁一致结论；workflow 触发条件、job 与超时符合 contracts/ci-gate.md

### 用户故事 3 的实现

- [ ] T020 [US3] 新增 `.github/workflows/ci.yml`：触发 `push: [main]` 与 `pull_request`；`backend` job（Python 3.12 → `python build.py install/lint/test/contract`）与 `frontend` job（Node 22 + npm 缓存 → `npm ci` → `npm run gen-api` + `git diff --exit-code -- src/api/client.ts` → `npm run build` → `npm test`，工作目录 `web/`）并行，均 `timeout-minutes: 15`，不含 verify 与 E2E
- [ ] T021 [US3] 用 `yaml.safe_load` 校验 `ci.yml` 可解析且触发/超时/job 结构符合契约，并按 workflow 顺序在本地复现 8 条命令记录结论

**检查点**：门禁可复现且不引入第二套检查脚本

---

## 阶段 6：用户故事 4 - 文档与规格状态反映真实现状（优先级：P3）

**目标**：015 标已被替代；016、025–028、030 状态与真实交付一致；面向当前系统的文档无未标注 v4 引用

**独立测试**：`grep -rn "/api/v4" docs/` 为空；`specs/016-ui-derived-metrics/` 内 v4 字样全部带历史/已替代标注；相关规格状态行与交付一致

### 用户故事 4 的实现

- [ ] T022 [P] [US4] 更新 `specs/015-kpi-dynamic-config/spec.md` 状态为"已被替代"并注明替代实现（测量单元 KPI 重构，现行 `/api/v5/kpi/measurement-*`）；在 `specs/015-kpi-dynamic-config/contracts/kpi-dynamic-config.yaml` 顶部加历史设计注释，声明其 plan/tasks/contracts 均为历史产物、不得作为现行指引（FR-013）
- [ ] T023 [P] [US4] 更新 `specs/016-ui-derived-metrics/spec.md` 状态为"已实现"；在 `spec.md`、`research.md`、`tasks.md`、`contracts/openapi-contract.md` 中把 v4 引用标注为"历史设计，现行入口 `/api/v5/kpi/measurement-derived`"，保留历史脉络
- [ ] T024 [P] [US4] 将 `specs/025-kpi-cross-task-trend/spec.md`、`specs/026-kpi-device-version-compare/spec.md`、`specs/027-site-device-ledger/spec.md`、`specs/028-ledger-crud/spec.md`、`specs/030-alarm-flapping/spec.md` 状态改为"已实现"
- [ ] T025 [P] [US4] 改写 `docs/roadmap.md` M6 条目：删去 v4 配置中心清单，改为测量单元 KPI 模型（v5）交付
- [ ] T026 [P] [US4] 改写 `docs/architecture.md` KPI 配置段落：删去 v4 动态口径与已退役 `/api/v3/kpi/resource-metrics`，指向现行 `/api/v5/kpi/measurement-*`
- [ ] T027 [P] [US4] 改写 `docs/design/mechanisms.md` 分类线索小节为测量单元候选绑定与自动入库的现行机制
- [ ] T028 [P] [US4] 改写 `docs/design/entrypoints.md` 动态口径入口为 v5 测量单元维护入口
- [ ] T029 [US4] 检索校验：`grep -rn "/api/v4" docs/architecture.md docs/roadmap.md docs/design/mechanisms.md docs/design/entrypoints.md` 为空；`grep -rn "/api/v4" specs/016-ui-derived-metrics/` 每条均带历史标注

**检查点**：全部用户故事独立可用且互不破坏

---

## 阶段 7：收尾与横切关注点

**目的**：影响多个用户故事的最终验证与交付

- [ ] T030 按 `specs/032-api-contract-governance/quickstart.md` 执行场景 1–4 全部命令并记录结果（后端 4 条、检索断言、前端 4 条）
- [ ] T031 确认 `tests/fixtures/make_real_package.py` 无需变更（本批次无新业务数据与展示用例），并在提交信息中说明
- [ ] T032 运行 `python build.py lint`、`python build.py test`、`python build.py contract`、`python build.py gen-web-api` 收尾门禁；勾选本文件全部任务项并按中文提交信息提交
- [ ] T033 合入 `main` 后按宪法执行合入验证：`python build.py lint`、`python build.py test`、`python build.py web-build`、`python build.py e2e`（本批次改动 `web/src/api/client.ts`，属前端变更）全部通过后方可清理工作树
- [ ] T034 推送 `origin/main` 后核对 GitHub Actions：`backend` 与 `frontend` 两个 job 自动触发并通过（quickstart 场景 5），保留运行链接作为交付证据

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：无依赖——可立即开始
- **基础层（阶段 2）**：依赖设置完成——T003 是 US1 的阻塞前置，与 T005 同批落到绿
- **用户故事 1（阶段 3）**：依赖 T003；是 US2 的隐含前置（守卫对真实契约的断言需要重复组已消失）
- **用户故事 2（阶段 4）**：依赖 T005–T006 完成后对真实契约的全绿断言；三条守卫与 T004 共同构成回归保护
- **用户故事 3（阶段 5）**：依赖 US1/US2 完成后本地命令全部为绿
- **用户故事 4（阶段 6）**：与 US1–US3 无代码依赖，可并行推进
- **收尾（阶段 7）**：依赖全部所需用户故事完成

### 每个用户故事内部

- 测试先写并确认失败（T004 对实现为红；T015–T017 对合成违规用例为红）
- 契约先于实现（T003 → T005–T006）
- 实现先于迁移与再生成（T005–T007 → T008–T013）
- 每个故事完成后再进入下一个优先级

### 并行机会

- T008–T011 修改不同测试文件，可并行
- T015–T017 三条守卫为独立函数，可在同一文件内顺序小步提交，也可由不同人先分头起草
- T022–T028 修改不同文档文件，可并行
- US4 可在 US1–US3 推进期间由另一人并行完成

---

## 并行示例：用户故事 1

```bash
# 同时迁移不同测试文件：
Task: "迁移 tests/baseline_helpers.py 与 tests/test_api.py 创建调用到 v3"
Task: "迁移 tests/test_api_robustness.py 上传助手到 v3"
Task: "迁移 tests/test_baseline_pipeline.py 与 tests/test_baseline_upload.py 到 v3"
Task: "迁移 tests/test_auth.py、tests/test_observability.py、tests/test_task_rebuild.py 到 v3"
```

## 并行示例：用户故事 4

```bash
# 同时改写不同文档：
Task: "更新 specs/015 与 specs/016 状态及 v4 引用标注"
Task: "更新 specs/025–028、030 状态行"
Task: "改写 docs/roadmap.md 与 docs/architecture.md"
Task: "改写 docs/design/mechanisms.md 与 docs/design/entrypoints.md"
```

---

## 实现策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：设置
2. 完成阶段 2：基础层（T003 契约先行）
3. 完成阶段 3：用户故事 1
4. **停止并验证**：T004/T007/T014 全部绿后独立演示入口收敛

### 增量交付

1. 设置 + 基础层 → 基础就绪
2. US1 → 独立测试 → 入口收敛可交付（MVP）
3. US2 → 独立测试 → 守卫固化
4. US3 → 独立测试 → 门禁上线
5. US4 → 独立测试 → 文档与状态同步
6. 阶段 7 → quickstart 全场景验证后交付

### 说明

- 本批次不新增依赖、不改巡检规则/执行器/数据模型；`v2` 其余接口保持冻结
- 契约（T003）与实现（T005–T006）必须同批提交，`python build.py contract` 的判据是双向完全一致
