# 阶段 0 研究：API 契约治理与持续集成门禁

**日期**：2026-10-10 | **规格**：[spec.md](spec.md) | **计划**：[plan.md](plan.md)

## D1 删除 v2 创建入口而不是标废弃

**Decision**：直接删除 `POST /api/v2/tasks`；`POST /api/v3/tasks` 是唯一创建入口。

**Rationale**：对现状契约做跨版本分析后确认，`(method, 去版本前缀路径)` 重复组只有一个：`POST /tasks`（v2 + v3）。v2 创建与 v3 能力完全重复，v3 额外强制 `package_kind` 与省份/运营商口径；前端 `web/src/api/http.ts` 早已只用 v3；v2 创建的实际调用方只有 8 个测试文件与自动生成的客户端。用户明确批准直接删除，且外部调用不在支持范围。

**Alternatives considered**：保留 v2 并标 `deprecated`（与用户决定冲突，双入口继续制造引用歧义）；保留墓碑返回 410（同样与"直接删除"冲突，且新增契约负担）。

## D2 契约守卫的落地位置与形式

**Decision**：三条契约侧守卫进入既有 `tests/test_contract.py`：

1. `operationId` 唯一且非空；
2. 无空版本前缀（见 D3）；
3. 同一能力唯一当前入口：按"去版本前缀路径 + 方法"分组，多版本组中版本号最大者为当前入口（必须未标废弃），其余必须 `deprecated: true` 且在描述中注明替代入口路径。

**Rationale**：既有 `tests/test_contract.py` 已承载契约与实现一致性测试，守卫放同处便于复用 `generate_openapi()` 与契约加载逻辑，且天然进入 `python build.py test`。三条守卫都是内存内结构检查，不增加测试时长。

**Alternatives considered**：新建独立 `tests/test_api_governance.py`（增加文件但无实质收益）；把守卫写进 `app/contract/export.py`（让导出工具承担治理职责，且外部消费者无法单独复用 pytest 报告）。

## D3 空版本前缀的检测口径

**Decision**：从 `app.api.router` 模块中枚举所有 `*_router` 变量取得 prefix 集合，与生成契约中出现的 `/api/vN` 前缀集合双向求差：代码侧有而契约无 → 空版本；契约有而代码无 → 孤儿版本。删除 `v4_router` 后两侧集合一致。

**Rationale**：空版本路由不会出现在 `app.routes` 与 OpenAPI 路径中，无法从路由表反推；直接枚举 router 模块变量是唯一可靠且不依赖命名巧合之外约定（`*_router` 命名已是仓库现状）的方式。

**Alternatives considered**：只断言契约中无 `/api/v4/` 路径（无法阻止未来新的空壳前缀）；扫描源码文本找 `APIRouter(prefix=` （正则脆弱，易被格式化改动影响）。

## D4 契约与生成客户端一致性的检查方式

**Decision**：由门禁执行"再生成 + 零差异"：`npm run gen-api` 后 `git diff --exit-code -- src/api/client.ts`；本地与 CI 使用同一命令，CI 前端 job 中作为独立步骤失败即红。

**Rationale**：`web/src/api/client.ts` 由 openapi-typescript 生成，结构是 TypeScript；在 pytest 中解析 TS 脆弱且需要 npm 参与后端测试环境。再生成后 diff 是生成器作者推荐且零误报的做法。

**Alternatives considered**：pytest 调 subprocess 跑 npm（后端 job 被迫安装 Node，违背前端/后端 job 分离）；在 pytest 中用正则提取 operationId 对比（只能覆盖部分信息，无法覆盖类型与 schema 漂移）。

## D5 CI 结构与命令映射

**Decision**：新增 `.github/workflows/ci.yml`：触发器 `push: [main]` 与 `pull_request`；两个并行 job（均 `timeout-minutes: 15`）：

- `backend`：`actions/setup-python@v5`（3.12）→ `python build.py install` → `python build.py lint` → `python build.py test` → `python build.py contract`；
- `frontend`：`actions/setup-node@v4`（22，npm 缓存指向 `web/package-lock.json`）→ `npm ci` → `npm run gen-api` + `git diff --exit-code -- src/api/client.ts` → `npm run build` → `npm test`。

**Rationale**：`build.py install` 按 `requirements-lock.txt` 建 `.venv` 并以 `--no-deps -e .` 安装本地项目，正是本地标准环境，满足"门禁复用既有命令"；前端依赖由 `package-lock.json` 精确锁定。`timeout-minutes: 15` 把 SC-004 固化为门禁行为而不是口头目标。不跑 `verify` 与 `e2e`。

**Alternatives considered**：单 job 串行（反馈更慢）；在 CI 中直接 `pip install -e .[dev]`（绕开仓库锁与构建入口，产生第二套安装路径）；引入缓存矩阵/分片（当前套件规模无必要）。

## D6 测试创建调用的迁移策略

**Decision**：8 个测试文件中的 15 处 `POST /api/v2/tasks` 创建调用全部迁移到 `/api/v3/tasks`：请求体增加 `package_kind="inspection"`，按测试需要补齐 `province` 与 `operator`；共享助手 `tests/baseline_helpers.py` 与 `test_api_robustness.py` 的两个上传帮助函数改为统一签名。文件名/大小/校验和冲突等边界测试使用最小合法元数据，不触碰 v3 校验规则。

**Rationale**：v3 对巡检包强制省份与运营商是现行契约，迁移必须显式提供而不是绕过；集中在助手函数中改动可把 15 处收敛为少量修改点。

**Alternatives considered**：为迁移放宽 v3 必填校验（违反现行契约，且会削弱元数据治理）；保留 v2 仅用于测试（与删除决定冲突）。

## D7 016 与四份文档的 v4 引用改写规则

**Decision**：不做机械 `v4→v5` 路径替换。逐处按当前事实改写：

- `docs/roadmap.md` M6 范围条目：删去 v4 配置中心清单，改写为"测量单元 KPI 模型（v5）交付"；
- `docs/architecture.md` KPI 配置段落：删去 v4 动态口径与已退役的 `/api/v3/kpi/resource-metrics` 描述，指向现行 `/api/v5/kpi/measurement-*` 资源；
- `docs/design/mechanisms.md` 分类线索小节：改写为"测量单元候选绑定与自动入库"的现行机制（分类线索接口已随 v4 删除）；
- `docs/design/entrypoints.md`：动态口径入口改为 v5 测量单元维护入口；
- `specs/016-ui-derived-metrics/{spec,research,tasks,contracts/openapi-contract}.md`：顶部/引用处标注"v4 配置中心已被测量单元重构替代，现行入口为 `/api/v5/kpi/measurement-derived`"；具体历史路径保留并显式标记历史。

**Rationale**：v4 时代的"配置中心 + 分类线索"整体被 `c429139` 的测量单元重构替代，能力不以同路径迁移；机械替换会产出指向不存在路径的假文档。规格 016 的验收对象（受控派生指标维护）在 v5 以 `POST /api/v5/kpi/measurement-derived` 存在，故状态为"已实现"，历史契约保留并加注。

**Alternatives considered**：全仓库删除 v4 字样（丢失历史脉络，且 015 作为被替代规格需要保留历史设计）；只改 docs 不改 specs（016 的契约草案仍会误导实现）。

## D8 规格状态同步范围与目标值

**Decision**：015 → "已被替代"（注明由测量单元 KPI 重构替代）；016、025、026、027、028、030 → "已实现"；017/019 既有的"已被部分替代"表述保持不变；002–014 等早期规格维持原状（属旧状态规范，不在本批次）。

**Rationale**：016 tasks.md 32/32 完成且能力现存于 v5；025–028 tasks 31–61 项全部完成，030 31 项全部完成且实现已合入 `main`；015 的实现（v4 配置中心）已在 `c429139` 删除。早期规格从未使用"已实现/已澄清"状态体系，统一重标会放大批次范围。

**Alternatives considered**：把所有历史规格状态一并重标（范围失控）；只改 015（025–028/030 的失真会继续误导后续批次）。

## D9 门禁失败的输出要求

**Decision**：三条 pytest 守卫的断言消息必须包含违规的具体版本前缀/路径/操作；客户端漂移由 `git diff` 原样输出差异文件。

**Rationale**：满足 FR-012 与容错原则（禁止笼统失败）；`git diff` 自带文件级差异，无需定制输出。

**Alternatives considered**：统一自定义错误报告器（对当前规模过度设计）。
