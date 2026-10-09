# 阶段 0 研究：主界面信息层级重构（巡检控制台方向）

**功能**：031-ui-information-hierarchy | **日期**：2026-10-10

**输入**：`spec.md`（已澄清）、`plan.md`、`docs/design/DESIGN.md`、`docs/design/ui-design-spike-brief.md`、仓库外 OpenDesign 原型 `/Users/yigui/code/PatrolX-design/prototypes/`

以下 9 项研究结论已并入 `plan.md`，并作为 `tasks.md` 的实现依据。每项给出决定、理由与被排除的方案。

---

## R1 视觉基线如何落地

**Decision**：用 AntD `ConfigProvider` theme token（`web/src/App.tsx`）承载全局 token，再用 `web/src/theme.css` 的语义变量承载 AntD token 覆盖不到的间距/圆角/状态语义，新增少量基类（页头、区块标题、元数据行、结论区）。不引入新样式库。

**Rationale**：`App.tsx` 已有 `ConfigProvider`（`colorPrimary` / `borderRadius` / `colorBgLayout`），`theme.css` 已有 `--space-1..5`、`--radius-round`、`--border-color`、`--primary-soft*`。沿用它即可覆盖全站，且 AntD 5 的 token 是官方支持的定制入口，改造成本与回归风险最低。

**Alternatives considered**：
- 引入 Tailwind / CSS-in-JS：新增依赖与构建配置，违反"不新增 UI 库"，且与 AntD 体系双轨并存会放大不一致。
- 每页写内联 `style`：现状问题的来源之一，无法形成可复用的语义变量与走查清单。
- 只改 `DESIGN.md` 不改代码：无法解决实际观感。

---

## R2 任务列表用什么承载行式结构

**Decision**：AntD `Table` + 自定义单元格 + `expandable` 行展开。列顺序为"任务（名称 + ID + 失败原因摘要）/ 状态摘要 / 元数据 / 时间与耗时 / 操作"；行展开承载数据准备状态、问题文件摘要与重试、失败日志入口。

**Rationale**：`Table` 天然提供列对齐、密度控制、分页、行展开与可访问性语义，正是 B 方向"密度与对齐"的载体；`InventoryPage` 等页面已在用 `Table`，风格一致。移除卡片网格后，"一行一个任务"的信息顺序可被固定下来。

**Alternatives considered**：
- 保留卡片网格 + 内部重排：卡片形态本身就让每个任务占满视觉宽度，异常任务无法"置顶一眼看到"。
- 自定义 `div` + grid：需自建分页/展开/键盘可访问性，重复造轮子。
- AntD `List`：行内多列对齐需要自行处理，不如 `Table` 直接。

---

## R3 状态摘要用什么组件

**Decision**：新增共享 `web/src/components/StatusDistribution.tsx`：分段条（`getHealthBarSegments` 复用）+ 非零状态计数标签；0 值状态不渲染任何占位。列表行用紧凑形态，详情页用完整形态。

**Rationale**：现状"五色等权块"在 0 值上也占用同样视觉权重，是"乱"的最主要来源。分段条 + 非零计数同时表达比例与绝对量，且一份实现可同时服务列表和详情，避免两处漂移。

**Alternatives considered**：
- 只保留数字统计：丢失分布比例，异常集中度不可见。
- 只保留条形图：缺失精确数值。
- 在页面内各写一份：必然产生一致性问题。

---

## R4 任务结论如何推导

**Decision**：新增纯函数 `web/src/utils/taskConclusion.ts` 的 `deriveTaskConclusion`，输入任务状态、失败原因/阶段与 `TaskStats`，输出"结论标签 + 一句话结论 + 语气（danger/warning/success/processing/neutral）+ 下一步动作提示"；单测覆盖全部分支。

**Rationale**：结论需要覆盖"全部通过 / 需要关注 / 任务失败 / 执行中 / 排队中"五种形态，散落在 JSX 中无法被完整测试。抽成纯函数后可用 Vitest 穷举分支，页面只负责渲染。

**Alternatives considered**：
- 在 `TaskDetailPage` 内联 `if/else`：分支多、难测、难复用（列表行也需要同源结论）。
- 使用正则解析后端文案：脆弱且违反"展示由既有字段推导"。

---

## R5 任务详情首屏结构

**Decision**：面包屑 → 结论 Hero（结论标签 + 一句话 + 状态计数 + 主操作 + 关键元数据）→ 重点关注列表（fail → warn，最多 5 条 + 其余折叠）→ 全部规则（按类别折叠，默认展开含异常的分组）→ 既有 Tab（执行日志 / 设备台账 / 报告预览）→ 折叠的执行与技术信息。删除 `TaskHealthPanel` 中与"重点关注"重复的 Alert 提示条。

**Rationale**：符合 SC-002（首屏含结论、计数、主操作、元数据）与 SC-005（同一事实不重复表达）。既有 Tab、筛选、搜索、排序、类别筛选、单规则重跑、设备编辑、重建全部保留，改动集中在信息组织而非能力。

**Alternatives considered**：
- 保留 4 概览大数字 + 5 状态块：等权重复即当前痛点。
- 用抽屉/弹窗展示详情：改变路由与深链语义，超出边界。

---

## R6 规则详情结构

**Decision**：面包屑 → 结论区（状态 + 严重度 + 结论摘要 + 重跑入口 + 建议）→ 源文件匹配 → 发现列表（skip 必显 `skip_reason`）→ 证据面板（`MetricPanel` / `MeasurementInspectionPanel` / `AlarmFlappingPanel` 按规则条件渲染）→ 折叠技术信息。指标表默认精简列，"显示全部列"可切换。

**Rationale**：规则详情是排查闭环最后一跳，当前平铺结构让用户"在指标表里找结论"。既有面板能力与数据来源完全保留，只重排顺序与默认折叠，回归面可控。

**Alternatives considered**：
- 重写面板内部：超出展示层边界，且会引入规则判定回归风险。
- 增加新的规则专用页面：与既有路由/深链冲突。

---

## R7 其余 7 个页面做到什么程度

**Decision**：设备台账、基础指标、规则管理、数据字典、报告、日志、用户管理页面只套用统一基线（`PageHeader`、卡片/分隔线、状态标签、操作分层、空 / 加载 / 错误态），不重排信息架构。顺带修正 `InventoryPage` 与 `InventoryDevicePage` 默认分页 20 → 10。

**Rationale**：用户反馈是"都乱"，跨页面一致性必须解决；但结构性重排会让本轮验收面失控（已由 clarify 确认）。分页默认值修正属宪法"数据分页默认"的合规修复，代价极小。

**Alternatives considered**：
- 全部页面一起重排：本轮体量与回归风险不可控。
- 完全不碰其余页面：无法回应"都乱"。

---

## R8 测试与展示效果证据如何做

**Decision**：Vitest 单测覆盖 `deriveTaskConclusion` 全分支、`StatusDistribution` 0 值不渲染、任务列表异常置顶、详情结论 Hero、规则详情证据顺序、分页默认值；Playwright E2E 等价迁移受影响用例（`task-home`、`task-detail*`、`task-actions`、`task-delete-confirm`、`report-page`、`alarm-flapping-rule-detail` 等）并新增四类断言；截图归档 `web/e2e/screenshots/`，并用 `python build.py verify` 的真实样例包复现界面结论。

**Rationale**：符合 FR-030（等价替换而非删除覆盖）与 SC-007（测试通过 + 截图证据）。四类新增断言一对一对应四个用户故事，保证每个故事可独立验证。

**Alternatives considered**：
- 只改断言不新增：无法证明"主次"确实被解决。
- 只做人工走查：无法防止回归。

---

## R9 设计规范如何回写

**Decision**：实现完成时同步更新 `docs/design/DESIGN.md`：补充页面头/区块标题字号与间距刻度、结论区规范、状态分布 0 值规则、操作分层、行式任务列表模式与四类页面模式。

**Rationale**：FR-001 要求基线成为长期约束；`DESIGN.md` 已是权威 UI 规范文档，回写后才能约束后续功能，避免"改完又乱回去"。

**Alternatives considered**：
- 只写代码不留规范：下一个功能会重新发散。
- 新建独立规范文档：与既有 `docs/design/DESIGN.md` 权威地位冲突。
