# Phase 0 研究：KPI 巡检结果判读工作台

**功能**：`041-kpi-result-workbench`
**日期**：2026-11-05
**输入**：[spec.md](./spec.md)
**状态**：设计未知项已收敛，Plan 与 tasks 已生成；待 analyze/review 后提交规划产物

## 1. 契约版本与 v5 冻结边界

**Decision**

- 新工作台、团队关注、测量单元范围、规则归属全部使用 `/api/v6/...`。
- 现有 `/api/v5/kpi/...` 路由、Schema 和字段语义原地冻结；新代码不得把 v5 作为读取回退、写入镜像或双写目标。
- `POST /api/v3/tasks` 只增加可选表单字段 `rule_network_element_type`，不改变既有字段语义；`POST /api/v2/tasks/{task_id}/rebuild` 保持原契约。
- 既有 v5 `/api/v5/kpi/measurement-bindings/batch-confirm` 与 v2 `/api/v2/inspector-states*` 在 OpenAPI 标记 `deprecated`。新 UI、新服务与 v6 不调用它们；物理删除属于独立旧版下线工作。

**Rationale**

- v5 同一测量单元 ID 可被 UMF/CSP 重复使用，按既有字段含义无法无歧义地承载 v6 复合身份。
- AGENTS.md 要求破坏性 API 变更进入新版本，且 FR-034/SC-017 明确要求 v5 字段含义不变。
- FR-031 要求退出批量确认，FR-034 要求 v5 冻结。两者的兼容实现是“新界面与 v6 无该能力、旧接口 deprecated、后续独立下线”，而不是在本功能中破坏性删除 v5 路径。

**Alternatives considered**

- 原地给 v5 响应增加 `product` 并切换所有调用方：会造成同一路径在相同 ID 下出现歧义，破坏既有客户端，拒绝。
- 删除 v5 `batch-confirm` 路由：违反 v5 冻结和破坏性变更规则，拒绝。
- 新旧接口双写：会产生两套事实源和故障时不一致，拒绝。

## 2. v6 作用域数据模型与 SQLite 迁移

**Decision**

- 新建 v6 作用域 KPI 表，不复用可冲突的全局 `resource_id` 主键。所有业务键至少包含 `network_element_type`：
  - 资源：`UNIQUE(network_element_type, resource_id)`
  - 绑定：`UNIQUE(network_element_type, measurement_unit_id, raw_source_name)`
  - 派生：`UNIQUE(network_element_type, measurement_unit_id, metric_resource_id)`
  - 维护口径：同样的三元复合唯一键
  - KPI 历史点：新增 `task_kpi_points_v6`，显式携带 `network_element_type`
- v5 KPI 表保留原结构并冻结，不把新语义塞回旧表。新任务写入 v6 表。
- 历史配置按“可证明唯一归属 → 自动落入 v6；缺失归属 → 待归属；多候选归属 → 待归属并保留候选”迁移。不得默认 UMF/CSP，也不得建立公共归属。
- 缺失归属的测量单元/绑定/派生/维护配置在完成归属前不进入任何任务；待归属记录保留原值、候选、原因和重试信息。
- `init_db()` 接入一次性、幂等迁移：建表/加列 → 迁移与回填 → 审计留存清理。迁移键由源表和源记录稳定生成，重复启动不重复插入。
- 唯一约束在数据库层和 Pydantic/API 层同时校验。

**Rationale**

- 当前 `KpiMeasurementResource.resource_id` 为全局主键，UMF 与 CSP 可使用相同测量单元/指标 ID；现有绑定、派生和维护口径唯一约束也不含网元类型。
- SQLite 无法可靠地原地改变主键和复合唯一约束；新建 v6 表可同时保证 v5 冻结、可回滚和幂等迁移。
- 待归属显式化避免静默选错网元类型，符合“无公共范围”原则。

**Alternatives considered**

- 直接重建旧表并复制 ID：UMF/CSP 相同 ID 会冲突或互相覆盖。
- 用 `resource_id` 字符串前缀编码 product：破坏既有资源 ID 语义并把作用域耦合进展示标识。
- 迁移时默认归到首个任务 product：可能把历史配置错误投向另一网元类型，拒绝。

## 3. 测量单元级巡检范围

**Decision**

- v6 中巡检范围唯一日常开关是测量单元 `inspection_enabled`。
- 单位启用后，纳入其全部已确认基础指标和全部已定义派生指标；绑定、派生、维护配置不再以 `enabled` 抑制巡检。
- 指标缺少阈值、方向、聚合方式或基线时仍进入结果，以 `needs_config` / `unjudgeable` / `no_baseline` 等状态呈现。
- 停用单位只影响后续任务，保留绑定、派生、维护配置、团队关注和历史结果。
- 任务启动时生成并持久化 `KpiTaskScopeSnapshot`，冻结 product、配置 revision、启用单元集合和指标集合。旧任务查询使用该快照，不因后续启停或改名而消失。
- 历史 `enabled=false` 的恢复在 v6 中体现为“不再作为巡检门禁”，并逐对象写 `KpiLegacyRecoveryAudit`；不把停用自动转成团队关注，也不自动启用测量单元。

**Rationale**

- 可解释性和历史稳定性要求旧任务结果不受后续配置变更影响。
- 只冻结规则集合不足以解释 KPI 结果；还需冻结当时启用的测量单元和指标集合。
- 将恢复定义为语义恢复而非改写 v5 数据，可同时满足审计与 v5 冻结。

**Alternatives considered**

- 查询时实时读取当前启用状态：停用单位会让旧任务历史消失，违反“只影响后续任务”。
- 保留指标级 `enabled` 作为执行门禁：与用户确认的测量单元粒度冲突。
- 删除所有旧 `enabled=false` 行：损失审计与可恢复性，拒绝。

## 4. 团队关注与并发保存

**Decision**

- 团队关注使用 v6 独立表，业务唯一键为 `(network_element_type, measurement_unit_id, metric_resource_id)`；初始为空，不迁移旧 `enabled`。
- 读取需要现有登录权限；新增/移出需要现有维护写权限（`admin`）。列表返回按 product 的作用域 revision。
- 修改使用一个原子 `PATCH`：请求携带 `expected_revision`、`add[]`、`remove[]`。服务端在同一事务中校验 revision、去重、校验当前任务可加入项、应用差异并递增 revision。
- revision 冲突返回 `409 team_focus_revision_conflict` 和当前 revision；前端保留暂存选择并要求刷新/重试。
- 当前任务不存在的关注项永久保留，响应标记 `availability=unavailable` 和原因；不得在保存时自动删除。
- 关闭有未保存修改的侧栏时，前端仅提示放弃或继续编辑，不自动保存。

**Rationale**

- 团队级共享配置若“整表覆盖”会造成多人同时编辑时静默丢失更新。
- 差异 PATCH 配合 revision 能保留不可用项，也避免当前任务目录收窄时误删跨任务关注。
- 一次保存完成批量加入/移出，符合 3 个动作以内和失败重试要求。

**Alternatives considered**

- 每用户本地存储：违反共享要求。
- 每次勾选立即保存：批量操作原子性差且失败恢复复杂。
- 整表 `PUT`：当前任务不可用项与并发编辑容易误删，拒绝。

## 5. 规则网元归属、执行与审计

**Decision**

- 删除“公共规则”语义；`rule_network_assignments` 只存 `rule_code + network_element_type`，一个业务规则可有多行，零行即“未归属”。
- 归属是业务规则唯一执行范围开关，规则 Python 实现不声明/硬编码网元类型；允许的网元类型来自运行时 network-element-type 字典。
- 迁移不把既有 `RuleState.enabled` 或 `scan_rules.disabled_rules` 转成归属；所有既有业务规则升级后初始未归属，需要人工配置。
- `rule_states` / v2 `inspector-states` 仅作为 deprecated 兼容影子保留，执行器、CLI 和 v6 规则目录绝不读取其 `enabled`。
- 规则目录读取全部已注册普通规则，显示 `definition_version`、归属标签或 `unassigned`。写入每条规则时使用 `expected_revision`，服务端原子替换该规则归属集合并写审计。
- 清空归属是合法写操作，但 UI 必须二次确认“该规则将停止参与后续任务”。
- 隐藏解压/分类单元不受归属约束；规则私有 prepare 仅在 owner 进入快照时执行。

**Rationale**

- 规则归属必须在运行时变更、共享和审计，不能固化进规则代码。
- 保留旧状态表但不读取，既满足“废弃全局启停”的新语义，也避免破坏为兼容而保留的旧 API。
- 每规则 revision 可防止两名维护者互相覆盖归属配置。

**Alternatives considered**

- 继续复用 `RuleState.enabled`：与网元归属并存会成为第二套执行开关，违反 FR-038。
- 在每次任务执行时实时查询规则：任务执行中修改归属会导致同一任务前后不一致。
- 启动时自动把所有规则归到 UMF/CSP：违反 FR-044 的初始未归属要求。

## 6. 任务规则范围快照与版本冻结

**Decision**

- `TaskRuleScopeSnapshot` 为每个任务保存：
  - `task_id`
  - `network_element_type`（日志补充包未选时为 null）
  - `assignment_revision`
  - 有序 `rules[]`，每项含 `rule_code`、`rule_version`、category、priority
  - `registry_fingerprint`（规则注册表的稳定摘要）
  - `frozen_at`、`trigger`、`source`
- 新任务在真正开始执行前创建快照；排队期间允许配置变化。任务一旦冻结，当前执行只使用快照。
- 显式全量重建创建新快照；单规则/增量重跑沿用原任务快照，只能操作快照中的规则，否则返回 `rule_not_in_task_scope`。
- 若服务重启后发现快照中的 `rule_version` 与当前注册表不一致，任务以 `rule_snapshot_version_mismatch` 失败并提示全量重建；不得静默换用新版本。
- API 与 CLI 共用同一 `RuleScopeResolver` 和快照构建逻辑；CLI 将相同快照写入任务元数据/DB，保证双模式语义一致。
- 日志补充包的 `rule_network_element_type` 只用于选择执行快照；未选择时快照规则集为空，只执行隐藏解压/分类单元。

**Rationale**

- 归属变更必须不污染已开始任务；规则实现版本也可能在排队期间变化，必须可解释。
- 冻结规则代码、版本、归属 revision 和注册表指纹，可复现“为什么执行/未执行此规则”。
- 单规则重跑不能引入新规则，否则单规则维护操作会改变整个任务范围。

**Alternatives considered**

- 任务入队即冻结：排队期间大量配置修改会产生不可见延迟，与“任务启动时冻结”不符。
- 执行时只冻结 code 不冻结版本：重启后同 code 可能已是新实现。
- 每次执行都覆盖快照：历史任务不可解释，拒绝。

## 7. 日志补充包独立网元字段

**Decision**

- `POST /api/v3/tasks` 新增可选 `rule_network_element_type` 表单字段，仅对 `log_supplement` 有效；巡检包必须为空并从 `product` 派生。
- 该字段不写入 `customer.product`，不改变 classification profile `GENERIC`，不触发设备台账。
- 日志补充包任务身份冲突矩阵扩展为：`checksum → package_kind → product → rule_network_element_type`。
- 新增稳定错误码：
  - `invalid_rule_network_element_type`：值不在运行时字典或已停用。
  - `package_rule_network_element_type_conflict`：同名同 checksum/kind 但选择不同。
  - `metadata_not_applicable`：巡检包携带该字段。
- 未选择时任务显示“未选择规则适用网元类型”，普通规则集合为空，内部技术单元仍可完成。

**Rationale**

- 复用 `product` 会污染巡检元数据与台账判定，违反 FR-039。
- 将字段纳入冲突矩阵可防止同名包在不同规则范围下被错误恢复。
- 独立字段可同时支持“不指定”和未来新增网元类型。

**Alternatives considered**

- 复用 `product`：改变日志包既有语义和分类逻辑。
- 强制日志包选择类型：违反“可不选”和只执行内部技术单元的要求。

## 8. 历史停用恢复与待归属

**Decision**

- 新增 `kpi_legacy_recovery_audits`，逐对象记录 source table/id、source key、候选 product、最终 product、before snapshot、result、error、attempt count、actor/source 和时间。
- 迁移先执行可唯一归属对象的语义恢复；缺归属或歧义对象进入 `pending_attribution`，不得进入 v6 巡检范围。
- 提供 v6 审计查询、归属指定和失败重试；部分失败保留成功项，不声称整体完成。
- 恢复和归属操作不改写既有 task rule result、KPI 点、报告或 v5 历史行。

**Rationale**

- 需同时满足可审计、幂等、部分失败与历史不可变。
- 待归属显式化让维护人员指定作用域，避免系统猜测。

**Alternatives considered**

- 启动时一次性静默修补：失败不可见、无法重试，拒绝。
- 回填进公共作用域：违反无公共规则/KPI 作用域原则。

## 9. 旧任务与重建

**Decision**

- 不迁移、不兼容旧任务结果；v6 查询遇到未带新快照的旧任务固定返回 `409 task_result_requires_rebuild`，并给出任务列表重建入口。
- 继续复用现有 `POST /api/v2/tasks/{task_id}/rebuild`，UI 在任务列表行内提供重建；二次确认文案明确删除并重建输出、不可撤销、原始包只读。
- 全量重建保持同一 `task_id`，重新执行当前规则归属、当前 KPI 范围并生成新快照。
- 原始包缺失/现场清理时沿用现有 `409 package_missing` / `410 scene_cleaned`，前端引导上传同名包覆盖重建。

**Rationale**

- 用户已明确不需要旧任务兼容，也不考虑旧任务迁移。
- 复用已验证的全量重建链路，避免另建任务复制协议。

**Alternatives considered**

- 在新工作台做 v5 适配层：与“不兼容旧任务”冲突且维护双语义。
- 新建 task_id：破坏一个包一个任务和原包身份。

## 10. OpenAPI → Pydantic → FastAPI → 生成客户端顺序

**Decision**

- 先更新 `docs/api/openapi.yaml`：新增 v6 路径、Schema、错误码，给既有 v5 兼容路径标 deprecated，扩展 v3 表单字段。
- 再新增 `app/models/kpi_v6.py` 与 `app/api/kpi_v6.py`，并在 `app/api/router.py` 注册 `v6_router`。
- 再执行 `python3 build.py contract` 和 `python3 build.py gen-web-api`，由生成客户端驱动前端。
- 契约测试必须覆盖：v6 路径存在、v5 字段未变、错误结构 `{code,message,detail}`、列表分页、202 + Location（建/重跑类）。
- 前端禁止手写与 OpenAPI 不一致的请求。

**Rationale**

- 项目宪法规定 OpenAPI 是唯一契约源，AGENTS.md 要求先改 OpenAPI。
- 生成客户端能防止 v5/v6 混用和字段漂移。

**Alternatives considered**

- 先写后端再补 OpenAPI：违反工程红线，拒绝。
- 前端直接 `fetch` 新接口：违反生成客户端约束，拒绝。

## 11. 测试、合成样例与展示验证

**Decision**

- 后端权威测试层：
  - 单元：作用域键、revision、范围/判定分组、恢复状态机、规则快照纯函数。
  - 集成：SQLite 幂等迁移、UMF/CSP 相同 ID 隔离、任务执行/重建、日志补充包字段、v5 冻结。
  - 契约：OpenAPI 与 Pydantic/FastAPI 一致。
- 前端组件测试：三视图、计数对账、证据抽屉、关注暂存/冲突、单位启停、规则归属、任务行内重建。
- 单一端到端 E2E 覆盖“打开任务 → 需处理 → 指标证据 → 团队关注加入/移出 → 全部指标追溯”。另以独立场景覆盖规则归属与日志补充包，不重复同一断言。
- 扩充 `tests/fixtures/make_real_package.py`：追加 20 个真实呼叫 KPI 指标身份且其中 10 个纳入团队关注、UMF/CSP 同 ID、历史停用、缺配置、冲突/失败边界；固定时间戳且幂等，既有样例只增不减。
- 桌面视口：1280、1440、1920；1440×900 首屏需看到汇总、分组和至少 5 个关注指标。
- Chrome 仅用于查看已确认的 v2 合成效果图和人工视觉复核，不作为自动化测试依赖。

**Rationale**

- 项目要求新功能有自动化、代表性样例和展示效果用例，且避免重复测试同一行为。
- 真实包和运行产物禁止入库，测试只能使用明确合成/脱敏 fixture。

**Alternatives considered**

- 只用内联数据：无法证明真实用户路径和界面展示，拒绝。
- 用真实 KPI 包：违反真实数据隔离原则，拒绝。

## 12. 设计后需复核的风险

| 风险 | 结论与处置 |
| --- | --- |
| FR-031 与 v5 冻结冲突 | 新 UI/v6 删除能力，v5 endpoint deprecated 保留，物理删除进入独立下线功能；Plan Review 明确接受此边界。 |
| 规则初始全部未归属导致升级后无业务规则执行 | 这是 FR-044 的明确结果；规则页提供批量/逐条配置，任务页显示“未配置可执行业务规则”，不伪造通过。 |
| v5 配置无法证明 product | 进入待归属，不猜测；必须先指定 product 才能恢复巡检。 |
| 20 指标首屏与三档宽度 | 使用紧凑结果表 + 右侧证据抽屉；1280 无页面横向滚动，列内允许横向滚动；E2E 固定视口验证。 |
| 规则代码在排队期间变更 | 快照记录 rule_version；版本不一致失败并要求全量重建，不静默换版本。 |
