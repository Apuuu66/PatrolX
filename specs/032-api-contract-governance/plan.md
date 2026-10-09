# 实现计划：API 契约治理与持续集成门禁

**分支**：`032-api-contract-governance` | **日期**：2026-10-10 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/032-api-contract-governance/spec.md` 的功能规格

## 摘要

批次 A 只做治理止血与最小 CI，不新增业务能力、不改执行语义。四件交付物：

1. **入口收敛**：删除 `/api/v2/tasks` 创建入口与 `/api/v4` 空壳路由，`/api/v3/tasks` 成为唯一任务创建入口；v2 其余接口冻结；全仓库第一方调用方（8 个测试文件的 15 处创建调用、生成客户端）迁移到 v3；契约与客户端同步再生成。
2. **契约守卫**：在既有 `tests/test_contract.py` 增加四条守卫——operationId 唯一、无空版本前缀、同一能力唯一当前入口且旧入口须标废弃与替代（判定口径：去版本前缀路径 + 方法）、契约与生成客户端零漂移（再生成 + `git diff` 检查，由前端门禁执行）。
3. **最小 CI**：新增 `.github/workflows/ci.yml`，两个并行 job——后端（`python build.py install/lint/test/contract`）与前端（`npm ci`、`npm run gen-api` 后 diff、`npm run build`、`npm test`）；触发条件为推送到 `main` 与合并请求；不跑完整 `verify`、不跑 E2E；job 超时 15 分钟。
4. **文档与规格状态同步**：015 标记"已被替代"；016 状态改为已实现并将其 v4 引用语义改写为 v5 测量单元模型；025–028、030 状态改为已实现；`docs/roadmap.md`、`docs/architecture.md`、`docs/design/mechanisms.md`、`docs/design/entrypoints.md` 的 v4/已退役 v3 引用改写为现行 v5 事实。

改造后状态：契约中跨版本重复能力组为 0（当前唯一重复组是 v2/v3 的 `POST /tasks`，删除后消失）；任务创建入口唯一；凡推送与合并请求都自动得到 lint/test/契约/前端四类门禁结论。

## 技术上下文

**语言/版本**：Python 3.11+（CI 用 3.12，与仓库 `.venv` 一致）；Node.js 22（CI 与本地一致）

**主要依赖**：不新增依赖。后端使用既有 FastAPI/Pydantic/pytest/ruff 与 `requirements-lock.txt`；前端使用既有 openapi-typescript、Vitest、Playwright（E2E 不进门禁）

**存储**：不涉及运行时存储与数据模型变更

**测试**：pytest（契约守卫 + 迁移后的既有套件）；前端 `npm test`（node --test + vitest）；契约一致性由 `python build.py contract` 与客户端再生成 diff 双重把关

**目标平台**：GitHub Actions（ubuntu-latest）+ 本地 macOS；本地与 CI 使用同一套命令

**项目类型**：离线巡检系统（FastAPI 在线模式 + 本地 CLI 模式）的治理与门禁改造

**性能目标**：单次门禁（两个 job 并行）15 分钟内完成；不因新增守卫显著拉长测试时间（守卫为内存内结构检查）

**约束条件**：不改巡检规则与执行器；v2 其余接口冻结；不跑完整 verify/E2E；门禁只读，不自动改写契约与客户端

**规模/范围**：2 处路由清理 + 1 个契约增量 + 3 条 pytest 守卫 + 1 个客户端漂移门禁 + 1 个工作流 + 8 个测试文件迁移 + 6 个规格状态与 4 份文档同步

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 处理 |
| --- | --- | --- |
| 离线优先 | 通过 | 不涉及采集与连接能力 |
| 一个包、一个任务 | 通过 | 不改任务身份与目录模型 |
| 契约驱动 | 通过 | 契约先行删除 v2 创建与 v4；OpenAPI、Pydantic、生成客户端与测试同步；守卫把一致性固化为门禁 |
| 模式同构 | 通过 | 仅改 API 表面与门禁，不触本地 CLI 巡检语义 |
| 巡检器插件架构 | 通过 | 不触规则注册与调度器 |
| 源文件显式匹配 | 通过 | 不触规则声明 |
| 增量重跑 | 通过 | 不改重跑与结果存储；v2 重跑/重建接口冻结保留 |
| 解压先行 / 规则私有预处理 / 安全解压 | 通过 | 不触解压、prepare 与路径安全逻辑 |
| 幂等与可追溯 | 通过 | 迁移后重复上传复用与同名异包冲突语义保持；迁移测试覆盖 |
| 轻量默认 | 通过 | 不新增运行时依赖与服务；CI 仅用既有锁文件与工具链 |
| 容错 | 通过 | 守卫失败输出可定位的路径/操作信息，不静默跳过 |
| 时间/命名/日志 | 通过 | 不新增持久化时间字段；文档与提交使用中文 |
| 破坏性变更约束 | 需说明 | `/api/v2/tasks` 创建入口属破坏性删除，见“复杂度跟踪”；替代能力已在 `/api/v3/tasks` 交付，删除经用户明确批准，v2 其余接口冻结 |

**阶段 1 复查**：设计未引入新依赖、新存储、新运行模式；守卫与门禁均为只读检查；文档改写真正确认过当前 v5 实际接口（`/api/v5/kpi/measurement-units*`、`measurement-bindings*`、`measurement-resources*`、`measurement-derived`）。结论不变。

## 阶段 0 研究结论

详见 [research.md](research.md)。关键决定：

- 删除而非废弃 v2 创建：它是契约中唯一的跨版本重复能力组，第一方调用方已全部使用 v3（仅测试与生成客户端残留），经用户明确批准直接删除；此后同类默认"保留 + 标废弃"。
- 守卫落地：三条契约侧守卫进 `tests/test_contract.py`；客户端漂移用"再生成后 `git diff --exit-code`"在 CI 前端 job 与本地同命令执行。
- 空版本检测：枚举 `app.api.router` 中所有 `*_router` 的 prefix，与契约中的版本前缀集合求差，双向断言。
- CI：GitHub Actions 两个并行 job；后端复用 `build.py install/lint/test/contract`，前端 `npm ci` + `gen-api` diff + `build` + `test`；`timeout-minutes: 15` 将反馈时间固化为门禁本身。
- v2 创建迁移：8 个测试文件 15 处创建调用迁移到 v3，统一补 `package_kind="inspection"`、省份与运营商元数据；不修改 v3 校验规则。
- 016 与文档：不做机械路径替换。v4 时代的"配置中心/分类线索"整体改写为 v5 测量单元模型的现状描述；无法对应的能力明确标注已被替代。

## 阶段 1 设计产物

- [data-model.md](data-model.md)：治理概念模型（能力入口、版本前缀、规格状态、门禁检查项）与校验规则
- [contracts/api-surface-delta.md](contracts/api-surface-delta.md)：公共接口增量（v2 创建移除、v4 移除）与守卫规则口径
- [contracts/ci-gate.md](contracts/ci-gate.md)：门禁检查项与本地命令映射
- [quickstart.md](quickstart.md)：可重复执行的验收步骤与预期结果

## 项目结构

### 文档（本功能）

```text
specs/032-api-contract-governance/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
├── contracts/
│   ├── api-surface-delta.md
│   └── ci-gate.md
└── tasks.md              # $speckit-tasks 生成
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py          # 删除 create_task_v2、v4_router 定义；保持 v2 其余路由
└── main.py                # 移除 v4_router 导入与 include_router

docs/
├── api/openapi.yaml       # 删除 /api/v2/tasks path、createTaskV2、Body_createTaskV2
├── architecture.md        # §7.x KPI 配置段落改写为 v5 测量单元模型
├── roadmap.md             # M6 范围条目改写（不再引用 v4 配置中心）
└── design/
    ├── mechanisms.md      # §分类线索改写为现行绑定/自动入库机制
    └── entrypoints.md     # 动态口径入口改写为 v5

tests/
├── test_contract.py       # +3 条守卫（唯一性 / 空版本 / 唯一当前入口与废弃标记）
├── baseline_helpers.py    # 上传助手迁移 v3
└── test_api*.py / test_baseline_*.py / test_auth.py / test_observability.py / test_task_rebuild.py
                           # 7 个文件的创建调用迁移 v3（共 15 处）

specs/
├── 015-kpi-dynamic-config/spec.md        # 状态：已被替代
├── 016-ui-derived-metrics/               # 状态：已实现；v4 引用语义改写为 v5
├── 025..028/030/spec.md                  # 状态：已实现
└── 032-api-contract-governance/          # 本功能

web/
└── src/api/client.ts      # 由 npm run gen-api 再生成

.github/
└── workflows/ci.yml       # 新增：后端 + 前端两个并行 job
```

**结构决策**：沿用仓库既有多层结构（`api → services`），本功能只触 API 表面、契约、测试、文档与 CI；前端仅再生成客户端，不改页面代码。

## 复杂度跟踪

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 删除 `/api/v2/tasks` 创建入口（破坏性删除，未按"新前缀交付"保留旧入口） | 经用户明确批准的一次性治理：该入口与 v3 能力完全重复，是契约中唯一的跨版本重复组；前端早已使用 v3；外部调用不在支持范围 | 方案 A：保留 v2 并标 `deprecated` —— 与用户"直接删除"的决定冲突，且留下双入口继续制造引用歧义；方案 B：保留墓碑 410 —— 同样与"直接删除"冲突，且墓碑本身是新契约负担 |
