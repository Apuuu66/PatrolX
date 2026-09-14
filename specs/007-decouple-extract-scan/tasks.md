# 任务：解压与规则扫描解耦

**输入**：来自 [`specs/007-decouple-extract-scan/`](spec.md) 的设计文档  
**前置条件**：[plan.md](plan.md)、[spec.md](spec.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/internal-extraction-scan.md](contracts/internal-extraction-scan.md)、[quickstart.md](quickstart.md)  
**测试**：包含测试任务；本功能是执行器与解压重构，必须按 TDD 和回归兼容要求验证。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）。
- **[US1]**：解压与读取解耦。
- **[US2]**：规则扫描统一使用声明式完整匹配。
- **[US3]**：整理解压与扫描职责。
- **[US4]**：保持结果契约与双模式一致。

---

## 阶段 1：设置

**目的**：建立实现现场并锁定重构基线。

- [x] T001 执行 `git worktree list`，创建或复用 `feature/decouple-extract-scan` 的 worktree `.worktrees/feature-decouple-extract-scan/`；先提交 `specs/007-decouple-extract-scan/` 全部规划产物，再在 worktree 内实施。
- [x] T002 [P] 在 `tests/test_extraction_site.py` 中整理并保留现有主包、嵌套包、`.log.gz`、manifest v3 和安全拒绝回归场景；如存在缺口，先补充失败测试。
- [x] T003 [P] 在 `tests/test_baseline_pipeline.py`、`tests/test_baseline_consistency.py` 和 `tests/test_online_identity.py` 中确认现有任务结果、`RuleResult` 字段、CLI/API 语义和报告基线；不得修改公共期望字段。

**检查点**：实现分支和 worktree 已就绪；现有回归基线明确。

---

## 阶段 2：基础层

**目的**：先建立解压与扫描共同依赖的布局、预算、manifest 和测试夹具。

- [x] T004 在 `app/services/extraction/layout.py` 中创建分类目录常量、主证据目录常量、目标路径推导、路径穿越/符号链接防护和空目录清理 helper；由 `app/core/classify.py` 的分类结果驱动，不感知规则实现。
- [x] T005 [P] 在 `app/services/extraction/budget.py` 中迁移任务级 `ExtractionBudget`，保留任务累计最多 200,000 个文件、2GB 解压总量、最大递归深度 8 的固定预算，并协同 `app/core/archive.py` 的 `UnpackLimit`。
- [x] T006 在 `app/services/extraction/manifest.py` 中迁移 `manifest_path()`、`read_manifest()`、`write_manifest()`、`reusable_manifest()` 和 v3 最小结构校验；保持 `.patrolx-extracted.json`、`main`、`subpackages`、`log_gz`、`rejected` 语义不变。
- [x] T007 [P] 在 `tests/test_scanning_catalog.py` 中新增失败测试，覆盖七个 category 白名单、`.main/`、manifest、`prepared/`、任务元数据、规则结果、报告和执行日志排除、POSIX 路径排序、缺失 category 目录和链接/越界拒绝。
- [x] T008 [P] 在 `tests/test_scanning_matcher.py` 中新增失败测试，覆盖 `re.fullmatch()`、多模式并集去重、稳定排序、非法正则、空/首尾空白/绝对路径/路径穿越/`~` 拒绝。

**检查点**：布局、预算和 manifest 的纯基础能力通过单元测试；catalog 与 matcher 的期望测试已失败。

---

## 阶段 3：用户故事 1 - 解压与读取解耦（P1）

**故事目标**：大主包、小主包、嵌套子包和 `.log.gz` 统一在 `EXTRACT` 展开；普通规则只读已解压相对路径。

**独立测试**：执行包含嵌套包、`.log.gz` 和普通文件的大包，以及只含单一 category 的小包；检查 `.main/`、category 现场、manifest 状态、幂等复用、局部失败隔离和 prepare 不解压。

- [x] T009 [US1] 在 `tests/test_extraction_package.py` 中新增失败测试，分别覆盖大主包嵌套日志/KPI、小主包单 category、重复执行复用 manifest、checksum 损坏重建、主包失败阻断、子包/`.log.gz` 局部失败继续。
- [x] T010 [US1] 在 `app/services/extraction/nested.py` 中迁移子包与 `.log.gz` 有界递归展开；保留 staging、checksum 去重、冲突/失败/拒绝状态、来源关系和结构化日志。
- [x] T011 [US1] 在 `app/services/extraction/site.py` 中迁移 `extract_main_site()` 与 `category_failures()`；实现 `.main.staging/` → `.main/` 原子替换、`.main.previous/` 恢复、分类现场清理重建和 manifest 终态写入。
- [x] T012 [US1] 在 `app/services/extraction/__init__.py` 中提供兼容 facade，导出 `extract_main_site()`、`category_failures()`、manifest API、`ExtractionLogger`、`ExtractionBudget` 和常量；更新 `app/inspectors/pkg.py` 引用并保持隐藏规则行为。
- [x] T013 [US1] 运行 `pytest -q tests/test_extraction_site.py tests/test_extraction_package.py tests/test_baseline_extraction.py`，修复回归并确认同一包重复执行不重复解压、局部失败可追溯。

**检查点**：解压服务可独立演进；普通规则没有解压调用，prepare 没有通用解压。

---

## 阶段 4：用户故事 2 - 规则扫描统一使用声明式完整匹配（P1）

**故事目标**：解压后构建一次内存 `TaskFileCatalog`，普通规则和 owner prepare 只通过该清单匹配文件。

**独立测试**：对每个代表性规则，断言实际 `ctx.files` 等于 catalog 上 `source_patterns[]` 的 fullmatch 结果；无匹配返回 `skip`，非法模式被拒绝。

- [x] T014 [US2] 在 `app/services/scanning/catalog.py` 中实现 `TaskFileCatalog.build()`、`paths()`、`match()`、`resolve()`；清单不持久化，只保存并返回 `/` 归一化、去重且稳定排序的相对路径。
- [x] T015 [US2] 在 `app/services/scanning/matcher.py` 和 `app/services/scanning/__init__.py` 中实现模式防御校验与 `re.fullmatch()`；`matcher` 不做文件系统遍历，`catalog` 不修改文件系统。
- [x] T016 [US2] 在 `app/services/executor.py` 中为 `RuleContext` 注入 catalog，新增 `ensure_catalog()`；全量执行在 `EXTRACT` 屏障后构建一次，单规则重跑先确保解压现场就绪再构建。
- [x] T017 [US2] 更新 `app/services/prepare.py`：删除 `match_relative_files()`，只保留 `prepared_dir()`、`marker_path()`、`rule_python_path()`、`rule_file_sha256()`；更新 `app/services/executor.py` 与相关测试调用。
- [x] T018 [US2] 在 `tests/test_executor.py`、`tests/test_prepare_pipeline.py`、`tests/test_prepare_cache.py` 和 `tests/test_rerun_status.py` 中更新并补充失败测试，覆盖 catalog 注入、prepare 输入、缓存命中/重建、无匹配 `skip`、prepare 失败隔离和非法 pattern 拒绝。
- [x] T019 [US2] 运行 `pytest -q tests/test_scanning_catalog.py tests/test_scanning_matcher.py tests/test_executor.py tests/test_prepare_pipeline.py tests/test_prepare_cache.py tests/test_rerun_status.py`，修复回归并确认所有普通规则匹配来自同一 catalog。

**检查点**：普通规则不再遍历任务目录；prepare 不再拥有通用扫描函数。

---

## 阶段 5：用户故事 3 - 整理解压与扫描职责（P2）

**故事目标**：删除混合职责入口，固化模块依赖边界和文件位置。

**独立测试**：静态边界测试确认依赖方向；仓库中没有旧的单文件混合入口和 prepare 通用扫描 helper。

- [x] T020 [US3] 删除旧 `app/services/extraction.py`；确认 `app/services/extraction/` facade 后，更新 `app/` 与 `tests/` 中所有 import。
- [x] T021 [US3] 清理 `app/services/prepare.py` 中扫描相关 import，确认 `app/services/scanning`、`app/services/prepare`、`app/services/extraction` 与 `app/inspectors` 遵守 `contracts/internal-extraction-scan.md` 的依赖规则。
- [x] T022 [P] [US3] 在 `tests/test_service_boundaries.py` 中新增静态边界测试，断言 extraction 不导入 scanning、scanning 不导入 prepare、prepare 不导入 scanning、普通规则不导入其他规则实现。
- [x] T023 [P] [US3] 更新 `docs/architecture.md`、`docs/design/mechanisms.md` 和 `docs/data-model.md`，描述统一 `EXTRACT`、`TaskFileCatalog`、matcher、prepare 边界和单规则重跑流程；不修改 OpenAPI 契约。

**检查点**：文件边界清晰、无跨职责循环依赖；文档与代码结构一致。

---

## 阶段 6：用户故事 4 - 保持结果契约与双模式一致（P2）

**故事目标**：重构不破坏任务、规则、指标、发现、证据、来源路径和本地/在线结果语义。

**独立测试**：同一上传包分别通过 CLI/API 执行，除执行标识和时间戳外规则结果语义一致；单规则重跑只更新目标规则、摘要和报告。

- [x] T024 [P] [US4] 在 `tests/test_online_identity.py` 和 `tests/test_baseline_consistency.py` 中补充或收紧 CLI/API catalog 匹配路径、规则结果语义、执行顺序和来源路径一致性断言。
- [x] T025 [US4] 在 `tests/test_baseline_rerun.py` 和 `tests/test_rerun_status.py` 中验证单规则重跑：manifest 有效时复用现场，只执行目标 prepare/inspect，无关规则 JSON 不变，任务摘要与报告正确刷新。
- [x] T026 [US4] 运行 `make contract` 检查 OpenAPI 漂移；若出现差异，停止实现并回到 Speckit review，不得在任务内私自改契约。
- [x] T027 [US4] 运行 `pytest -q tests/test_baseline_rerun.py tests/test_rerun_status.py tests/test_baseline_consistency.py tests/test_online_identity.py tests/test_contract.py`，修复兼容性回归。

**检查点**：公共契约兼容；单规则重跑行为稳定；CLI/API 结果一致。

---

## 阶段 7：收尾与横切关注点

**目的**：验证安全、可观测性和全流程质量门禁。

- [x] T028 在 `tests/test_archive.py`、`tests/test_extraction_package.py` 和 `tests/test_scanning_catalog.py` 中复核路径穿越、符号链接、深度、文件数、总量、checksum 去重和 catalog 越界拒绝均有断言。
- [x] T029 在 `tests/test_observability.py` 中确认主包、子包、`.log.gz`、catalog、pattern 拒绝、prepare 状态和 inspect 无匹配日志包含 `contracts/internal-extraction-scan.md` 要求的任务、规则、路径或原因上下文。
- [x] T030 [P] 按 `specs/007-decouple-extract-scan/quickstart.md` 手工执行大主包、小主包、单规则重跑和安全场景；记录任何有意行为优化。
- [x] T031 依次运行 `make lint`、`make test`、`make verify`；全部通过后更新 `specs/007-decouple-extract-scan/tasks.md` 复选框并在 worktree 内提交实现。

---

## 依赖与执行顺序

### 阶段依赖

1. 阶段 1 设置无前置依赖。
2. 阶段 2 基础层依赖设置完成，阻塞所有用户故事。
3. US1 依赖基础层布局、预算、manifest。
4. US2 依赖基础层 catalog/matcher 期望和 US1 的 category 终态。
5. US3 依赖 US1/US2 的服务包稳定后清理旧入口。
6. US4 依赖 US1/US2 行为完成，可与 US3 的文档/清理并行验证。
7. 收尾依赖所有用户故事完成。

### 用户故事依赖

- US1 可在基础层后开始，是 US2 catalog 构建时机的前置。
- US2 在基础层后可先行编写测试，但完整验证依赖 US1。
- US3 的删除与静态边界测试依赖 US1/US2。
- US4 是兼容性验收，依赖重构行为完成，但契约基线可在设置阶段准备。

### 并行机会

- T002、T003 可并行。
- T005、T007、T008 可并行。
- US1 和 US2 的测试编写可并行，但实现和集成验证建议按 US1 → US2。
- T022、T023 可并行。
- T024 可在 US4 内与 T025 并行准备，最终一起验证。
- T030 手工 quickstart 可与 T028/T029 补充并行，但最终验证依赖所有测试通过。

---

## 实现策略

### MVP 优先（US1 + US2）

1. 完成设置与基础层。
2. 完成 US1，验证解压终态与幂等。
3. 完成 US2，验证唯一 catalog 和 fullmatch。
4. 停止并运行 `make lint`、`make test`、`make verify`。
5. US1 + US2 达成核心解耦价值，可作为可演示增量。

### 增量交付

1. US1 + US2：降低耦合并统一扫描。
2. US3：清理文件边界与文档。
3. US4：确认契约兼容和双模式一致。
4. 收尾：安全、日志、quickstart 和完整门禁。
