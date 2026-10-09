# 实现计划：界面降噪与一致性精修

**分支**：`033-ui-refinement`（实现目标名；规划在 main 完成，实现阶段创建独立 worktree） | **日期**：2026-10-10 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/033-ui-refinement/spec.md` 的功能规格

## 摘要

在 031 已完成的信息层级骨架上，针对 18 条走查建议做一轮展示层精修：状态分布统一"异常优先 + 弱化通过/跳过 + Tooltip 占比"；概览指标补口径说明；结论句与元数据去掉零值与空占位；时间列、行操作、重点关注去重降低首屏噪音；规则详情把证据结构化、把源文件匹配降为一行；新增表格密度切换与规则管理页细节；统一顶栏/侧边栏/术语与可访问性色板；上传弹窗增加任务 ID 预览与前置校验。

全部改动限定在前端展示层与 `docs/design/DESIGN.md`，不新增或修改 OpenAPI 契约、不改后端执行链路、不改路由与深链。

## 技术上下文

**语言/版本**：TypeScript 5.x（前端）；文档为 Markdown。

**主要依赖**：React 18、Vite、Ant Design 5、ECharts、dayjs、React Router；测试为 Vitest + Testing Library + Playwright。不新增依赖。

**存储**：浏览器 `localStorage` 保存表格密度偏好（key `patrolx.tableDensity`）；无后端存储变更。

**测试**：`npx vitest run`（组件/工具单测）、`npx playwright test`（E2E 与视口回归）、`python build.py lint / test / web-build`（合入门禁）。

**目标平台**：桌面浏览器（1280px ~ 1920px），Chrome/Chromium 为主（Playwright）。

**项目类型**：Web 前端（离线巡检系统的展示层）。

**性能目标**：无新增接口调用；纯展示层转换（排序、拆分、格式化）在既有渲染路径内完成，不引入额外网络或大数据遍历。

**约束条件**：

- 不修改 `docs/api/openapi.yaml`；不新增前端 API 调用；不改变既有错误码语义。
- 状态语义色沿用 DESIGN.md；文字色必须满足 WCAG AA，填充色可保持标准值。
- 1280/1920 无页面级横向滚动；1920 内容宽度 ≤ 1600px。
- 既有筛选、搜索、分页、轮询、深链、单规则重跑、报告与删除/重建确认行为不变。

**规模/范围**：6 个用户故事、30 条功能需求；涉及 4 个主页面、1 个上传弹窗、1 个布局与 1 份设计规范。

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后复核。*

| 宪法条款 | 检查结论 |
| --- | --- |
| 离线优先（不连接被检系统、不新增采集） | 通过：不新增任何网络/采集能力；仅本地展示层改动。 |
| 一个包、一个任务 | 通过：上传预检不改变"包名派生 task_id"的隔离模型，仅提前展示派生结果。 |
| 契约驱动 | 通过：不修改 OpenAPI/Pydantic；不新增前端接口调用。若实现中发现需要新字段，必须停下先改契约（预期不会发生）。 |
| 源文件显式匹配 / 规则架构 / 解压与执行编排 | 通过：不触碰后端规则、注册表、执行器与解压逻辑。 |
| 幂等与可追溯 | 通过：术语与展示只改变呈现，不改变数据落盘与任务标识。 |
| 轻量默认 | 通过：不新增依赖；密度偏好使用浏览器本地存储。 |
| 时间、命名与日志 | 通过：前端相对时间仅为展示，底层仍为 UTC `*_at` 字段；不新增时间字段。 |
| 语言策略 | 通过：文档与文案使用中文，标识符与接口字段保持英文。 |
| 新功能验证与展示效果 | 通过：每个用户故事至少 1 个自动化用例与 1 张走查截图；复用既有代表性样例包与 E2E 种子任务，不新增数据语义。 |
| 数据分页默认 | 通过：分页与页大小行为不变，密度切换不重置分页。 |
| 双模式兼容 | 通过：仅前端展示层，本地与在线模式共用同一套页面。 |

**展示效果合规说明**：宪法“新功能验证与展示效果”要求新增功能扩充代表性样例包。本功能为纯展示层精修，不新增巡检数据语义；展示效果以既有代表性样例包 `ZZapp01BCN_app_Problem_scene_333.zip` 与既有 E2E 种子任务复现，密度 / 复制 / 展开等交互由 `python build.py e2e` 覆盖；上传预检使用 `web/e2e/start-backend.sh` 确定性生成的 `.tmp/inventory-e2e.zip` 与 Playwright 内存文件（空文件 / 非法扩展名）覆盖边界，同名冲突由同一文件二次上传复现，因此不扩充 `tests/fixtures/make_real_package.py`（与 031 同一判定口径）。该判定写入任务 T052、T054 并在 analyze 报告中确认。

**阶段 1 复核**：设计产物（data-model / contracts / quickstart）未引入新的契约字段、后端改动或依赖，门禁保持通过，无需复杂度豁免。

## 项目结构

### 文档（本功能）

```text
specs/033-ui-refinement/
├── plan.md              # 本文件
├── research.md          # R1-R17 技术决策
├── data-model.md        # 展示层模型与校验规则
├── quickstart.md        # 验证与走查步骤
├── contracts/
│   └── ui-refinement.md # UI 行为契约（无 API 契约变更）
├── checklists/
│   └── requirements.md  # 规格质量检查（16/16）
└── tasks.md             # 阶段 2 输出（/speckit.tasks）
```

### 源代码（仓库根目录）

```text
web/
├── src/
│   ├── components/
│   │   ├── StatusDistribution.tsx        # 排序、弱化色、Tooltip、占比
│   │   ├── StatusBadge.tsx               # SeverityTag 轻量变体
│   │   ├── MetadataList.tsx              # 空值过滤与"更多元数据"承载
│   │   ├── ConclusionHero.tsx            # 结论句/元数据走查点
│   │   ├── PageHeader.tsx                # 页面上下文（顶栏复用）
│   │   ├── DensitySegmented.tsx          # 新增：密度切换控件
│   │   ├── CopyTextButton.tsx            # 新增：复制反馈
│   │   ├── FindingItem.tsx               # 新增：结构化发现条目
│   │   └── task-detail/RuleBrowser.tsx   # 重点关注去重
│   ├── hooks/useTableDensity.ts          # 新增：密度偏好持久化
│   ├── utils/
│   │   ├── taskDisplay.ts                # 分段排序与 emphasis
│   │   ├── taskConclusion.ts             # 非零结论句
│   │   ├── taskOverview.ts               # 新增：指标口径
│   │   ├── timeDisplay.ts                # 新增：相对时间
│   │   ├── statusTextColors.ts           # 新增：文本安全状态色与对比度
│   │   ├── findingEvidence.ts            # 新增：证据解析与高亮
│   │   └── uploadPrecheck.ts             # 新增：任务 ID 预览与校验
│   ├── pages/
│   │   ├── TaskListPage.tsx              # 概览/时间/操作/密度/上传
│   │   ├── TaskDetailPage.tsx            # 元数据与去重
│   │   ├── RuleDetailPage.tsx            # 源文件匹配与发现结构
│   │   └── InspectorsPage.tsx            # 时间/排序/编码/回滚
│   ├── layouts/MainLayout.tsx            # 顶栏与侧边栏
│   └── theme.css                         # 密度、弱化色、斜纹、等宽数字
├── e2e/
│   ├── task-home.spec.ts                 # 列表排序/操作/密度
│   ├── task-detail.spec.ts               # 结论/元数据/去重
│   ├── alarm-flapping-rule-detail.spec.ts# 规则详情结构
│   ├── page-states.spec.ts               # 规则管理与页面态（新增断言）
│   ├── table-density.spec.ts             # 新增：跨页密度偏好与记忆
│   ├── upload-precheck.spec.ts           # 新增：上传预检
│   └── theme.spec.ts                     # 视口回归扩展
docs/
└── design/DESIGN.md                      # 术语表、密度、对比度、操作分层回写
```

**结构决策**：沿用既有 `web/src/{components,hooks,utils,pages,layouts}` 分层；新增能力以小组件与纯函数工具落位，避免在页面内堆叠逻辑；设计规则统一回写 `docs/design/DESIGN.md`，不新增设计文档。

## 复杂度跟踪

无需豁免项。所有改动复用现有技术栈与组件，不新增依赖、不新增契约、不新增后端路径。
