# 实现计划：主界面信息层级重构（巡检控制台方向）

**分支**：`031-ui-information-hierarchy` | **日期**：2026-10-10 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/031-ui-information-hierarchy/spec.md` 的功能规格

## 摘要

按 OpenDesign 探索确认的组合方向重构前端展示层：任务列表改为单表行式列表并异常置顶（B），任务详情改为一屏结论优先（C），规则详情按"结论 → 证据 → 建议"重排（B），其余 7 个主页面统一视觉基线（A 的克制 AntD 样式）。

技术方案不走新框架：以 AntD `ConfigProvider` 主题 token + `web/src/theme.css` 语义变量承载视觉基线，新增少量共享展示组件（状态分布、结论区、页面头、元数据行），把"结论"与"状态摘要"从页面内联逻辑抽成可单测的纯函数。任务列表用 AntD `Table` 承载行式结构（列对齐、行展开承载数据准备详情、行内 primary/secondary 操作分层），不再保留卡片形态。

本功能**不改 OpenAPI、不改后端、不改规则**；所有展示结论由既有接口字段推导。E2E 与单测同步迁移，新增"异常置顶 / 结论 Hero / 规则详情证据顺序 / 其余页面基线"四类断言，并以 1440×900 截图作为展示效果证据。

## 技术上下文

**语言/版本**：TypeScript 5.6 + React 18.3 + Vite 5.4（`web/`）

**主要依赖**：Ant Design 5.21、`@ant-design/icons` 5.5、dayjs、ECharts 5.5、react-router-dom 6.26；**不新增依赖**

**存储**：不适用（纯展示层；数据来自既有 FastAPI 接口与本地 CLI 输出）

**测试**：Vitest（组件/工具单测）+ Playwright E2E（`web/e2e`，`python build.py e2e`）+ `python build.py web-build`

**目标平台**：桌面浏览器（1280–1920 宽），本地模式与在线模式共用同一前端

**项目类型**：离线巡检系统的 Web 前端（React SPA + Vite）

**性能目标**：任务列表与详情保持首屏 < 1s 渲染（种子数据规模）；不引入新的阻塞请求；不改动既有轮询策略

**约束条件**：不改路由与 URL 语义；不新增 OpenAPI 字段；状态色沿用 `docs/design/DESIGN.md`；默认分页 10 条（宪法）；桌面优先不做移动端

**规模/范围**：3 个核心页面结构性重构 + 7 个页面基线统一 + 1 份设计规范更新 + E2E/单测迁移；不含后端、报告模板与规则逻辑改动

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 处理 |
| --- | --- | --- |
| 离线优先 | 通过 | 不引入任何在线采集或外部数据源；只消费既有接口/输出 |
| 一个包、一个任务 | 通过 | 展示层不改变任务隔离模型，不新增目录身份 |
| 契约驱动 | 通过 | 不新增或修改 API；前端不手写与 OpenAPI 不一致的调用；如展示确需新字段必须先改 `docs/api/openapi.yaml`（本轮无此需求） |
| 模式同构 | 通过 | 前端对本地/在线任务使用同一展示契约；两模式差异仅体现在"模式"标注 |
| 增量重跑 | 通过 | 单规则重跑入口与行为保持不变，仅位置回归首屏 |
| 数据分页默认 | 通过 | 任务列表保持每页 10 条；基线统一时修正 `InventoryPage` / `InventoryDevicePage` 的 20 条默认值为 10，并补断言 |
| 容错 | 通过 | skip 必须显示 `skip_reason`；加载失败提供统一重试；空列表提供上传入口 |
| 轻量默认 | 通过 | 不新增依赖、不新增运行时服务；沿用 AntD + ECharts |
| 语言策略 | 通过 | 文档、注释与界面文案使用中文；标识符与接口字段使用英文 |
| 前端质量门禁 | 通过 | 执行 `python build.py web-build`、`python build.py e2e`、`python build.py lint`、`python build.py test` |
| 新功能验证与展示效果 | 通过 | 本功能为展示层重构，不新增数据语义与交互能力；展示效果复用既有代表性样例包 `ZZapp01BCN_app_Problem_scene_333.zip` 与 E2E 种子任务（`task-home-failed` 等）复现，故不扩充 `tests/fixtures/make_real_package.py`，证据见 T044/T045/T046 |

**阶段 1 复查**：设计未引入新契约、新依赖与新路由；"结论"全部由既有字段推导；分页默认修正属宪法合规修复，与 FR-013/FR-025 一致。结论不变。

**展示效果合规说明**：宪法“新功能验证与展示效果”要求新增功能扩充代表性样例包。本功能不新增交互能力与数据语义，属既有能力的信息层级重构，因此展示效果以既有样例包与 E2E 种子任务复现即满足要求；该判定写入任务 T041/T044/T045/T046，并在 analyze 报告中确认。

## 阶段 0 研究结论

详见 [research.md](research.md)。关键决定：

1. **样式落地**：AntD theme token + `theme.css` 语义变量，不引入 CSS-in-JS/Tailwind（R1）。
2. **行式列表载体**：AntD `Table` + 行内自定义单元格 + `expandable` 承载数据准备详情（R2）。
3. **状态摘要组件**：新增共享 `StatusDistribution`（分段条 + 非零计数），替换列表/详情中的等权五色块（R3）。
4. **结论推导**：新增纯函数 `deriveTaskConclusion`（状态 + 规则计数 → 结论标签/一句话/语气），单测覆盖全部分支（R4）。
5. **任务详情结构**：结论 Hero → 重点关注列表 → 全部规则（按类别折叠）→ 折叠的执行/技术信息；删除与列表重复的提示条（R5）。
6. **规则详情结构**：结论 + 建议 → 源文件匹配 → 发现 → 证据面板 → 折叠技术信息；既有面板组件内部能力不动（R6）。
7. **其余页面基线**：只统一页头、卡片、状态标签、操作分组与空/加载/错误态；不改信息架构；顺带修正分页默认值（R7）。
8. **测试迁移**：既有 E2E 选择器等价替换；新增 4 类断言；截图作为展示效果证据（R8）。
9. **设计规范回写**：`docs/design/DESIGN.md` 增补布局、字号、组件与页面模式基线，作为长期约束（R9）。

## 阶段 1 设计

### 1. 视觉基线（`docs/design/DESIGN.md` + `web/src/theme.css` + `web/src/App.tsx`）

- 在 `DESIGN.md` 固化：页面标题/区块标题/正文/次要字号；间距刻度；卡片与分隔线；状态语义色与标签并存规则；操作分层（每屏 1 主操作）；技术信息折叠与复制规则；四类页面的标准模式（列表 / 详情 / 证据 / 配置）。
- `theme.css` 扩展语义变量：字号层级、间距刻度、卡片内边距、状态色与浅底、行高与最小行高，供页面与组件统一引用。
- `App.tsx` 的 `ConfigProvider` token 与 `theme.css` 变量保持单一来源，避免页面内联魔法数字；既有 `--space-*` 变量保留兼容。

### 2. 共享展示组件（`web/src/components/`）

- `PageHeader`：面包屑 / 标题 + 状态 + 一句话结论 + 主操作 + 次要操作收纳区。
- `StatusDistribution`：分段状态条 + 非零计数 chips；支持点击筛选与 `aria-pressed`；0 值不渲染为独立彩色块。
- `ConclusionHero`（任务详情用）：结论标签 + 一句话结论 + 状态计数 + 主操作 + 关键元数据网格。
- `MetadataList`：label（次要）/ value（主要）键值展示，长值截断 + 可复制/提示。
- `TaskRowActions` 或等价封装：行内"详情 / 报告 / 失败日志"与 `⋯` 菜单（重跑、增量重建、全量重建、删除）。

### 3. 任务列表（`web/src/pages/TaskListPage.tsx`）

- 顶部：`PageHeader` + 概览条（总量 + 状态分布 + 注册规则/规则结果/发现数），上传数据包为唯一主操作。
- 主体：`Table` 行式列表，列 = 任务（名称 + ID + 失败原因摘要）/ 状态摘要（`StatusDistribution`）/ 元数据（省份·运营商·网元·版本·设备）/ 时间与耗时 / 操作；`fail`、`error` 行置顶并高亮（默认排序，无切换控件）。
- 行展开：数据准备状态、问题文件摘要与重试入口、失败日志入口。
- 保留：状态筛选 chips（排队中/执行中/已完成/失败 + 全部）、搜索、分页（默认 10）、轮询、上传表单。
- 移除：任务卡片网格、等权五色状态块、卡片内散落的删除错误面板（改为行内/展开区表达，保留 `TaskDeleteError` 语义与重试删除）。

### 4. 任务详情（`web/src/pages/TaskDetailPage.tsx` 及 `components/task-detail/`）

- 结构：面包屑 → 结论 Hero（`deriveTaskConclusion`）→ 重点关注列表（fail → warn，最多 5 条 + 其余折叠）→ 全部规则（按类别分组折叠，默认展开含异常分组）→ 执行日志 / 设备台账 / 报告预览（既有 Tab 保留）→ 折叠的执行与技术信息。
- 删除重复：`TaskHealthPanel` 中的黄色 `Alert` 提示条与"重点关注"重复，改为状态计数块（可点选筛选）；`SummaryCards` 在详情页的 4 大数字改为概览条。
- 保留：状态筛选联动、搜索、排序、类别筛选、单规则重跑、设备信息编辑、增量/全量重建、失败日志跳转。

### 5. 规则详情（`web/src/pages/RuleDetailPage.tsx`）

- 结构：面包屑 → 结论区（状态 + 严重度 + 结论摘要 + 重跑入口 + 建议）→ 源文件匹配 → 发现列表（skip 必显原因）→ 证据面板（`MetricPanel` / `MeasurementInspectionPanel` / `AlarmFlappingPanel` 按规则条件渲染）→ 折叠的技术信息。
- 指标表默认精简列，"显示全部列"可切换（既有实现保留）。
- 不改规则面板内部判定与数据来源。

### 6. 其余页面基线统一（`InventoryPage`、`InventoryDevicePage`、`MeasurementUnitsPage`、`InspectorsPage`、`DictsPage`、`ReportPage`、`LogsPage`、`UsersPage`）

- 统一 `PageHeader`、卡片/分隔线、状态标签、操作分层与空/加载/错误态文案风格；不改信息架构与功能。
- 修正 `InventoryPage` / `InventoryDevicePage` 默认分页 20 → 10（宪法"数据分页默认"），补单测断言。

### 7. 测试与证据

- 单测（Vitest）：`deriveTaskConclusion` 全分支、`StatusDistribution` 0 值不渲染、`TaskListPage` 异常置顶排序、`TaskDetailPage` 结论 Hero 渲染、规则详情证据顺序、分页默认值。
- E2E（Playwright）：迁移受影响用例（`task-home`、`task-detail*`、`task-actions`、`task-delete-confirm`、`report-page`、`alarm-flapping-rule-detail` 等），新增"异常置顶 / 结论 Hero / 规则详情顺序 / 其余页面基线"断言；保留删除确认、重跑、筛选、页面状态等既有覆盖。
- 展示效果证据：`python build.py e2e` 全绿 + 1440×900 截图（任务列表 / 任务详情 / 规则详情 / 1 个基线页面）归档到 `web/e2e/screenshots/`，并用 `python build.py verify` 的真实样例包任务复现同一界面结论。

## 项目结构

### 文档（本功能）

```text
specs/031-ui-information-hierarchy/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui-baseline.md
└── tasks.md            # $speckit-tasks 生成
```

### 源代码（仓库根目录）

```text
web/src/
├── App.tsx                          # ConfigProvider token（基线单一来源）
├── theme.css                        # 语义变量（字号/间距/状态/行高）
├── components/
│   ├── PageHeader.tsx               # 新增：统一页头
│   ├── StatusDistribution.tsx       # 新增：状态条 + 非零计数
│   ├── ConclusionHero.tsx           # 新增：任务结论首屏
│   ├── MetadataList.tsx             # 新增：键值元数据
│   ├── SummaryCards.tsx             # 调整：概览条形态
│   └── task-detail/                 # TaskHealthPanel / RuleBrowser / TaskMetaPanel 等调整
├── pages/
│   ├── TaskListPage.tsx             # 行式列表 + 异常置顶
│   ├── TaskDetailPage.tsx           # 结论 Hero + 分组折叠
│   ├── RuleDetailPage.tsx           # 结论/证据/建议顺序
│   └── {Inventory,InventoryDevice,MeasurementUnits,Inspectors,Dicts,Report,Logs,Users}Page.tsx
└── utils/
    ├── taskConclusion.ts            # 新增：结论推导纯函数
    ├── taskDisplay.ts               # 复用/扩展：状态分布与概览
    └── taskCard.ts                  # 复用：元数据与耗时格式

web/e2e/                             # 断言迁移 + 新增基线用例 + 截图证据
docs/design/DESIGN.md                # 基线回写（长期约束）
```

**结构决策**：沿用现有 `web/src/{pages,components,utils}` 分层；新增组件放 `components/` 顶层（跨页面复用），任务详情专用组件留在 `components/task-detail/`；结论推导等纯逻辑放 `utils/` 以便单测。

## 复杂度跟踪

> 本功能无宪法违规项，无需填写。
