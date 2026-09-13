---
description: "功能实现任务列表：保留主包解压现场并原地解压日志压缩文件"
---

# 任务：保留主包解压现场并原地解压日志压缩文件

**输入**：来自 `specs/005-main-log-gz-extract/` 的设计文档。

**组织方式**：任务按用户故事分组；每个故事先编写失败测试，再实现与集成。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：任务所属用户故事
- 路径均相对于仓库根目录

---

## 阶段 1：基础契约与测试现场

**目的**：建立可共享、可验证的解压状态与测试基础设施。

- [ ] T001 [P] 在 `tests/test_extraction_site.py` 中创建归档工厂 helper，支持构造主包、KPI 子包、日志子包、`.log`、`.log.gz`、损坏 gzip、同名冲突、多级嵌套与超预算样例。
- [ ] T002 在 `app/services/extraction.py` 中定义内部解压状态模型与 manifest v3 读写框架，覆盖 `main`、`subpackages`、`log_gz`、`rejected`、版本号和非 v3 manifest 的不信任重建路径。
- [ ] T003 [P] 在 `tests/test_extraction_site.py` 中添加 manifest v3 结构、必填字段、非法路径防护与旧版本重建的单元测试。

**检查点**：manifest 契约和测试工厂就绪，后续用户故事可以共享同一状态模型。

---

## 阶段 2：用户故事 1 - 保留主包原始解压现场（优先级：P1）🎯 MVP

**目标**：主包解压后同时保留 `.main/` 原始现场和分类工作现场，普通规则不读取 `.main/`。

**独立测试**：执行包含多层目录与多类文件的包后，断言 `.main/` 路径集合与上传包一致，分类现场存在工作副本，普通规则匹配结果不包含 `.main/`，且 `uploads/` 包不变。

### 测试

- [ ] T004 [P] [US1] 在 `tests/test_extraction_site.py` 中编写测试：`.main/` 保留上传包 100% 原始相对文件路径，分类工作目录生成对应最终文件，`uploads/` 原始包 checksum 不变。
- [ ] T005 [P] [US1] 在 `tests/test_extraction_site.py` 中编写测试：普通规则文件匹配排除 `.main/`，同一内容不会同时从 `.main/` 与分类现场重复进入规则输入。

### 实现

- [ ] T006 [US1] 在 `app/services/extraction.py` 中实现主包安全解压到临时目录、checksum 校验、临时目录校验后原子替换/建立 `.main/` 的流程。
- [ ] T007 [US1] 在 `app/services/extraction.py` 中实现“保留 `.main/`、复制到分类工作现场”的落位语义：非压缩文件复制到 `logs/`、`kpi/`、`traffic/`、`alarm/`、`config/`、`resource/`、`other/`，并保留 `.main/` 内相对目录结构。
- [ ] T008 [US1] 重构 `app/inspectors/pkg.py` 的 `pkg.extract.main`，改为调用 `app/services/extraction.py`；主包失败仍阻断，成功时记录 manifest 的 checksum、文件数、证据路径与复用状态。
- [ ] T009 [US1] 在 `app/services/prepare.py` 的普通规则匹配入口中显式排除 `.main/` 与 manifest 文件，防止路径模式误匹配证据现场。
- [ ] T010 [US1] 运行 `pytest tests/test_extraction_site.py tests/test_baseline_extraction.py tests/test_baseline_pipeline.py`，确认主包现场保留且既有任务语义不回退。

**检查点**：`.main/`、`uploads/` 和分类现场稳定保留，普通规则输入不包含证据现场。

---

## 阶段 3：用户故事 2 - 按分类展开日志子包并解压历史日志（优先级：P1）

**目标**：日志子包进入 `logs/` 后继续展开，`.log.gz` 展开为同目录同名 `.log`，`logs/` 只保留最终解压结果。

**独立测试**：执行包含普通 `.log` 与 `.log.gz` 的日志子包后，断言 `.log.gz` 同目录生成 `.log`，`logs/` 不含日志子包和已成功展开的 `.log.gz`，`.main/` 仍保留原始证据，日志规则只消费一份文本日志。

### 测试

- [ ] T011 [P] [US2] 在 `tests/test_extraction_site.py` 中编写测试：主包内日志子包展开后保留服务/节点目录层级，`app_history.log.gz` 生成同目录 `app_history.log`。
- [ ] T012 [P] [US2] 在 `tests/test_extraction_site.py` 中编写测试：成功展开后 `logs/` 不存在 `.zip`、`.tar.gz`、`.tgz`、`.tar` 和已成功展开的 `.log.gz`，`.main/` 中对应原始文件仍存在。
- [ ] T013 [P] [US2] 在 `tests/test_extraction_site.py` 中编写日志规则输入测试：日志规则只匹配最终 `.log`，不匹配 `.log.gz`，重复内容指标与单一文本日志一致。

### 实现

- [ ] T014 [US2] 在 `app/core/archive.py` 中新增受控 gzip 流式展开能力，执行目标路径、单文件大小、任务累计字节数和输出路径校验，不引入新运行时依赖。
- [ ] T015 [US2] 在 `app/services/extraction.py` 中实现 `.log.gz` 展开：同目录生成 `.log`，记录 `source_evidence`、`source_relative_path`、`target`、状态与错误；成功后从 `logs/` 移除 `.log.gz`。
- [ ] T016 [US2] 将 `pkg.extract.logs` 改为调用共享展开服务，确保日志子包、普通日志文件与 `.log.gz` 在同一任务级状态机中处理。
- [ ] T017 [US2] 检查并递增受输入语义影响的 `app/inspectors/log/*.py` 日志规则 `rule_version`；不修改业务统计口径。
- [ ] T018 [US2] 运行 `pytest tests/test_extraction_site.py tests/test_rules.py tests/test_baseline_extraction.py`，确认日志展开、文件清理与日志规则输入符合规格。

**检查点**：`logs/` 是干净的最终日志现场，历史日志可巡检且不会重复统计。

---

## 阶段 4：用户故事 3 - 通用展开多级子压缩包（优先级：P1）

**目标**：任意分类子包中发现的压缩包都能按自身业务特征递归展开到对应分类现场，并受任务级安全预算约束。

**独立测试**：执行 `主包 → KPI 外层子包 → KPI 数据子包 + 日志子包` 样例后，KPI 文件进入 `kpi/`，日志进入 `logs/`，分类现场无中间压缩包，manifest 记录每层分类依据、深度、checksum 和状态。

### 测试

- [ ] T019 [P] [US3] 在 `tests/test_extraction_site.py` 中编写多级展开测试：KPI 子包内的 KPI 子包解压到 `kpi/`，KPI 子包内的日志子包解压到 `logs/`。
- [ ] T020 [P] [US3] 在 `tests/test_extraction_site.py` 中编写分类依据测试：子包按自身文件名/内容优先分类，无法识别时继承父分类或进入可解释 `other/`，manifest 记录 `classification_reason`。
- [ ] T021 [P] [US3] 在 `tests/test_extraction_site.py` 中编写安全预算测试：超深度、超文件数、超单文件大小或任务累计总大小的子包被拒绝并记录原因，不产生越界路径，不中断其他子包。
- [ ] T022 [P] [US3] 在 `tests/test_extraction_site.py` 中编写 checksum 去重测试：同一子包 checksum 只展开一次，重复项记录 `duplicate`，不复制重复展开结果。

### 实现

- [ ] T023 [US3] 在 `app/services/extraction.py` 中实现通用递归展开队列：临时工作区解压、扫描子包、按自身特征分类、跨分类落位、成功后清理分类现场中的中间压缩包。
- [ ] T024 [US3] 在 `app/services/extraction.py` 中加入任务级累计安全预算，聚合既有单包深度、文件数、单文件大小与总大小限制；拒绝项写入 `rejected` 或对应状态。
- [ ] T025 [US3] 重构 `app/inspectors/pkg.py` 的全部 `pkg.extract.<category>` 隐藏规则，使其按 manifest 待处理项调用共享服务；保持隐藏规则名称、优先级和 P0 编排不变。
- [ ] T026 [US3] 运行 `pytest tests/test_extraction_site.py tests/test_baseline_extraction.py tests/test_prepare_pipeline.py`，确认多级、跨分类、预算与去重行为符合规格。

**检查点**：递归展开不限于日志类别，KPI、日志和其他分类均可安全落位。

---

## 阶段 5：用户故事 4 - 保留失败和冲突现场（优先级：P2）

**目标**：单个子包或 `.log.gz` 失败、冲突时保留证据、记录原因并继续后续处理。

**独立测试**：执行包含正常 gzip、损坏 gzip 和同名冲突 gzip 的包后，任务完成，正常 `.log` 可巡检，异常项保留原始证据并在 manifest/日志中有显式原因，规则状态为 `warn` 或明确记录失败。

### 测试

- [ ] T027 [P] [US4] 在 `tests/test_extraction_site.py` 中编写损坏 `.log.gz` 测试：不生成 `.log`、不保留失败中间文件、保留 `.log.gz` 原始证据、记录 `failed` 和原因、任务继续完成。
- [ ] T028 [P] [US4] 在 `tests/test_extraction_site.py` 中编写同名冲突测试：已有 `.log` 不被覆盖、`.log.gz` 保留、记录 `conflict` 与原因、其他日志不受影响。
- [ ] T029 [P] [US4] 在 `tests/test_extraction_site.py` 中编写重跑幂等测试：连续执行两次后文件集合、日志指标、成功状态一致，`.main/` 不被破坏，成功项不重复展开。

### 实现

- [ ] T030 [US4] 在 `app/services/extraction.py` 中实现子包/gzip 单项异常隔离：临时工作区失败清理中间结果，原始证据保留，结构化日志记录任务、规则、来源、目标、状态与错误。
- [ ] T031 [US4] 在 `app/services/extraction.py` 中实现幂等恢复逻辑：按 manifest 与文件 checksum 判断可复用现场；不覆盖既有结果；旧 manifest 或 checksum 变化时安全重建分类现场且只整体替换 `.main/`。
- [ ] T032 [US4] 在 `app/inspectors/pkg.py` 中保持隐藏规则结果对失败/冲突可见，使用 `warn` 汇总失败数和失败明细，不将其显示为普通业务规则。
- [ ] T033 [US4] 运行 `pytest tests/test_extraction_site.py tests/test_baseline_rerun.py tests/test_prepare_pipeline.py`，确认失败隔离和重跑幂等符合规格。

**检查点**：局部失败可追溯、不扩散；重跑不会重复统计或破坏现场。

---

## 阶段 6：收尾与横切验证

**目的**：完成文档一致性、契约确认和全流程验证。

- [ ] T034 [P] 更新 `docs/architecture.md` 与 `docs/example/real-package-structure.md`，描述 `.main/` 证据现场、分类副本、递归子包、`.log.gz` 展开和 manifest v3。
- [ ] T035 [P] 核对 `specs/005-main-log-gz-extract/contracts/extract-manifest.md` 与实现行为一致；不修改 `docs/api/openapi.yaml`，并运行 `make contract` 确认 HTTP 契约无意外差异。
- [ ] T036 运行 `make lint`、`make test`、`make verify`，使用 `specs/005-main-log-gz-extract/quickstart.md` 场景验证真实样例、嵌套 KPI/日志、失败隔离与重跑幂等。

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 1**：最先完成；T002 是 T006、T014、T015、T023、T024、T030、T031 的状态模型基础。
- **US1（阶段 2）**：依赖阶段 1；是后续子包递归与 gzip 展开的现场基础。
- **US2（阶段 3）**：依赖 US1 的现场保留与复制语义。
- **US3（阶段 4）**：依赖 US1；可与 US2 的共享服务合并实现，但验收不得依赖 US2 先完成。
- **US4（阶段 5）**：依赖阶段 1；建议在 US1-US3 后执行，以验证完整失败隔离和幂等。
- **收尾（阶段 6）**：依赖所有 P1/P2 用户故事完成。

### 故事内部顺序

- 测试先于实现，并确认失败。
- 状态模型先于主包现场，现场先于递归展开，递归展开先于横切验证。
- 同一文件任务按编号顺序执行；标记 `[P]` 的测试可在不同文件/fixture 场景中并行编写。

### 并行机会

- 不同用户故事的测试任务可并行起草，但实现文件存在依赖时应按 T001→T033 顺序合入。
- 文档任务 T034、T035 可与实现后验证并行准备，但必须在 `make verify` 前定稿。

---

## 实现策略

1. 完成阶段 1，确认 manifest 模型与测试工厂可用。
2. 完成 US1 并验证主包现场保留，这是 MVP。
3. 完成 US2，验证日志最终现场和重复统计防护。
4. 完成 US3，验证任意分类多级子包。
5. 完成 US4，验证失败、冲突和重跑。
6. 执行收尾验证；全部通过前不提交功能完成结论。
