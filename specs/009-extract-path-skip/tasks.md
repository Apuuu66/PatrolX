---
description: "压缩项解压跳过与白名单策略实现任务列表"
---

# 任务：压缩项解压跳过与白名单策略

**输入**：来自 `/specs/009-extract-path-skip/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**测试**：项目交付门槛和 AGENTS.md 要求 TDD；每个用户故事先补失败测试，再实现。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事
- 描述中包含精确文件路径

## 阶段 1：设置（共享基础设施）

**目的**：建立项目级配置入口和可复用的测试基础。

- [ ] T001 创建 `deploy/config/extract_policy.yaml`，包含 `version: 1`、`nested.skip_all: false`、`nested.skip_paths: []`、`whitelist.paths: []`、`whitelist.name_keywords: ["alarm"]`。该配置结构由 `ExtractPolicyConfig` 和策略加载测试约束，不新增 JSON Schema。
- [ ] T002 [P] 在 `tests/test_extract_policy.py` 创建策略加载测试骨架和临时配置 helper，覆盖配置文件缺失、空配置、非法版本、未知键、非法路径和非法关键字场景。
- [ ] T003 [P] 在 `tests/test_extraction_policy.py` 创建 manifest 策略契约测试骨架，覆盖旧 manifest 无 `policy` 节可复用、新 manifest 必须有 `policy` 节、`skipped` 状态与失败状态互斥。

**检查点**：配置文件和测试基线就绪；此时策略测试应失败。

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：所有用户故事共同依赖的策略模型、归一化逻辑和 manifest 扩展。

**⚠️ 关键**：本阶段完成前不得开始任何用户故事工作。

- [ ] T004 在 `app/services/extraction/policy.py` 实现 `ExtractPolicyConfig` 与加载器：读取项目级 YAML，处理文件缺失/空文件默认值，校验 `version`、未知键、路径前缀、名称关键字，并在无效配置时抛出统一业务错误。
- [ ] T005 在 `app/services/extraction/policy.py` 实现目录前缀归一化：`/0/ -> 0/`、`/xx/0/ -> xx/0/`；归一化后必须以 `/` 结尾，拒绝空串、`/`、`.`、`..`、空段、越界路径和重复作用域歧义。
- [ ] T006 在 `app/services/extraction/policy.py` 实现策略 fingerprint：对归一化后的 `skip_all`、`skip_paths`、`whitelist_paths`、`whitelist_keywords` 计算 SHA-256，不包含 YAML 注释和无关空白。
- [ ] T007 在 `app/services/extraction/manifest.py` 扩展校验：允许旧 manifest 无 `policy` 节；新 manifest 校验 `policy` 节、fingerprint、路径数组、关键字数组、counters 非负整数；`subpackages.status` 和 `log_gz.status` 支持 `skipped`。`skipped` 必须有非空目标路径，且不得携带错误信息；复制失败、目标冲突或预算拒绝必须使用 `failed` 或 `rejected`。
- [ ] T008 在 `app/services/extraction/__init__.py` 导出策略加载、策略决策和策略跳过查询入口，保持现有公共导入名称不变。

**检查点**：策略可加载、可校验、可生成审计快照；manifest 兼容旧现场。

---

## 阶段 3：用户故事 1 - 保留指定路径内的压缩项（优先级：P1）🎯 MVP

**目标**：命中目录前缀的压缩项不再展开，保留为 category 现场最终文件；范围外行为不变。

**独立测试**：用包含 `/0/`、`/xx/0/` 和范围外压缩项的包执行任务，验证跳过范围内压缩项未展开、范围外正常解压。

### 用户故事 1 的测试

- [ ] T009 [US1] 在 `tests/test_archive.py` 添加路径跳过集成测试：构造 `.main` 证据内的 `0/a.zip`、`xx/0/deep.zip` 和范围外压缩包；配置 `skip_paths: ["/0/", "/xx/0/"]` 后验证跳过项保留在 category 现场、无内部派生文件、范围外正常展开。
- [ ] T010 [US1] 在 `tests/test_archive.py` 添加前缀边界测试：验证 `0/` 不匹配 `0a/file.zip`，`/0/` 等价 `0/`，`/xx/0/` 等价 `xx/0/`。
- [ ] T011 [US1] 在 `tests/test_archive.py` 添加容错测试：跳过路径内的非白名单损坏 zip、密码 zip 或不支持压缩项保持未展开，manifest 记录 `skipped`，任务可安全继续。

### 用户故事 1 的实现

- [ ] T012 [US1] 在 `app/services/extraction/policy.py` 实现目录前缀命中判断：白名单判断预留接口，先返回 `skip`、`reason=skip_path` 和命中作用域。
- [ ] T013 [US1] 在 `app/services/extraction/nested.py` 实现非白名单压缩项保留落位：跳过嵌套 zip/tar 时不读取成员、不递归展开；evidence 来源复制到 category 现场，嵌套现场来源原地保留；复制成功后才记录 `skipped`。复制失败或目标冲突记录局部失败且不覆盖。
- [ ] T014 [US1] 在 `app/services/extraction/nested.py` 实现跳过非白名单 `.log.gz`：不生成同名 `.log`，evidence 来源复制到 `logs/`，嵌套现场来源原地保留；复制成功后才记录 `skipped`，目标冲突处理与压缩包一致。
- [ ] T015 [US1] 在 `app/services/extraction/site.py` 注入项目级策略，遍历证据文件时传递策略；确保无策略或未命中路径时保持 007 行为。
- [ ] T016 [US1] 在 `app/services/executor.py` 的执行器层为无匹配规则补充策略提示：仅当规则自身 `source_patterns[]` 无匹配，且同 category 的解压审计存在 `skipped` 压缩项时，在既有 `skip_reason` 文本中说明可能因项目级解压策略缺少内部文件。普通规则不得读取 manifest，不得读取策略对象，不得感知或依赖其他规则。

**检查点**：路径跳过 MVP 可独立验证；范围外任务与基线一致。

---

## 阶段 4：用户故事 4 - 白名单例外（优先级：P1）

**目标**：白名单路径或名称关键字优先于跳过策略，告警相关压缩项和普通文件继续进入 category 现场。

**独立测试**：配置跳过路径并使用 `alarm` 关键字，验证文件名或目录段包含 `alarm` 的内容按普通流程解压或拷贝，其余命中路径内容仍跳过。

### 用户故事 4 的测试

- [ ] T017 [P] [US4] 在 `tests/test_extract_policy.py` 添加白名单匹配测试：`AlarmFiles/`、`service_ALARM.zip`、`node/alarm.txt` 命中；非告警路径不命中；配置关键字为空时不命中。
- [ ] T018 [US4] 在 `tests/test_archive.py` 添加白名单集成测试：跳过路径内白名单 zip 正常展开；白名单目录下嵌套压缩项正常递归处理；白名单普通文件拷贝到对应 category。
- [ ] T019 [US4] 在 `tests/test_archive.py` 添加优先级测试：同一父路径下白名单内容正常处理，非白名单压缩项保持 `skipped`；白名单路径优先于 `skip_paths`，也优先于全局保留。

### 用户故事 4 的实现

- [ ] T020 [US4] 在 `app/services/extraction/policy.py` 实现白名单路径和名称关键字判断：文件名或任一目录段包含配置关键字即命中，比较忽略大小写；返回 `whitelist`、`reason=whitelist_path` 或 `whitelist_keyword`。
- [ ] T021 [US4] 在 `app/services/extraction/nested.py` 将决策顺序改为白名单优先：命中白名单的 zip/tar 和 `.log.gz` 恢复既有解压、预算、分类、递归和安全检查。
- [ ] T022 [US4] 在 `app/services/extraction/site.py` 与 `app/services/extraction/nested.py` 记录普通文件白名单命中：输出结构化日志，包含任务 ID、来源、目标、原因、作用域或关键字，并累计 `whitelisted_files`。

**检查点**：告警等关键内容不再被路径跳过屏蔽；非白名单内容仍跳过。

---

## 阶段 5：用户故事 2 - 全局保留嵌套压缩项（优先级：P2）

**目标**：项目级开启 `nested.skip_all` 后保留所有非白名单嵌套压缩项，主包本身仍解压。

**独立测试**：使用多层压缩项包并设置 `skip_all: true`，验证主包解压、所有非白名单嵌套项未展开、白名单项仍正常处理。

### 用户故事 2 的测试

- [ ] T023 [US2] 在 `tests/test_archive.py` 添加全局保留测试：`skip_all: true` 时 zip、tar.gz、`.log.gz` 均保留为最终文件，无内部派生文件，主包本身仍解压并分类。
- [ ] T024 [US2] 在 `tests/test_archive.py` 添加全局保留与白名单组合测试：`skip_all: true` 且关键字 `alarm` 时，告警压缩项解压，其他压缩项跳过。

### 用户故事 2 的实现

- [ ] T025 [US2] 在 `app/services/extraction/policy.py` 实现 `skip_all` 判断：仅作用于主包内发现的压缩项，不作用于主包本身；返回 `reason=global_retain`。
- [ ] T026 [US2] 在 `app/services/extraction/nested.py` 将全局保留接入压缩项决策顺序，复用路径跳过的保留落位、冲突处理和预算计费逻辑。

**检查点**：全局保留可与路径跳过、白名单共同工作。

---

## 阶段 6：用户故事 3 - 保持跳过现场可审计（优先级：P2）

**目标**：每个策略压缩项、白名单压缩项和汇总计数都可追溯，并能与局部失败明确区分。

**独立测试**：执行包含跳过、白名单、重复项、损坏项和正常项的包，核对 manifest 状态、原因、来源、目标、counters 和结构化日志。

### 用户故事 3 的测试

- [ ] T027 [P] [US3] 在 `tests/test_extraction_policy.py` 添加 manifest 审计测试：`policy.fingerprint` 稳定、路径数组已归一化、counters 与实际条目一致、`skipped` 与 `failed` / `rejected` 不混淆。
- [ ] T028 [US3] 在 `tests/test_extraction_policy.py` 添加幂等复用测试：同一输入和策略重复执行复用 manifest 和现场；项目策略变更后不自动重建有效旧现场；现场缺失或损坏时按当时策略重建。
- [ ] T029 [P] [US3] 在 `tests/test_observability.py` 添加策略日志测试：跳过、白名单恢复、普通文件白名单命中和目标冲突均输出结构化日志，并包含任务 ID 与路径上下文。

### 用户故事 3 的实现

- [ ] T030 [US3] 在 `app/services/extraction/manifest.py` 实现策略快照和 counters 写入：压缩项逐项记录 `policy.action`、`reason`、`scope`、`keyword`；聚合所有 `skipped` 和 `whitelisted` 计数。`skipped_*` 只统计成功保留项，复制失败或落位失败不计入。
- [ ] T031 [US3] 在 `app/services/extraction/site.py` 实现策略跳过查询：按 category 返回 `subpackages` 和 `log_gz` 中 `skipped` 条目摘要，并确保 `category_failures()` 继续排除 `skipped`。
- [ ] T032 [US3] 在 `app/services/extraction/nested.py` 和 `app/services/extraction/site.py` 统一审计事件字段：来源路径、目标路径、任务 ID、状态、原因、作用域或关键字，避免日志与 manifest 语义不一致。

**检查点**：跳过现场可审计、可排查、可复用。

---

## 阶段 7：收尾与横切关注点

**目的**：同步权威文档、验证双模式一致性和全流程质量门禁。

- [ ] T033 [P] 更新 `docs/architecture.md`：补充部署侧静态 `extract_policy.yaml`、决策顺序、被跳过项落位、manifest v3 可选 `policy` 节和 `TaskFileCatalog` 行为；明确不提供在线配置接口。
- [ ] T034 [P] 更新 `docs/design/mechanisms.md`：补充白名单优先级、名称关键字匹配、主包不可跳过、部署侧静态配置边界和策略变更不重建旧任务的机制。
- [ ] T035 [P] 在 `tests/test_baseline_consistency.py` 补充 CLI 与 API 同一包、同一策略结果一致性的冒烟断言。
- [ ] T036 在 `tests/test_archive_robustness.py` 补充安全回归：跳过路径不能绕过越界、链接、深度、文件数、单文件和总量预算；白名单内容仍走全部安全解压防护。
- [ ] T037 运行 `specs/009-extract-path-skip/quickstart.md` 的端到端验收场景。
- [ ] T038 运行 `python build.py lint`。
- [ ] T039 运行 `python build.py test`。
- [ ] T040 运行 `python build.py verify`。

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：无依赖，可立即开始。
- **基础层（阶段 2）**：依赖阶段 1 配置与测试骨架，阻塞所有用户故事。
- **用户故事阶段**：依赖阶段 2；推荐按优先级执行 US1 → US4 → US2 → US3。
- **收尾（阶段 7）**：依赖 US1、US2、US3、US4 全部完成。

### 用户故事依赖

- **US1 路径跳过**：基础层完成后可开始，是 MVP。
- **US4 白名单例外**：依赖 US1 的保留落位与决策注入，但独立可测。
- **US2 全局保留**：依赖 US1 的保留落位，可复用其实现。
- **US3 可审计**：依赖前三个故事产生的状态；最终统一校验、汇总和日志。

### 用户故事内部

- 测试先写并确认失败，再实现。
- 策略判断先于落位实现。
- 落位实现先于执行器提示和审计收口。
- 每个检查点运行对应测试后再进入下一阶段。

## 并行机会

- 阶段 1：T002、T003 可与 T001 并行。
- 阶段 3：T009、T010、T011 都修改 `tests/test_archive.py`，应顺序补充。
- 阶段 4：T017 可与 archive 集成测试并行；T018、T019 都修改 `tests/test_archive.py`，应顺序补充。
- 阶段 5：T023、T024 都修改 `tests/test_archive.py`，应顺序补充。
- 阶段 6：T027 与 T029 可并行；T028 与 T027 修改同一文件，应在 T027 后执行。
- 阶段 7：T033、T034、T035 可并行；T036 可与其后验证前的文档任务并行。
- 多人协作时，基础层完成后可按 US1、US4、US2 分工，US3 留给集成负责人统一收口。

## 并行示例

```bash
# US1 测试修改同一文件，应顺序执行：
Task: "在 tests/test_archive.py 添加路径跳过集成测试"
Task: "在 tests/test_archive.py 添加前缀边界测试"
Task: "在 tests/test_archive.py 添加跳过范围容错测试"

# 白名单配置测试可与 archive 集成测试分离；archive 内任务顺序执行：
Task: "在 tests/test_extract_policy.py 添加白名单匹配测试"
Task: "在 tests/test_archive.py 添加白名单集成测试"
Task: "在 tests/test_archive.py 添加优先级测试"
```

## 实现策略

### MVP 优先（US1）

1. 完成阶段 1 设置。
2. 完成阶段 2 基础层。
3. 完成阶段 3 US1。
4. 运行策略测试和 `python build.py verify`。
5. 验证通过后形成最小可用能力。

### 增量交付

1. US1：路径级跳过。
2. US4：白名单保护关键内容。
3. US2：全局保留。
4. US3：统一审计与幂等验证。
5. 阶段 7：文档、一致性和质量门禁。

## 注意事项

- 所有实现必须在 `feature/extract-path-skip` 对应 worktree 内完成。
- 不修改 OpenAPI、前端 API 客户端、数据库模型或普通巡检规则。
- 不让普通规则读取 manifest；策略提示只由执行器基于解压审计生成。
- 不在执行代码中硬编码 `alarm`；关键字只来自项目级配置。
- 每个任务或逻辑组完成后提交，提交粒度保持单一主题。
