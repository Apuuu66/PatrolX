# 验证记录：界面降噪与一致性精修（033-ui-refinement）

- 实现 worktree：`.worktrees/feature/033-ui-refinement`（分支 `feature/033-ui-refinement`）
- 规划产物基线：`main` @ `893e120`
- 实现前置检查：`git worktree list` / `git branch --show-current` 已执行，确认当前目录为该实现分支 worktree、检出分支正确、Speckit 产物已在 `main` 提交
- 验证范围：纯前端展示层精修 + 文档回写；未改 OpenAPI、未改后端、未新增依赖、未改路由与深链

## 1. 质量门禁结果

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `.venv/bin/python build.py lint` | 通过 | `All checks passed!` / `181 files already formatted` |
| `.venv/bin/python build.py test` | 通过 | `576 passed`（38.8s，上限 120s） |
| `.venv/bin/python build.py web-build` | 通过 | `tsc -b` + `vite build` 成功（仅有既有 chunk 体积提示） |
| `cd web && npm test` | 通过 | `node --experimental-strip-types --test`：134 passed / 39 suites；`vitest run`：20 files / 93 tests passed |
| `.venv/bin/python build.py e2e` | 通过 | `53 passed (30.0s)`，自动起 `8010` 后端 + `5183` 前端并加载 E2E 种子任务 |

worktree 内 `.venv`、`web/node_modules` 为指向主仓库的符号链接（均被 `.gitignore` 忽略），不参与提交。

## 2. 成功标准逐条证据

### SC-001（任务列表首屏与密度差异）

- `e2e/task-home.spec.ts:16`：1440×900 下 5 条种子任务首屏可见、失败任务置顶、单一表行式列表，通过。
- `e2e/table-density.spec.ts:48`：1440×620 下紧凑密度比舒适密度多显示 ≥2 行（并断言行高更大），通过。
- `e2e/theme.spec.ts:12`：1280 / 1920 无页面级横向滚动，通过。
- 截图：`web/e2e/screenshots/1-任务列表.png`。

### SC-002（概览条弱化与状态色）

- `e2e/task-home.spec.ts:98`：通过 / 跳过使用低饱和计数表达，失败 / 告警 / 异常使用标准状态色，且给出计数与占比 Tooltip，通过。
- `web/src/components/StatusDistribution.test.tsx`（11 passed）、`web/src/utils/taskOverview.test.ts`：非零状态才渲染、缺失数据不渲染 0 值假分布。
- 截图：`1-任务列表.png`（概览条右半区状态分布）。

### SC-003（结论句零值与空元数据）

- `e2e/task-detail.spec.ts:3`：结论句只包含非零状态，通过。
- `e2e/task-detail.spec.ts:150`：元数据超过 4 项收纳，空字段不渲染占位，通过。
- 单测 `web/src/utils/taskConclusion.test.ts`、`web/src/components/MetadataList.test.tsx` 覆盖 0 值剔除与空值过滤。
- 截图：`2-任务详情.png`。

### SC-004（重点关注与全部规则不重复）

- `e2e/task-detail-rule-browser.spec.ts:103`：默认视图同一规则不在"全部规则"中等权重复，`显示全部` 可恢复完整列表，通过。
- 单测 `web/src/components/task-detail/RuleBrowser.test.tsx` 覆盖去重与恢复。
- 截图：`2-任务详情.png`（"另有 N 条已在重点关注 · 显示全部"）。

### SC-005（规则详情首屏）

- `e2e/alarm-flapping-rule-detail.spec.ts:28`：按结论 → 建议 → 源文件匹配 → 发现 → 证据 → 技术信息组织，首屏可见结论、建议与第一条发现，"源文件匹配"保持一行，通过。
- `e2e/alarm-flapping-rule-detail.spec.ts:172`：`skip` 规则展示跳过原因，通过。
- 截图：`3-规则详情.png`。

### SC-006（状态文字对比度与异常冗余标识）

- `e2e/theme.spec.ts:58`：页面脚本内计算关注状态文字与背景对比度，≥ 4.5:1，通过。
- `e2e/theme.spec.ts:98`：异常状态除颜色外具备斜纹 / 虚框等冗余标识，通过。
- 单测 `web/src/utils/statusTextColors.test.ts` 锁定五个文本安全色值。
- 截图：`1-任务列表.png`（异常斜纹分段）、`2-任务详情.png`（异常虚框标签）。

### SC-007（上传前置反馈）

- `e2e/upload-precheck.spec.ts:34`：合法数据包选择后 1 秒内出现任务 ID 预览、文件大小与"校验通过"，提交可用，通过。
- `e2e/upload-precheck.spec.ts:52`：非法扩展名 / 空文件 / 文件名超长在选择阶段即给出具体原因并禁用提交，通过。
- `e2e/upload-precheck.spec.ts:84`：同名且 checksum 相同提示"同名数据包已存在，将打开已有任务"；checksum 不同时弹窗内给出"修改文件名 / 查看已有任务"两个动作并跳转既有任务，通过。
- 单测 `web/src/utils/uploadPrecheck.test.ts`（与后端 `app/cli.py::clean_task_id` 同规则）、`web/src/pages/TaskListPage.test.tsx` 上传预检 / 同名冲突分组（10 passed）。
- 截图：`5-上传弹窗.png`。

### SC-008（1280 / 1440 / 1920 走查）

走查脚本（临时 Playwright 用例，取证后已删除，未提交）逐视口访问任务列表、任务详情、规则详情、规则管理并打开上传弹窗，断言：

- `document.documentElement.scrollWidth <= clientWidth`：1280 / 1440 / 1920 全部通过；
- 1920px 下 `.app-shell-inner` 内容宽度 ≤ 1600px：全部通过；
- 上传弹窗（含任务 ID 预览）不产生页面级横向滚动。

常驻回归：`e2e/theme.spec.ts:12` 覆盖 1280 / 1920 无横向滚动 + 1920 内容 ≤1600px + 页头与内容左对齐。

截图（1440×900，本地证据，不提交）：

| 截图 | 页面 | 对应 SC |
| --- | --- | --- |
| `1-任务列表.png` | 任务列表（概览条 + 行操作 + 密度） | SC-001 / SC-002 / SC-006 / SC-008 |
| `2-任务详情.png` | 任务详情（结论 + 重点关注 + 全部规则） | SC-003 / SC-004 / SC-006 / SC-008 |
| `3-规则详情.png` | 规则详情（结论 + 建议 + 一行源匹配 + 发现） | SC-005 / SC-008 |
| `4-规则管理.png` | 规则管理（相对时间 + 排序 + 密度） | SC-001（时间列规范）/ SC-008 |
| `5-上传弹窗.png` | 上传弹窗（任务 ID 预览 + 校验通过） | SC-007 / SC-008 |

### SC-009（门禁与覆盖）

- 门禁结果见第 1 节，全部通过。
- 每个用户故事都有自动化用例与走查截图：

| 用户故事 | 主要自动化用例 | 截图 |
| --- | --- | --- |
| US1 任务列表 | `task-home.spec.ts`、`table-density.spec.ts` | 1 |
| US2 任务详情 | `task-detail.spec.ts`、`task-detail-states.spec.ts`、`task-detail-rule-browser.spec.ts` | 2 |
| US3 规则详情 | `alarm-flapping-rule-detail.spec.ts`、`page-states.spec.ts` | 3 |
| US4 密度与管理页 | `table-density.spec.ts`、`task-actions.spec.ts` | 4 |
| US5 全局一致性 | `theme.spec.ts`、`navigation-icons.spec.ts`、`MainLayout.test.tsx` | 1–5 |
| US6 上传预检 | `upload-precheck.spec.ts`、`TaskListPage.test.tsx` | 5 |

## 3. 与规划的偏差

### R13 状态文字色值（唯一实质偏差）

`research.md` R13 给出的文本安全色为 warn `#ad6800`、pass `#389e0d`。实测在浅色底上按 WCAG AA 计算时，这两个值对本页使用的背景不足 4.5:1，因此实现改用：

| 状态 | research 规划值 | 实现值 | 说明 |
| --- | --- | --- | --- |
| pass | `#389e0d` | `#237804` | 满足 AA（对 `#fafafa` / 白色背景） |
| warn | `#ad6800` | `#874d00` | 满足 AA |
| fail | — | `#cf1322` | 与规划一致口径，满足 AA |
| error | — | `#595959` | 满足 AA |
| skip | — | `#0958d9` | 满足 AA |

- 值定义在 `web/src/theme.css` 的 `--status-text-*`，与 `web/src/utils/statusTextColors.ts` 一一对应，`statusTextColors.test.ts` 锁定。
- 填充色（`--status-*`）保持原标准状态色不变，"概览条弱化"仍使用低饱和填充。
- `e2e/theme.spec.ts:58` 在页面内实时计算对比度并断言 ≥ 4.5:1，因此后续若调整色值会直接失败。

### 既有 E2E 断言的等价调整（未删除覆盖）

| 文件 | 调整 | 原因 |
| --- | --- | --- |
| `web/e2e/inventory.spec.ts` | 设备台账标题断言加 `level: 1` | 顶栏新增当前页面标题（FR-020）后与页面主标题同名，原写法触发 Playwright strict mode |
| `web/e2e/inventory.spec.ts` | 重新巡检后台账可见断言超时 5s → 20s | 新增上传预检用例并行创建任务后，后台解压 + 台账回填偶发超过 5s；断言语义不变 |
| `web/e2e/table-density.spec.ts` | 等宽断言取内层 `<code>`；排序断言改用 `aria-sort` | 等宽样式落在 `Typography.Text code` 内层；E2E 种子规则 `updated_at` 相同，行序无法区分排序方向 |
| `web/src/pages/TaskListPage.test.tsx` | `ApiError` mock 补齐 `code/status/detail` | 与真实类构造签名一致，冲突分支才能被触发 |

## 4. 越界与洁净度

- 未修改 `docs/api/openapi.yaml`、`app/**`、`requirements-lock.txt`、`pyproject.toml`、依赖清单、`web/src/App.tsx` 路由与深链。
- 未修改 `tests/fixtures/make_real_package.py`：本功能为纯展示层精修，不新增巡检数据语义；展示效果复用既有代表性样例包与 E2E 种子任务，上传预检使用 `web/e2e/start-backend.sh` 确定性生成的 `.tmp/inventory-e2e.zip` 与 Playwright 内存文件。
- 上传预检与冲突提示复用既有 `POST /api/v3/tasks` 与 `package_checksum_conflict` 错误码，未新增接口调用。
- `web/e2e/screenshots/`、`web/test-results/`、`web/e2e/.tmp/`、调试用临时 spec 均未提交（`test-results` 已在 `.gitignore`）。

## 5. 复现命令

```bash
cd .worktrees/feature/033-ui-refinement
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py web-build
cd web && npm test
cd web && npx playwright test e2e/task-home.spec.ts e2e/table-density.spec.ts \
  e2e/task-detail.spec.ts e2e/task-detail-states.spec.ts e2e/task-detail-rule-browser.spec.ts \
  e2e/alarm-flapping-rule-detail.spec.ts e2e/theme.spec.ts e2e/navigation-icons.spec.ts \
  e2e/page-states.spec.ts e2e/upload-precheck.spec.ts
cd ../ && .venv/bin/python build.py e2e
```

走查取证（任选一次，截图写入 `web/e2e/screenshots/`，不提交）：按 1440×900 逐页截图，并在 1280 / 1440 / 1920 下检查 `document.documentElement.scrollWidth <= clientWidth` 与 1920 内容宽度 ≤1600px。
