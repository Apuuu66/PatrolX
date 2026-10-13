---
spec: 031-ui-information-hierarchy
branch: feature/031-ui-information-hierarchy
worktree: .worktrees/feature/031-ui-information-hierarchy
verified_at: 2026-10-10
---

# 实现回合验证记录：主界面信息层级重构

## 一、前置检查

```text
git worktree list
/Users/yigui/code/PatrolX                                                 f3b9141 [main]
/Users/yigui/code/PatrolX/.worktrees/feature/030-alarm-flapping           3a41dfa [feature/030-alarm-flapping]
/Users/yigui/code/PatrolX/.worktrees/feature/031-ui-information-hierarchy 84077d2 [feature/031-ui-information-hierarchy]

git branch --show-current
feature/031-ui-information-hierarchy
```

- 当前目录即本功能唯一 worktree，检出分支与实现分支一致。
- Speckit 产物（spec/plan/tasks/analyze review 结果）已在 `main` 提交（`f3b9141`），实现分支由该提交派生。
- 复用既有 worktree，未重复创建。

## 二、质量门禁结果

| 命令 | 结果 |
| --- | --- |
| `python build.py web-build` | 通过（`tsc -b` + `vite build`） |
| `python build.py lint` | `All checks passed!` / `181 files already formatted` |
| `python build.py test` | `576 passed`（46.2s） |
| `python build.py e2e` | `34 passed`（25.7s） |
| `python build.py verify` | 通过：`task-zzapp01bcn_app_problem_scene_333`，`pass=4 warn=3 fail=5 error=0 skip=2` |
| `cd web && npx vitest run` | `30 passed`（单元/组件测试） |

补充说明：`web/e2e/theme.spec.ts` 新增“布局在 1280px 与 1920px 下符合宽度约束”用例，覆盖 FR-028 与 contracts/ui-baseline §6。

## 三、SC-001 ~ SC-007 走查结果

| 编号 | 判据要点 | 证据 | 结果 |
| --- | --- | --- | --- |
| SC-001 | 1440×900 首屏可见概览条与种子任务、无横向滚动 | `e2e/task-home.spec.ts`；本回合视口检查（1440 下页面与表格内部均无横向滚动）；截图 `01-task-list-1440x900.png` | 通过 |
| SC-002 | 任务详情首屏可见结论标签、一句话结论、状态计数、主操作、关键元数据 | `e2e/task-detail.spec.ts`、`e2e/task-detail-states.spec.ts`；截图 `02-task-detail-1440x900.png` | 通过 |
| SC-003 | 失败任务位于第一行、行内原因摘要、进入失败日志 ≤2 次点击 | `e2e/task-home.spec.ts`（首行断言 + 失败日志 1 次点击） | 通过 |
| SC-004 | 任务列表 → 失败规则详情 ≤3 次点击 | `e2e/task-home.spec.ts`（行内“详情”1 次）+ `e2e/alarm-flapping-rule-detail.spec.ts`（规则行“详情”第 2 次）；截图 `03-rule-detail-1440x900.png` | 通过 |
| SC-005 | 同一事实不得两处等权重复表达 | 任务详情仅结论 Hero 给结论与计数，“重点关注”只列异常规则；`e2e/task-detail.spec.ts`“全通过且无关注项时只保留结论 Hero 与全部规则” | 通过 |
| SC-006 | 其余主页面逐页走查通过统一基线清单 | 阶段 6 的 `PageHeader`/状态/操作/空加载错误态改造 + `e2e/inventory.spec.ts`、`e2e/page-states.spec.ts`、`e2e/theme.spec.ts` 自动化断言；截图 `04-inspectors-1440x900.png` | 通过 |
| SC-007 | 测试与构建全绿，真实样例包结论与报告一致并留截图 | 见第二、四节 | 通过 |

## 四、真实样例包一致性（SC-007）

1. `python build.py verify` 产出 `output/task-zzapp01bcn_app_problem_scene_333/`。
2. 同一事实三处对齐：

| 来源 | 通过 | 告警 | 失败 | 异常 | 跳过 |
| --- | --- | --- | --- | --- | --- |
| `output/<task_id>/task.json` | 4 | 3 | 5 | 0 | 2 |
| `output/<task_id>/report.html` | 4 | 3 | 5 | 0 | 2 |
| 界面（任务列表行内状态摘要） | 4 | 3 | 5 | 未渲染（0 值） | 2 |

3. 以真实 `output/` 启动 API + Web 后走查：任务详情结论 Hero 显示「需要关注 · 发现失败 5 条、异常 0 条规则结果，需要处理。」，与报告结论一致。
4. 截图证据保存在 `web/e2e/screenshots/`（本地证据，不提交）：

| 文件 | 对应 | 说明 |
| --- | --- | --- |
| `01-task-list-1440x900.png` | SC-001、SC-003 | 任务列表异常置顶与行内摘要 |
| `02-task-detail-1440x900.png` | SC-002、SC-005 | 任务详情首屏结论 Hero |
| `03-rule-detail-1440x900.png` | SC-004 | 规则详情结论 → 源文件匹配 → 发现 |
| `04-inspectors-1440x900.png` | SC-006 | 基线页面（规则管理） |

## 五、视口与响应式检查（FR-028）

| 视口 | 页面级横向滚动 | 任务列表表格（可视 / 内容） | 内容区宽度 |
| --- | --- | --- | --- |
| 1280×900 | 无（`scrollWidth == clientWidth == 1280`） | 982 / 1098，需要表格内部横向滚动，操作列固定在右侧 | 1032px |
| 1440×900 | 无（`scrollWidth == clientWidth == 1440`） | 1142 / 1142，无内部滚动 | 1192px |
| 1920×900 | 无（`scrollWidth == clientWidth == 1920`） | 1550 / 1550，无内部滚动 | 1600px（上限），页头与内容区左边缘对齐 |

覆盖页面：任务列表、任务详情、规则详情、规则管理、设备台账。

## 六、越界与洁净度检查（FR-027、FR-029、T048）

- 未修改 `docs/api/openapi.yaml`，未修改后端、规则与路由实现。
- 未新增依赖、未新增前端路由。
- 未暂存 `web/e2e/screenshots/`、临时脚本与测试产物；`web/test-results/`、`web/playwright-report/` 走既有 `.gitignore`。

## 七、例外与说明

1. 1280px 下任务列表 5 列总宽超过可视区，按 AntD 既有模式使用表格内部横向滚动并固定操作列；页面本身不出现横向滚动，符合 contracts/ui-baseline §6 的页面级约束，该约定已回写 DESIGN.md。
2. 1920px 下新增 `.app-shell-inner`（`max-width: 1600px`）约束，页头与内容区使用同一容器宽度，避免内容无限拉伸。
3. 固定列遮挡缺陷（1440 下时间列被操作列覆盖）在本回合修复：任务列 280、状态摘要 190、元数据 200、时间与耗时 190、操作 190。

## 八、2026-10-12 修订验证（任务列表行内信息与操作收敛）

**修订范围**：FR-006（列顺序新增"数据准备"）、FR-011（固定列 + 列内弹层，不使用行展开；删除失败操作列就地重试）、FR-012（去掉任务级"重跑"、"全量重建"更名"重建"并收进 `⋯` 菜单）。产物同步见 `spec.md` 修订记录与 `tasks.md` 修订记录。

**历史说明**：本节"重建与删除收进 `⋯` 菜单、报告 hover / 聚焦显现"的结论已在 2026-10-13 修订中调整为操作列平铺（FR-012 修订），以第九节为准。

**工作区形态**：本修订为小改动，按 AGENTS.md「小改动不创建 worktree」，在主工作区 `main` 直接完成实现与验证；未触碰 OpenAPI 与后端。

| 命令 | 结果 |
| --- | --- |
| `cd web && npm run build` | 通过（`tsc -b` + `vite build`，4.7s，仅既有 chunk 体积提示） |
| `cd web && npm test` | 通过：24 files / 106 passed |
| `npx playwright test e2e/task-actions.spec.ts e2e/task-home.spec.ts e2e/upload-precheck.spec.ts` | 通过：14 passed |
| `.venv/bin/python build.py lint` | `All checks passed!` / `182 files already formatted` |
| `.venv/bin/python build.py test` | 通过：585 passed |

**修订后断言要点**：

- `e2e/task-actions.spec.ts`：操作列不出现"重跑"；`⋯` 菜单内"重建"可及且为危险样式；重建二次确认按钮文案为"重建"。
- `e2e/task-home.spec.ts`：列表无 `.ant-table-row-expand-icon`（无行展开）；"数据准备"列摘要常驻可见，问题文件明细在列内弹层打开。
- `web/src/pages/TaskListPage.test.tsx`：删除失败不再依赖行展开区，操作列就地渲染"删除失败"并可重试。

**例外说明**：E2E 中两字中文按钮（"取消"）经 AntD 处理会插入空格，断言改用 `/取\s*消/` 宽松匹配，与既有 `web/e2e/task-delete-confirm.spec.ts` 惯例一致；属选择器写法调整，未降低行为覆盖。

## 九、2026-10-13 修订验证（任务列表操作列不再收纳）

**修订范围**：FR-012（操作列改为详情、报告 / 失败日志、重建、删除全部平铺常驻；移除 `⋯` 更多菜单与"报告"的 hover / 聚焦显现；重建、删除继续二次确认）、US1 验收场景 4。产物同步见 `spec.md` 与 `tasks.md` 修订记录。

**工作区形态**：本修订为小改动，按 AGENTS.md「小改动不创建 worktree」，在主工作区 `main` 直接完成实现与验证；未触碰 OpenAPI 与后端。

| 命令 | 结果 |
| --- | --- |
| `cd web && npm run build` | 通过（`tsc -b` + `vite build`，3.7s，仅既有 chunk 体积提示） |
| `cd web && npm test` | 通过：27 files / 121 passed |
| `npx playwright test e2e/task-actions.spec.ts e2e/task-home.spec.ts e2e/task-delete-confirm.spec.ts` | 通过：13 passed（18.1s） |
| `.venv/bin/python build.py e2e` | 通过：默认 57 passed（38.4s）+ 留存 5 passed（14.0s） |
| `.venv/bin/python build.py lint` | `All checks passed!` / `193 files already formatted` |
| `.venv/bin/python build.py test` | 通过：635 passed（48.3s） |

**修订后断言要点**：

- `e2e/task-actions.spec.ts`：失败任务行操作列平铺"详情 / 失败日志 / 重建 / 删除"，行内不存在"更多操作"触发器与任务级"重跑"；已完成任务"报告"常驻可见并一次点击进入报告页。
- `e2e/task-home.spec.ts`：失败行四个操作与已完成行"报告 / 重建 / 删除"均平铺可见；列表仍无 `.ant-table-row-expand-icon`。
- `e2e/task-delete-confirm.spec.ts`：行内"删除"按钮仍需二次确认，取消后任务仍在列表。
- `web/src/pages/TaskListPage.test.tsx`：单测断言操作列无"更多操作"按钮，四个操作直接可见。

**例外说明**：操作列宽度由 190px 调整为 280px：实测失败行四操作约 204px，叠加"删除失败"重试入口约 276px；280px 保证任何状态下操作单行平铺不换行、不截断。
