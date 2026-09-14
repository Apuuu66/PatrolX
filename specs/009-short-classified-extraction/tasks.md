---
description: "009 分类短路径解压、长路径防护与准备/删除状态展示任务清单"
---

# 任务：分类短路径解压、长路径防护与准备/删除状态展示

**输入**：`specs/009-short-classified-extraction/`

**前置条件**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/api.md`、`quickstart.md`

**测试**：本功能涉及安全解压、契约、执行器、删除和关键交互，必须采用测试先行；每个故事先补失败测试，再实现。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：不同文件且不依赖未完成前置任务时可并行。
- **[US1]**：分类现场直接落位。
- **[US2]**：长路径提前失败。
- **[US3]**：数据准备状态可见。
- **[US4]**：删除失败可见可重试。

---

## 阶段 1：设置

**目的**：隔离实现现场，固定基线，准备可复现样例。

- [x] T001 在仓库根目录确认 Speckit 产物已提交后，创建并检出 `feature/009-short-classified-extraction`，创建 `.worktrees/feature-009-short-classified-extraction`；实现只在该 worktree 内进行。
- [x] T002 在 worktree 根目录执行 `python build.py lint`、`python build.py test` 和 `python build.py verify`，记录实现前基线结果。
- [x] T003 [P] 在 `tests/test_extraction_package.py` 和 `tests/test_extraction_site.py` 中补充可复用的嵌套分类样例构造 helper，覆盖 `logs/`、`kpi/`、`config/`、`resource/` 和相同目标冲突来源。

**检查点**：实现分支和 worktree 就绪，基线命令结果已知，测试样例可以表达分类落位需求。

---

## 阶段 2：基础层

**目的**：建立 manifest v4、路径限制抽象和契约基础，阻塞后续用户故事。

- [x] T004 在 `app/services/extraction/layout.py` 将 `MANIFEST_VERSION` 升级为 `4`，定义分类目录常量、安全目标解析、目标冲突记录结构和可注入的 `PathLimitPolicy` 抽象。
- [x] T005 在 `app/services/extraction/manifest.py` 实现 manifest v4 读写与最小校验，保留 `policy` 快照、fingerprint 校验和路径限制上下文，并允许 `files[]`、`subpackages[]`、`log_gz[]` 记录 `source`、`target`、`status`、`error`、`error_code`、`path_length`、`path_limit`。
- [x] T006 在 `tests/test_extraction_policy.py` 和 `tests/test_extract_policy.py` 中补充 manifest 版本、策略 fingerprint 或路径限制上下文变化时必须重建现场的测试；确认策略跳过与白名单行为不回退。
- [x] T007 在 `tests/test_extraction_site.py` 中为 manifest v4 缺失、损坏、版本不匹配场景添加失败测试，验证任务分类现场按新布局重建且 `.main/` 不作为普通规则输入。

**检查点**：manifest v4、策略快照与路径限制抽象就绪；新测试先失败，旧安全防护测试仍能表达目标行为。

---

## 阶段 3：用户故事 1 - 分类现场直接落位（优先级：P1）🎯 MVP

**目标**：分类工作文件直接进入 `output/<task_id>/<category>/`，不再额外插入来源子包目录层，同时保留压缩包内部相对结构。

**独立测试**：构造包含顶层普通分类文件、`.log.gz` 和嵌套分类子包的主包，执行任务后断言目标路径均以分类根开始、不含来源子包名层，且 `.main/` 证据现场不变。

### 用户故事 1 的测试

- [x] T008 [P] [US1] 在 `tests/test_extraction_site.py` 编写失败测试：顶层普通文件应落到 `<category>/<内部相对路径>`，`.log.gz` 应落到 `<category>/<内部相对去后缀路径>`，并断言原始上传包 checksum 与内容不变。
- [x] T009 [P] [US1] 在 `tests/test_extraction_package.py` 编写失败测试：嵌套分类子包展开后的成员直接进入分类根，不出现来源子包目录层；子包内部目录结构保留，且原始上传包 checksum 与内容不变。
- [x] T010 [P] [US1] 在 `tests/test_extraction_policy.py` 编写失败测试：两个来源命中同一目标时保留第一个、后续记录 `conflict`；相同 checksum 子包记录 `duplicate`；策略跳过记录 `skipped`。

### 用户故事 1 的实现

- [x] T011 [US1] 修改 `app/services/extraction/layout.py` 的 `_destination_relative()`：移除来源子包目录层，普通文件保留分类前缀加内部相对路径，工作来源不再拼接 `group`。
- [x] T012 [US1] 修改 `app/services/extraction/nested.py`：子压缩包、日志 gzip 和普通文件按分类根直接落位；目录冲突不覆盖、不生成 checksum 后缀目录，并写入 manifest 记录。
- [x] T013 [US1] 修改 `app/services/extraction/site.py`：主包证据展开后稳定遍历 `.main/`，清空并重建分类根，生成 manifest v4 的 `files[]` 成功记录；保留策略 fingerprint 快照。
- [x] T014 [US1] 调整 `app/inspectors/pkg.py` 与 `app/services/extraction/__init__.py` 的隐藏结果元数据，使 `pkg.extract.*` 汇总与 manifest v4 的来源、目标、状态一致；不把 hidden 规则加入普通规则结果。
- [x] T015 [US1] 更新 `tests/test_extraction_site.py`、`tests/test_extraction_package.py`、`tests/test_baseline_extraction.py` 中受旧目录层影响的断言，并运行目标测试确认通过。

**检查点**：`python build.py verify` 可通过；分类现场路径缩短且结构可预期；冲突、重复、策略跳过记录稳定。

---

## 阶段 4：用户故事 2 - 长路径提前失败（优先级：P1）

**目标**：Windows 传统 MAX_PATH 限制环境下，完整目标路径达到或超过 260 在写入前拒绝，错误包含实际长度、上限、来源和目标。

**独立测试**：注入 `PathLimitPolicy(limit=260, enforce=True)` 后处理包含长目标路径的普通文件、日志 gzip 和子包，断言不产生半成品文件，manifest 项包含 `error_code=path_too_long`、`path_length=279`、`path_limit=260`。

### 用户故事 2 的测试

- [x] T016 [P] [US2] 在 `tests/test_extraction_policy.py` 新增长路径策略单元测试：仅在 `enforce=true` 时拒绝，非 Windows 或长路径启用时不按 260 拒绝；路径长度按解析后的完整目标路径计算。
- [x] T017 [P] [US2] 在 `tests/test_extraction_site.py` 和 `tests/test_extraction_package.py` 添加失败测试：主包 `.main/` 证据目标、普通文件、`.log.gz`、子压缩包和子包成员在写入前命中 `path_too_long` 时不留下对应半成品；主包证据现场失败阻断后续执行。

### 用户故事 2 的实现

- [x] T018 [US2] 在 `app/services/extraction/layout.py` 实现 `PathLimitPolicy`：Windows 且长路径未启用时强制 260；注册表不可读时保守拒绝；非 Windows 默认不启用；提供可注入构造入口。
- [x] T019 [US2] 修改 `app/core/archive.py` 和 `app/services/extraction/nested.py`：在主包 `.main/` 证据目标、普通文件 copy、gzip 创建、子包目标创建和 staging 成员 rename 前调用路径检查；失败项清理 staging 或目标，并记录结构化错误。
- [x] T020 [US2] 修改 `app/services/extraction/site.py` 和 `app/inspectors/pkg.py`：传递路径策略，把 `path_too_long` 明细透传到 manifest 和 hidden 结果 metadata；不使用 `\\?\` 前缀改写。
- [x] T021 [US2] 在 `tests/test_extraction_policy.py`、`tests/test_extraction_site.py` 中确认失败项状态、来源、目标、路径长度和上限可追溯，并运行解压相关测试。

**检查点**：注入长路径场景可稳定提前失败；真实 Windows 行为由策略分支控制；普通规则不会消费半成品现场。

---

## 阶段 5：用户故事 3 - 数据准备状态可见（优先级：P2）

**目标**：任务列表页每个任务卡片内展示可折叠的数据准备摘要和明细，失败、冲突或长路径默认展开。

**独立测试**：分别构造成功、冲突、长路径任务，打开任务列表页；成功任务显示折叠摘要，异常任务默认展开并可手动收起；普通 Pass/Warn/Fail/Skip 统计不包含 `pkg.extract.*`。

### 用户故事 3 的契约与测试

- [x] T022 [US3] 按 `specs/009-short-classified-extraction/contracts/api.md` 更新 `docs/api/openapi.yaml`：新增 `PreparationStatusV2`、`PreparationIssueTypeV2`、`PreparationIssueV2`、`PreparationItemV2`、`DataPreparationV2`，并为 `InspectionTaskV2` 增加可选可空 `preparation`。
- [x] T023 [US3] 执行 `python build.py contract` 和 `python build.py gen-web-api`，同步 `tests/test_contract.py`、`tests/test_schemas.py` 和 `web/src/api/client.ts`。
- [x] T024 [US3] 在 `tests/test_api.py` 添加失败测试：`GET /api/v2/tasks` 和 `GET /api/v2/tasks/{task_id}` 返回 `preparation`；历史任务或无 manifest 任务可返回 `null`；`stats` 不变化。

### 用户故事 3 的实现

- [x] T025 [US3] 在 `app/models/schemas.py` 新增数据准备契约模型，字段与 `docs/api/openapi.yaml` 严格一致；状态枚举为 `pass/warn/fail/skip/error`，问题类型为 `conflict/duplicate/skipped/failed/rejected`。
- [x] T026 [US3] 新建 `app/services/preparation.py`：读取 manifest v4 和 `rules/pkg.extract.*.json`，组装主包与七类分类准备项、耗时、数量和 issues；无来源分类返回 `skip`，冲突返回 `warn`，失败返回 `fail`，主包失败或 manifest 损坏返回 `error`。
- [x] T027 [US3] 修改 `app/services/tasks.py` 与 `app/api/router.py`：任务列表和详情响应挂载 `preparation`；读取失败返回 `null` 或结构化原因，不得改变任务统计和普通规则列表。
- [x] T028 [US3] 修改 `web/src/pages/TaskListPage.tsx`：在对应任务卡片内新增数据准备折叠区；默认摘要展示成功/警告/失败/跳过数量和分类 chips；点击标题或箭头在卡片内展开明细，不使用 Modal、Drawer 或独立页面。
- [x] T029 [US3] 修改 `web/src/pages/TaskListPage.tsx`：失败、冲突或长路径准备项默认展开，展示来源、目标、原因、`path_length` 和 `path_limit`；普通规则统计继续排除 hidden 准备项。
- [x] T030 [US3] 更新 `tests/test_api.py` 与 `web` 构建验证，运行 `python build.py contract`、`python build.py gen-web-api` 和 `python build.py test` 确认通过。

**检查点**：任务列表无需进入详情页即可识别准备失败；成功任务不放大噪音；契约、生成客户端和后端模型一致。

---

## 阶段 6：用户故事 4 - 删除失败可见可重试（优先级：P2）

**目标**：删除现场失败时返回结构化错误，任务列表展示完整错误 5 秒后收起，保留可重新展开的失败状态并支持重试。

**独立测试**：模拟 `shutil.rmtree` 抛出 Windows 长路径或目录占用错误，调用删除 API 后任务仍可列出；响应包含 `task_delete_failed` 和现场上下文；前端完整提示 5 秒收起、可重新展开、重试成功后清除。

### 用户故事 4 的契约与测试

- [x] T031 [US4] 更新 `docs/api/openapi.yaml`：为 `DELETE /api/v2/tasks/{task_id}` 新增 `500 task_delete_failed` 响应，保持 `204`、`404`、`409 task_busy` 语义不变，并描述 `detail.task_id`、`locations`、`failed_path`、`path_length`、`path_limit`。
- [x] T032 [US4] 执行 `python build.py contract` 和 `python build.py gen-web-api`，更新 `web/src/api/http.ts` 的结构化 `detail` 解析类型与 `tests/test_contract.py`。
- [x] T033 [US4] 在 `tests/test_delete_race.py` 和 `tests/test_api.py` 添加失败测试：目录删除失败返回 500 与结构化 detail；在线任务数据库记录仍在，任务仍可从列表返回；本地任务失败后 `output/<task_id>/task.json` 可恢复读取。

### 用户故事 4 的实现

- [x] T034 [US4] 在 `app/services/tasks.py` 定义 `TaskDeleteError`，调整删除顺序：文件现场全部成功后才删除数据库记录；删除前读取本地 `task.json`，失败后若该文件缺失则恢复。
- [x] T035 [US4] 在 `app/services/tasks.py` 的 `_remove_tree()` 中识别长路径、目录占用、权限和其他 `OSError`，保留重试瞬时 WinError 145 的既有策略，并生成包含失败路径、可选路径长度和上限的上下文。
- [x] T036 [US4] 修改 `app/api/router.py`：捕获 `TaskDeleteError` 并映射为 500 `{code:"task_delete_failed", message, detail}`；不把失败响应表达为“任务已删除”。
- [x] T037 [US4] 修改 `app/services/tasks.py` 的任务列表 fallback：完成态在线任务在 output 部分删除但数据库记录仍存在时仍可返回；不改变正常任务排序和分页。
- [x] T038 [US4] 修改 `web/src/pages/TaskListPage.tsx`：维护按 `task_id` 隔离的删除失败状态；完整行内 Alert 展示 5 秒后收起，保留“删除失败”状态并支持重新展开；展示任务、现场位置、原因和可选长度信息。
- [x] T039 [US4] 修改 `web/src/pages/TaskListPage.tsx`：提供 loading 态“重试删除”；成功后清除该任务错误状态、刷新列表并移除任务；失败时更新同一任务的状态而不弹全局成功提示。
- [x] T040 [US4] 更新 `tests/test_delete_race.py`、`tests/test_api.py` 和前端构建验证，运行删除相关测试确认通过。

**检查点**：删除失败不再只是短暂 toast；任务保持可见且可重试；成功路径仍返回 204 并级联删除 uploads/output/数据库记录。

---

## 阶段 7：收尾与横切关注点

**目的**：统一契约、文档、日志、安全和质量门禁。

- [x] T041 检查 `app/services/extraction/layout.py`、`app/services/extraction/nested.py`、`app/core/archive.py` 的安全防护：路径穿越、符号链接、重复路径、深度、文件数、单文件大小和总字节预算全部保留。
- [x] T042 [P] 在 `app/services/extraction/site.py`、`app/services/extraction/nested.py`、`app/services/tasks.py` 中确认 structlog 记录包含 `task_id`、规则或删除上下文、来源/目标、状态、错误码；不输出完整超长路径以外的敏感内容。
- [x] T043 [P] 更新 `docs/architecture.md`、`docs/design/mechanisms.md` 或相关设计文档中旧的分类路径、manifest 版本和删除错误说明；不修改无关章节。
- [x] T044 [P] 检查 `docs/example/real-package-structure.md` 与真实样例路径说明，补充分类现场不再包含来源包目录层、`.main/` 仍保留原始证据的说明。
- [x] T045 运行 `python build.py contract` 和 `python build.py gen-web-api`，确认 OpenAPI、Pydantic 和生成客户端无漂移。
- [x] T046 运行 `python build.py lint`、`python build.py test`、`python build.py verify`；随后在 `web/` 运行 `npm run build`。
- [x] T047 按 `specs/009-short-classified-extraction/quickstart.md` 用 `local_run/` 样例验证本地全流程、任务列表折叠状态和删除失败交互。
- [x] T048 汇总变更、验证结果和残留风险，准备实现分支 review；不得合并未经完整门禁验证的代码。

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 1 设置**：必须最先完成；实现只能发生在 `feature/009-short-classified-extraction` worktree。
- **阶段 2 基础层**：依赖设置完成；manifest v4 和路径策略抽象阻塞 US1/US2。
- **阶段 3 US1**：依赖阶段 2；是 MVP 核心路径。
- **阶段 4 US2**：依赖阶段 2；建议在 US1 后执行，因为长路径检查挂在直接分类落位流程上。
- **阶段 5 US3**：依赖 manifest v4 和 US1 的落位明细；前端展示可在 US1 稳定后开始。
- **阶段 6 US4**：依赖契约基础，但核心删除服务可与 US3 后端工作并行；前端状态展示依赖任务列表页已有结构。
- **阶段 7 收尾**：依赖所有用户故事完成。

### 用户故事依赖

- **US1**：只依赖基础层，可独立用样例包验证。
- **US2**：依赖 `PathLimitPolicy` 和分类落位调用点；独立通过注入策略验证。
- **US3**：依赖 manifest v4 和 US1 产生的目标、冲突、路径错误明细；契约更新完成后可独立验证 API/UI。
- **US4**：与 US1/US2 的删除残留风险直接相关，但删除服务契约和前端交互可独立测试。

### 每个故事内部顺序

1. 先写并确认失败测试。
2. 更新公共契约（如涉及）。
3. 实现数据模型/服务。
4. 接入 API 或执行器。
5. 更新前端和生成客户端。
6. 运行故事内测试与必要全流程验证。

### 并行机会

- T003、T006/T007 中的不同测试文件可并行准备。
- T008–T010 三个测试文件互不修改，可并行。
- T016–T017 长路径测试可并行。
- T024 API 准备状态测试可与前端草稿并行，但依赖 T022/T023。
- T033 在 T031/T032 完成后可编写，并与 T034/T035 的实现准备工作交错执行。
- T042–T044 文档与日志检查可并行。

---

## 实现策略

### MVP

1. 完成阶段 1、2。
2. 完成 US1，运行 `python build.py verify`。
3. 若只交付 MVP，分类路径已经缩短并可观测 manifest 明细；继续 US2 后才能满足 Windows 长路径约束。

### 推荐完整增量

1. 设置 + 基础层。
2. US1 分类落位。
3. US2 长路径防护。
4. US3 数据准备展示。
5. US4 删除失败展示与重试。
6. 收尾质量门禁和文档同步。

---

## 注意事项

- 禁止缩短、哈希化、重命名或迁移 `task_id`。
- 禁止使用 `\\?\` 前缀静默绕过 Windows 长路径。
- 禁止让普通规则读取 `.main/` 证据现场。
- 禁止把 `pkg.extract.*` 加入普通规则统计或普通规则列表。
- 禁止破坏 `RuleResult`、`Metric`、`Finding`、`TaskStats` 既有字段语义。
- 每个 T 任务或逻辑组完成后在 worktree 内提交；提交信息使用 `<type>(<scope>): <subject>`。
