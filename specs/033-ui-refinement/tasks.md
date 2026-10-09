---
description: "界面降噪与一致性精修 — 实现任务清单"
---

# 任务：界面降噪与一致性精修

**输入**：来自 `specs/033-ui-refinement/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/ui-refinement.md、quickstart.md

**测试**：本清单包含测试任务；前端新增能力先写失败测试再补实现（TDD），并包含覆盖完整入口到关键结果的 E2E。前端单测分两套：`src/**/*.test.ts` 由 `node --test` 执行（`node:test` + `node:assert/strict`，导入需带 `.ts` 后缀），`src/**/*.test.tsx` 由 Vitest 执行。

**组织方式**：按用户故事分组，每个故事可独立实现、独立测试、独立演示。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1~US6）
- 描述中包含精确的文件路径与对应 FR / SC / R 编号

## 路径约定

仓库根目录：`web/`、`docs/`、`specs/`。规划产物已在 `main` 主工作区完成并提交；实现与测试全部在实现分支 worktree `.worktrees/feature/033-ui-refinement` 内完成，不得在主工作区改实现文件。

本轮不修改 `docs/api/openapi.yaml`、不新增或修改前端 API 调用、不改后端执行链路、不新增依赖、不改路由与深链。

---

## 阶段 1：设置（实现环境与前置检查）

**目的**：创建实现 worktree 并完成 AGENTS.md 规定的实现前置检查

- [ ] T001 从已提交规划产物的 `main` 创建实现分支 `feature/033-ui-refinement` 与 worktree `.worktrees/feature/033-ui-refinement`；执行 `git worktree list` 与 `git branch --show-current` 并确认：当前目录是实现 worktree、检出分支正确、Speckit 产物已在 `main` 提交、未与其他 worktree 分支冲突；在回合报告记录检查结果（阻塞全部后续任务；AGENTS.md 实现前置检查）

**检查点**：前置检查四条全部满足，后续任务方可开始。

---

## 阶段 2：基础层（阻塞全部用户故事）

**目的**：把跨故事复用的纯函数与小组件先做成可单测的共享能力，避免在页面内各写一份

- [ ] T002 [P] 先写失败单测 `web/src/utils/taskDisplay.test.ts`：`getHealthBarSegments` 排序改为 `fail → warn → error → skip → pass`、`percent` 取整、概览场景 pass/skip 强调级别为 `quiet`（FR-001、FR-002、data-model §1、R1）
- [ ] T003 实现 `web/src/utils/taskDisplay.ts`：调整 `getHealthBarSegments` 排序与 `emphasis` 推导，新增概览弱化色映射（pass `#b7eb8f` / skip `#91caff`，fail/warn/error 保持标准色），保持既有调用点签名兼容（依赖 T002；FR-001、FR-002、R1）
- [ ] T004 [P] 新增 `web/src/utils/statusTextColors.ts` 与单测 `web/src/utils/statusTextColors.test.ts`：文本安全色 warn `#ad6800`、pass `#389e0d`、skip `#0958d9`、error `#595959`；导出 `contrastRatio`，单测逐色断言相对白底 ≥ 4.5:1（FR-019、SC-006、R13）
- [ ] T005 [P] 新增 `web/src/utils/timeDisplay.ts` 与单测 `web/src/utils/timeDisplay.test.ts`：dayjs `relativeTime` + `zh-cn` 相对时间、完整时间 Tooltip 文案、`tabular-nums` 类名常量；空值与非法时间返回占位而不抛错（FR-006、FR-007、FR-017、R4）
- [ ] T006 [P] 新增 `web/src/components/CopyTextButton.tsx` 与单测 `web/src/components/CopyTextButton.test.tsx`：复制成功 / 失败可见反馈、键盘可触发、焦点可见、点击不触发行跳转，剪贴板不可用时降级为可选中文本（FR-010、FR-014、FR-015、contracts §7）
- [ ] T007 [P] 新增 `web/src/utils/taskOverview.ts` 与单测 `web/src/utils/taskOverview.test.ts`：四项指标（巡检任务 / 注册规则 / 规则结果 / 发现问题数）的 label、口径 description 与统计范围；description 必须包含"一条规则可产生多条发现"，并解释规则结果 = 五态之和（FR-004、data-model §2）
- [ ] T008 [P] 新增 `web/src/utils/findingEvidence.ts` 与单测 `web/src/utils/findingEvidence.test.ts`：按 `；` 拆段、识别 `键：值` / `键 值`、数字 / 次数 / 时长为 `highlights`、超过 4 行标记折叠、解析失败降级为原文且不丢信息（FR-012、FR-013、FR-014、R8、data-model §3）
- [ ] T009 [P] 新增 `web/src/hooks/useTableDensity.ts` 与单测 `web/src/hooks/useTableDensity.test.tsx`：默认 `compact`、localStorage key `patrolx.tableDensity` 读写、非法值与读取 / 写入失败静默回退默认（FR-016、data-model §4、R11）
- [ ] T010 [P] 新增 `web/src/components/DensitySegmented.tsx` 与单测 `web/src/components/DensitySegmented.test.tsx`：紧凑 / 舒适两态、键盘可操作、`aria-pressed` 状态可读、只切换密度不改动筛选与分页（FR-016、contracts §6）
- [ ] T011 [P] 新增 `web/src/utils/uploadPrecheck.ts` 与单测 `web/src/utils/uploadPrecheck.test.ts`：`deriveTaskIdPreview` 与后端 `app/cli.py::clean_task_id` 同规则（固定样例覆盖中文、大写、连续特殊字符、超长、空名回退 `task`）；`validatePackageFile` 覆盖扩展名、空文件、超过上限、文件名超长，返回具体原因（FR-023、FR-024、R16、data-model §5）

**检查点**：基础层单测全绿（`npm test` 与 `npx vitest run`）；六个用户故事可以开始。

---

## 阶段 3：用户故事 1 - 任务列表只被异常吸引（优先级：P1）🎯 MVP

**目标**：概览条与任务行把注意力让给失败 / 告警 / 异常；计数异常优先、口径可查、时间与操作不再抢注意力。

**独立测试**：`cd web && npx playwright test e2e/task-home.spec.ts e2e/task-actions.spec.ts`

- [ ] T012 [P] [US1] 先写失败测试，扩展 `web/src/components/StatusDistribution.test.tsx`：分段与计数按 `fail → warn → error → skip → pass`、每段 Tooltip 文案为"状态 计数（整数百分比）"、0 值状态不渲染、五态全 0 只显示空文案（FR-001、FR-002、FR-003、FR-005）
- [ ] T013 [US1] 重构 `web/src/components/StatusDistribution.tsx`：使用 AntD `Tooltip` 替换原生 `title`、`variant="full"` 的概览场景应用弱化色、计数与分段顺序一致、空态不渲染空条；保持 `onStatusClick` 状态筛选与既有 `data-status-*` 属性（依赖 T003、T012；FR-001~FR-003、FR-005、contracts §1）
- [ ] T014 [US1] 在 `web/src/pages/TaskListPage.tsx` 概览指标区（`task-overview-metrics`）接入 `taskOverview` 口径说明 Tooltip 与统计范围；0 值状态不渲染；分布条使用弱化形态（依赖 T007、T013；FR-002、FR-004、FR-005、R3）
- [ ] T015 [US1] 在 `web/src/pages/TaskListPage.tsx` 重排"时间与耗时"列：耗时为主信息、创建 / 完成为相对时间次要信息、Tooltip 提供完整时间、列内不换行（依赖 T005、T014；FR-006、FR-007）
- [ ] T016 [US1] 在 `web/src/pages/TaskListPage.tsx` 收敛行内操作：常驻仅"详情"；报告 / 失败日志 hover 或聚焦显示且保留在 `⋯` 菜单；重跑 / 重建 / 删除仅在菜单，危险操作保留二次确认；失败原因摘要可点击进入日志且不出现第二个失败日志入口（依赖 T015；FR-008、FR-026、R5、contracts §3）
- [ ] T017 [US1] 在 `web/src/theme.css` 落地概览弱化色、时间列等宽数字（`tabular-nums`）、操作列 hover / focus-visible 显隐与焦点样式，确保 1280px 下固定列不遮挡；超长任务名 / 规则名 / 路径在紧凑密度下截断并提供悬浮完整值与复制（依赖 T015、T016；FR-002、FR-006、FR-007、FR-027、边界情况）
- [ ] T018 [P] [US1] 扩展 `web/e2e/task-home.spec.ts`：异常优先排序、概览条弱化色、Tooltip 文案与占比、时间列层级、0 值状态不出现、加载中不渲染 0 值分布（依赖 T014~T017；SC-001、SC-002、SC-009、边界情况）
- [ ] T019 [P] [US1] 扩展 `web/e2e/task-actions.spec.ts`、`web/e2e/task-delete-confirm.spec.ts`：报告 / 失败日志 / 重跑 / 重建 / 删除在收敛后仍可及，确认流程行为不变（依赖 T016；FR-008、FR-026、SC-009）

**检查点**：MVP 可用——列表首屏异常优先、口径可查、操作收敛；`task-home` 与 `task-actions` E2E 通过。

---

## 阶段 4：用户故事 2 - 任务详情结论无噪音、不重复（优先级：P1）

**目标**：结论句只讲非零事实；元数据只显示真实有值字段；重点关注与全部规则不再等权重复。

**独立测试**：`cd web && npx playwright test e2e/task-detail.spec.ts e2e/task-detail-states.spec.ts e2e/task-detail-rule-browser.spec.ts`

- [ ] T020 [P] [US2] 先写失败测试，扩展 `web/src/utils/taskConclusion.test.ts`：fail 分支只表达非零状态（不出现"异常 0 条"）、仅 warn 为"需要关注"、全通过与空 stats 分支保持既有语义（FR-009、SC-003）
- [ ] T021 [US2] 实现 `web/src/utils/taskConclusion.ts`：结论句按非零状态拼接，保持推导优先级与后端文案无关（依赖 T020；FR-009、R6）
- [ ] T022 [P] [US2] 先写失败测试，新增 `web/src/components/MetadataList.test.tsx`：空值与空白值不渲染、最多平铺 4 项、其余进入"更多元数据"、全部为空时整块隐藏、完整值可复制（FR-010、SC-003、contracts §4）
- [ ] T023 [US2] 重构 `web/src/components/MetadataList.tsx`：支持 `maxVisible`（默认 4）与"更多元数据" Popover，移除 `emptyText="-"` 占位路径，接入 `CopyTextButton`（依赖 T006、T022；FR-010、R6）
- [ ] T024 [US2] 调整 `web/src/components/ConclusionHero.tsx`：`buildMetadataItems` 过滤空值、不再生成 `"-"` 占位、按新 MetadataList 渲染，结论句来自 `deriveTaskConclusion`（依赖 T021、T023；FR-009、FR-010、R6）
- [ ] T025 [P] [US2] 补充单测 `web/src/components/ConclusionHero.test.tsx`：结论无零值、空元数据不渲染占位、最多 4 项平铺（依赖 T024；SC-003）
- [ ] T026 [US2] 在 `web/src/components/task-detail/RuleBrowser.tsx` 实现去重：接收重点关注规则 code 列表并默认排除，显示"另有 N 条已在上方重点关注 · 显示全部"；搜索命中时自动纳入结果（依赖 T024；FR-011、SC-004、R7）
- [ ] T027 [P] [US2] 单测 `web/src/components/task-detail/RuleBrowser.test.tsx`（新增）：默认排除、显示全部后完整、搜索命中优先纳入（依赖 T026；FR-011）
- [ ] T028 [P] [US2] 扩展 `web/e2e/task-detail.spec.ts`、`web/e2e/task-detail-states.spec.ts`：结论句无 0 值、空字段不渲染横线、"更多元数据"可展开（依赖 T024；SC-003、SC-009）
- [ ] T029 [P] [US2] 扩展 `web/e2e/task-detail-rule-browser.spec.ts`：默认不重复、显示全部恢复完整列表、搜索仍命中被排除规则（依赖 T026；SC-004）

**检查点**：详情首屏无零值与空占位；同一规则不重复表达；`task-detail*` 系列 E2E 通过。

---

## 阶段 5：用户故事 3 - 规则详情先读结论与证据（优先级：P2）

**目标**：发现条目结构化、关键数值高亮、长证据可展开、来源路径可复制；源文件匹配降为一行元数据。

**独立测试**：`cd web && npx playwright test e2e/alarm-flapping-rule-detail.spec.ts`

- [ ] T030 [P] [US3] 先写失败断言，扩展 `web/e2e/alarm-flapping-rule-detail.spec.ts`：发现条目分行、关键数值高亮、超过 4 行折叠可展开、来源路径复制、源文件匹配不超过一行（FR-012~FR-015、SC-005）
- [ ] T031 [US3] 在 `web/src/pages/RuleDetailPage.tsx` 移除独立"源文件匹配"Card，改为结论卡片内一行等宽元数据 + `CopyTextButton`，保留 `data-testid="rule-section-source-patterns"` 供断言等价替换（依赖 T006；FR-015、SC-005、R9、contracts §5）
- [ ] T032 [US3] 新增 `web/src/components/FindingItem.tsx` 并在 `web/src/pages/RuleDetailPage.tsx` 接入：来源 / 证据 / 详情 / 建议分行或键值对，关键数值高亮，超过 4 行折叠展开，来源路径复制，解析失败降级原文（依赖 T008、T031；FR-012、FR-013、FR-014、R8）
- [ ] T033 [US3] 在 `web/src/components/StatusBadge.tsx` 为 `SeverityTag` 增加 `variant?: "tag" | "plain"`（色点 + 文字，含 title 与 aria-label）；`RuleDetailPage` 与 `web/src/components/RuleResultTable.tsx` 改用 plain，其余场景保持 tag（依赖 T004；FR-013、R10）
- [ ] T034 [P] [US3] 补充单测 `web/src/components/FindingItem.test.tsx` 与 `web/src/components/StatusBadge.test.tsx`（新增）：结构化渲染、折叠阈值、复制动作、plain 变体无障碍属性（依赖 T032、T033；FR-012~FR-014）
- [ ] T035 [P] [US3] 扩展 `web/src/pages/RuleDetailPage.test.tsx`：区块顺序为结论与建议 → 源文件匹配一行 → 发现 → 证据，`skip` 必显 `skip_reason`（依赖 T031~T033；FR-015、SC-005）

**检查点**：规则详情首屏可见结论、建议与首个发现；配置信息不占高位。

---

## 阶段 6：用户故事 4 - 密度可选与管理页细节（优先级：P2）

**目标**：三处表格支持紧凑 / 舒适且记忆偏好；规则管理页时间、排序、编码与启停反馈工程化。

**独立测试**：`cd web && npx playwright test e2e/page-states.spec.ts e2e/table-density.spec.ts`

- [ ] T036 [US4] 在 `web/src/pages/TaskListPage.tsx` 接入 `DensitySegmented` 与 `useTableDensity`：AntD `Table size` 联动、切换不重置筛选 / 分页 / 滚动位置、刷新后保持偏好（依赖 T009、T010；FR-016、contracts §6）
- [ ] T037 [US4] 在 `web/src/pages/TaskDetailPage.tsx` 的"重点关注"表格接入同一密度偏好（依赖 T009、T010、T036；FR-016）
- [ ] T038 [US4] 在 `web/src/pages/InspectorsPage.tsx` 接入密度偏好；更新时间列改相对时间 + Tooltip 完整时间并支持排序；规则编码列使用等宽字体（依赖 T005、T009、T010；FR-016、FR-017、R12）
- [ ] T039 [US4] 在 `web/src/pages/InspectorsPage.tsx` 完善启停开关：请求进行中禁用重复触发，失败回滚到变更前并给出失败原因，成功保持既有提示（依赖 T038；FR-018、R12）
- [ ] T040 [P] [US4] 新增 `web/src/pages/InspectorsPage.test.tsx`：相对时间渲染、排序回调、开关失败回滚与进行中禁用（依赖 T038、T039；FR-017、FR-018）
- [ ] T041 [P] [US4] 扩展 `web/src/pages/TaskListPage.test.tsx`、`web/src/pages/TaskDetailPage.test.tsx`：密度偏好默认值、切换后筛选与分页不重置（依赖 T036、T037；FR-016）
- [ ] T042 [P] [US4] 新增 `web/e2e/table-density.spec.ts` 并扩展 `web/e2e/page-states.spec.ts`：跨页面偏好记忆、紧凑密度同视口多可见 2 行、规则管理时间与排序（依赖 T036~T039；SC-001、SC-009）

**检查点**：三处密度一致且可记忆；规则管理页细节达标。

---

## 阶段 7：用户故事 5 - 全局一致与可访问性（优先级：P2）

**目标**：状态不依赖颜色、文本色满足 AA、顶栏与侧边栏权重正确、术语统一。

**独立测试**：`cd web && npx playwright test e2e/theme.spec.ts e2e/navigation-icons.spec.ts e2e/page-states.spec.ts`

- [ ] T043 [US5] 全局应用文本安全色：`web/src/components/StatusBadge.tsx`、`web/src/components/StatusDistribution.tsx`、`web/src/theme.css` 的文字状态色改用 `statusTextColors` 输出，填充色仍保留标准状态色（依赖 T004、T033；FR-019、SC-006、R13）
- [ ] T044 [US5] 为"异常"增加颜色以外的冗余标识：`web/src/theme.css` 分布条斜纹背景 + `web/src/components/StatusBadge.tsx` 标签纹理或图标；确认与中性灰文本可区分（依赖 T043；FR-019、SC-006）
- [ ] T045 [US5] 调整 `web/src/layouts/MainLayout.tsx`：顶栏左侧改为当前页面标题（路由 → 标题映射），右侧保留用户区；访客模式"登录"降为 `default`；侧边栏选中态改为淡色底 + 左侧指示条 + 品牌色文字（依赖 T017；FR-020、FR-021、R14）
- [ ] T046 [P] [US5] 新增 `web/src/layouts/MainLayout.test.tsx`：路由标题映射、登录按钮权重、选中态 class 与键盘焦点（依赖 T045；FR-020、FR-021）
- [ ] T047 [US5] 扩展 `web/e2e/theme.spec.ts`、`web/e2e/navigation-icons.spec.ts`、`web/e2e/page-states.spec.ts`：顶栏上下文、登录权重、侧边栏选中态、状态文字对比度与异常冗余标识、密度 / 复制 / 展开的键盘触发与可见焦点（依赖 T043~T045，且与 T042 同文件须在其后执行；SC-006、SC-008、边界情况）
- [ ] T048 [US5] 在 `docs/design/DESIGN.md` 新增术语表章节：规则结果 / 发现 / 问题条目 / 状态分布 / 任务，并同步状态语义与禁用词约定（FR-022、SC-006、R15、data-model §6）

**检查点**：逐页走查状态语义、顶栏、侧边栏与术语一致；对比度断言通过。

---

## 阶段 8：用户故事 6 - 上传前置反馈（优先级：P3）

**目标**：选择文件后即可看到任务 ID 预览与校验结论；同名冲突给出下一步动作；不改契约。

**独立测试**：`cd web && npx playwright test e2e/upload-precheck.spec.ts`

- [ ] T049 [US6] 先写失败测试，扩展 `web/src/pages/TaskListPage.test.tsx`：选择文件后渲染任务 ID 预览、文件大小与校验结论；非法文件禁用提交并显示具体原因（与 T041 同文件须在其后执行；FR-023、SC-007）
- [ ] T050 [US6] 在 `web/src/pages/TaskListPage.tsx` 上传弹窗接入 `deriveTaskIdPreview` 与 `validatePackageFile`：预览区展示 token 样式任务 ID、格式化文件大小、格式 / 空文件 / 超限 / 超长原因，非法时禁用"确定"（依赖 T011；FR-023、data-model §5、R16）
- [ ] T051 [US6] 在 `web/src/pages/TaskListPage.tsx` 完善同名与 checksum 冲突提示：`package_checksum_conflict` 提供"修改文件名 / 查看已有任务"两个动作，checksum 相同提示"将打开已有任务"；不新增接口调用，不改错误码语义（依赖 T050；FR-024、FR-025）
- [ ] T052 [P] [US6] 新增 `web/e2e/upload-precheck.spec.ts`：合法文件 1 秒内出现预览、非法文件禁用提交并给出原因、同名冲突提示包含下一步动作；样例固定使用 `web/e2e/start-backend.sh` 确定性生成的 `.tmp/inventory-e2e.zip` 与 Playwright 内存文件（空文件 / 非法扩展名），冲突由同一文件二次上传复现，不新增巡检数据语义（依赖 T050、T051；SC-007、SC-009、plan 展示效果合规说明）

**检查点**：上传前即可发现绝大多数问题；后端校验语义未变。

---

## 阶段 9：收尾与横切关注点

**目的**：设计规范回写、证据留存与全量质量门禁

- [ ] T053 回写 `docs/design/DESIGN.md`：概览条弱化与排序、时间列规范、操作分层、密度切换、发现条目结构、文本安全色与对比度要求、上传前置反馈（在 T048 术语表基础上合并，FR-030）
- [ ] T054 越界与洁净度检查：`git status` 与 `git diff --stat` 确认未改 `docs/api/openapi.yaml`、未改后端、未新增依赖、未改路由与深链；未改 `tests/fixtures/make_real_package.py`（复用既有代表性样例包，见 plan 展示效果合规说明）；未暂存 `web/.tmp-show-detail.mjs`、`web/.tmp-show-updates.mjs` 与 `web/e2e/screenshots/`（FR-025、FR-026、FR-029）
- [ ] T055 运行 `python build.py web-build`、`cd web && npm test`、`cd web && npx vitest run`，修复全部类型 / 构建 / 单测问题（FR-028、SC-009、R17）
- [ ] T056 [P] 运行 `python build.py lint` 与 `python build.py test`，全绿（AGENTS.md 合入门禁）
- [ ] T057 运行 `python build.py e2e` 全量通过（自动起服务并加载种子任务），未删除任何既有覆盖（FR-026、FR-028、SC-009）
- [ ] T058 视口走查与截图：在 1280 / 1440 / 1920 检查无页面级横向滚动、1920 内容宽度 ≤ 1600px；按 1440×900 留存 5 张截图到 `web/e2e/screenshots/`（任务列表 / 任务详情 / 规则详情 / 规则管理 / 上传弹窗，本地证据不提交）（FR-027、FR-030、SC-001、SC-008、quickstart §3）
- [ ] T059 在 `specs/033-ui-refinement/verification.md` 记录 SC-001~SC-009 复现结果（命令、结论、截图清单与对应 SC），勾选本清单复选框并更新 spec/plan 如有偏差（FR-030、quickstart §4）
- [ ] T060 交付：按主题拆分提交（状态分布 / 列表降噪 / 详情降噪 / 规则详情 / 密度与管理页 / 全局一致性 / 上传预检 / 文档），提交信息用中文；收到"推送"指令后按 AGENTS.md 推送约定 fast-forward 合入 `main` 并推送 `origin/main`，非 fast-forward 或门禁失败先报告等待确认

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：T001 阻塞全部后续任务
- **基础层（阶段 2）**：依赖 T001；阻塞全部用户故事
- **用户故事（阶段 3~8）**：均依赖基础层完成，可按 P1 → P2 → P3 顺序执行，也可在人力允许时并行
- **收尾（阶段 9）**：依赖所有纳入本轮的阶段完成

### 用户故事依赖

- **US1（P1，MVP）**：依赖 T003（排序）、T005（时间）、T007（口径），可独立交付与测试
- **US2（P1）**：依赖 T006（复制）、T021（结论），可独立测试；与 US1 无写冲突
- **US3（P2）**：依赖 T004、T006、T008，可独立测试
- **US4（P2）**：依赖 T005、T009、T010，可独立测试；T037 依赖 T036 的接入方式
- **US5（P2）**：依赖 T004；T043 同时改动 US1 的 `StatusDistribution.tsx`（T013）与 US3 的 `StatusBadge.tsx`（T033），必须排在 T013 与 T033 之后执行
- **US6（P3）**：依赖 T011，可独立测试

### 每个用户故事内部

- 测试先于实现：T002→T003、T012→T013、T020→T021、T022→T023、T030→T031、T049→T050
- 共享组件先于页面：T013→T014、T021/T023→T024、T032/T033→T035、T009/T010→T036→T037
- 同一文件的任务串行执行：`TaskListPage.tsx` 的 T014→T015→T016→T036→T050→T051；`RuleDetailPage.tsx` 的 T031→T032→T033；`InspectorsPage.tsx` 的 T038→T039

### 并行机会

- 阶段 2 的 T004~T011 可并行（不同文件）
- 基础层完成后 US1 / US2 可并行；US3 / US4 / US6 之间无文件冲突。US5 因复用 `StatusDistribution.tsx` 与 `StatusBadge.tsx`，须在 US1 的 T013 与 US3 的 T033 之后执行（T043）
- 同一故事内的 E2E 扩展任务（T018 / T019、T028 / T029、T052）可并行
- 阶段 9 的 T056 与 T055 可并行；T058 与 T059 需在 T057 之后

---

## 并行示例：用户故事 2

```bash
# 结论与元数据分别推进（不同文件）：
Task: "在 web/src/utils/taskConclusion.ts 实现非零状态结论（T021）"
Task: "在 web/src/components/MetadataList.tsx 实现空值过滤与更多元数据（T023）"

# 结构完成后并行补测试证据：
Task: "扩展 web/e2e/task-detail.spec.ts 与 task-detail-states.spec.ts（T028）"
Task: "扩展 web/e2e/task-detail-rule-browser.spec.ts（T029）"
```

---

## 实现策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：设置（含 worktree 前置检查）
2. 完成阶段 2：基础层（阻塞全部故事）
3. 完成阶段 3：US1
4. **停止并验证**：`cd web && npx playwright test e2e/task-home.spec.ts e2e/task-actions.spec.ts`
5. 演示 / 截图任务列表新形态

### 增量交付

1. 设置 + 基础层 → 共享能力就绪
2. US1 → 独立测试 → 演示（MVP）
3. US2 → 独立测试 → 演示
4. US3 → 独立测试 → 演示
5. US4 → 独立测试 → 演示
6. US5 → 独立测试 → 演示
7. US6 → 独立测试 → 演示
8. 收尾：DESIGN.md 回写 + 全量门禁 + 截图与走查证据

### 质量门禁（每个用户故事完成后）

```bash
python build.py web-build
python build.py lint
python build.py test
python build.py e2e
```

任一门禁失败不得进入下一故事；前端结构调整只允许等价替换测试断言，不得删除既有覆盖。

### 反模式提醒

- 不得为通过测试而修改 `docs/api/openapi.yaml`、后端或新增前端接口调用（FR-025）
- 不得用 CSS 隐藏代替数据层过滤（空值 / 0 值必须在渲染前剔除）
- 不得把密度偏好写入后端或 URL，避免污染深链
- 不得删除既有 `data-testid` / `data-status-*` 属性；结构调整用等价断言语义替换
