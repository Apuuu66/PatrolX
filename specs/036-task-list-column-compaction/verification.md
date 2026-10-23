# 实现验证：任务列表列宽压缩（036）

**功能**：036-task-list-column-compaction | **日期**：2026-10-23
**实现分支 / worktree**：`feature-036-task-list-column-compaction` / `.worktrees/feature-036-task-list-column-compaction`
**变更范围**：`web/src/pages/TaskListPage.tsx`、`web/src/theme.css`、`web/src/pages/TaskListPage.test.tsx`、`web/e2e/task-home.spec.ts`、`docs/design/DESIGN.md`、`specs/036-*` 规划产物数值回写

## 1. 实现前置检查（AGENTS.md）

```bash
git worktree list
git branch --show-current
```

| 检查项 | 结果 |
| --- | --- |
| 当前目录是实现 worktree | ✅ `/Users/yigui/code/PatrolX/.worktrees/feature-036-task-list-column-compaction` |
| 检出分支正确 | ✅ `feature-036-task-list-column-compaction`（基于 `main` 的 `10d0d95`） |
| Speckit 产物已在 `main` 提交 | ✅ `10d0d95 docs(036): 规划任务列表列宽压缩` |
| 复用既有 worktree | ✅ 未重复创建 |

## 2. 质量门禁

| 命令 | 结果 |
| --- | --- |
| `cd web && npx vitest run` | ✅ 27 个文件 / 123 个用例通过（98.5s） |
| `.venv/bin/python build.py lint` | ✅ `All checks passed!`，193 files already formatted |
| `.venv/bin/python build.py test` | ✅ 681 passed, 2 warnings（50.01s） |
| `.venv/bin/python build.py web-build` | ✅ `tsc -b && vite build` 成功（3.91s，仅有 chunk 体积提示） |
| `.venv/bin/python build.py e2e` | ✅ 60 passed（38.9s）+ retention 5 passed（16.6s） |

## 3. 关键实测数据（SC-001、SC-002、SC-004）

Playwright 在真实 Chromium 中测得：

| 视口 | 页面级 `scrollWidth / clientWidth` | `.ant-table-content` `scrollWidth / clientWidth` | 声明表格宽 | 结论 |
| --- | --- | --- | --- | --- |
| 1440×900 | 1440 / 1440 | 1142 / 1142 | 1130px | 无内部横向滚动，6 列一屏可见 |
| 1280×900 | 1280 / 1280 | 1130 / 982 | 1130px | 148px 内部横向滚动；滚到底后操作列仍贴表格右缘（偏差 ≤ 2px） |

- 列头顺序实测：任务 → 状态摘要 → 数据准备 → 元数据 → 时间 → 操作（共 6 列）。
- 时间三段（`task-duration` → `task-last-run` → `task-created-at`）同处 `[data-testid="task-time"]` 单元格；单元格与整表内均无完整时间戳文本，完整时间只在 Tooltip 中。
- 操作列：详情 / 失败日志（失败任务）/ 重建 / 删除四个入口顶端坐标一致（单行不换行）；无「重跑」、无「更多操作」`⋯` 入口。

### 与规划的偏差（已按 research R2 回退处理）

规划期按“视口 − 侧栏 200 − Content 内边距 48”估算 1440 可用宽度为 1192px，**漏算卡体内边距 48px 与卡片边框 2px**。实现期实测 `.ant-table-content` 可用宽度为 **1142px**（与 `specs/031-ui-information-hierarchy/verification.md` 记录的 1142 / 1142 完全一致），原 1160px 合计宽在 1440 下产生 18px 内部横向滚动。

处置：按 R2“不得压缩操作列”的约束，把合计宽由 1160px 下调为 **1130px**——状态摘要 160→150、数据准备 170→160、元数据 150→140；任务 240、时间 160、操作 280 **保持不变**，1440 下留 12px 余量。需求口径（1440×900 无内部横向滚动）未变，回写位置：`contracts/task-list-compaction.md` §1、`research.md` R2、`data-model.md` §1/§4、`analysis.md` A2/A5、`plan.md` 第 3 条、`tasks.md` US1 目标与 T005、`docs/design/DESIGN.md` Task List 表与修订记录。

## 4. 展示效果证据（SC-008）

```bash
cd web && npx playwright test e2e/task-home.spec.ts
```

| 截图 | 内容 |
| --- | --- |
| `web/e2e/.tmp/036-task-list-1440.png` | 1440×900：6 列全部一屏可见，卡片内无内部滚动条，操作列贴右平铺 |
| `web/e2e/.tmp/036-task-list-1280.png` | 1280×900：出现内部滚动条（已滚到底），操作列仍固定在右侧可见，页面本身无横向滚动 |

截图目录 `web/e2e/.tmp/` 已列入 `.gitignore`；注意 `web/test-results/` 会被每次 Playwright 运行清空，不能存放证据。

## 5. 测试覆盖对照

| 用例 | 位置 | 覆盖 |
| --- | --- | --- |
| 任务列表收敛为 6 列，时间三段合并进同一单元格 | `web/src/pages/TaskListPage.test.tsx` | FR-001、FR-006~FR-010、FR-020、SC-003 |
| 元数据平铺 3 项，其余进入更多元数据且空值不渲染 | `web/src/pages/TaskListPage.test.tsx` | FR-011~FR-013、SC-006 |
| 最多平铺 4 项，其余收进更多元数据 | `web/src/components/MetadataList.test.tsx` | FR-014（详情页默认值不变，既有用例即锁定） |
| 1440 视口一屏看全 6 列且表格内部无横向滚动 | `web/e2e/task-home.spec.ts` | FR-001、FR-002、FR-004、SC-001、SC-002 |
| 1280 视口下操作列贴右固定且入口不换行 | `web/e2e/task-home.spec.ts` | FR-003、FR-015、FR-016、SC-004 |
| 任务列表元数据平铺 3 项，其余收进更多元数据 | `web/e2e/task-home.spec.ts` | FR-011~FR-013、SC-006 |
| 行内元数据与操作分层保持可读（已按新结构等价替换） | `web/e2e/task-home.spec.ts` | FR-011、FR-016 |
| 任务列表行内删除 / 重建二次确认、删除失败重试 | `web/e2e/task-delete-confirm.spec.ts`、`task-actions.spec.ts` | FR-016、SC-005 |
| 布局 1280 / 1920 页面级无横向滚动 | `web/e2e/theme.spec.ts` | SC-002 |

## 6. 未改动范围

未改 `docs/api/openapi.yaml`、未改后端数据模型与执行编排、未改巡检规则、未新增依赖、未改分页 / 筛选 / 轮询 / 上传与操作语义（FR-005、FR-017~FR-019）。

## 7. 已知遗留

- `web/src/pages/TaskListPage.tsx` 的操作列在最坏状态（同时出现「详情 / 失败日志 / 重建 / 删除 / 删除失败」）下依赖 280px 宽度单行容纳；该状态未在 E2E 中构造，沿用 031/033 的既有约束与结论。
- 1280×900 下任务列需要横向滚动后才可见，属本功能明确允许的口径（FR-004）。
