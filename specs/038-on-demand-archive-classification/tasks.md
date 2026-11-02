---
description: "功能实现任务列表：按真实目录进行按需归档分类"
---

# 任务：按真实目录进行按需归档分类

**输入**：`specs/038-on-demand-archive-classification/spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`
**前置条件**：`spec.md`、`plan.md` 已完成澄清与宪法复核
**测试策略**：本项目宪法要求自动化测试和展示效果验证；每个用户故事的测试任务必须先于对应实现任务执行，并先确认失败。

## 格式

- `[P]`：可并行执行，文件集合不重叠且不依赖未完成任务
- `[USn]`：所属用户故事；仅用户故事阶段使用
- 每个任务都包含可执行动作、准确文件路径和必要的契约约束

## 阶段 1：设置（共享契约与测试入口）

**目的**：先冻结公共契约和测试入口，避免后续实现反向决定接口。

- [x] T001 更新 `docs/api/openapi.yaml`，冻结巡检包 `product` 条件必填、`trim().upper()` 语义、`missing_product`、`invalid_product`、`metadata_not_applicable` 和三类同名任务冲突响应，并明确日志补充包禁止携带省份、运营商和网元类型（FR-001、FR-002、FR-050）
- [x] T002 [P] 在 `tests/test_contract.py` 增加 OpenAPI 契约测试，断言 `docs/api/openapi.yaml` 与 `app/models/schemas.py`、生成前端客户端对 product/package kind 字段和错误码保持一致（FR-001、FR-002、FR-051）
- [x] T003 [P] 在 `tests/test_dicts.py` 增加 product 字典测试，要求 `deploy/config/dicts.yaml` 的 code 严格为 `UMF`、`CSP`，输入仅大小写不同也能匹配（FR-001）
- [x] T004 [P] 在 `tests/test_schemas.py` 增加 schema 测试，覆盖 product 的 `trim().upper()`、非法值、`package_kind=inspection` 条件必填和 `log_supplement` 禁止元数据（FR-001、FR-002、FR-050）
- [x] T005 [P] 新建 `tests/test_unit_runtime.py`，先写 `RuleContext` 与 `UnitRequest` 可序列化传递 product/package kind 的失败测试，并断言 worker 不从路径或包名推断（FR-040、FR-051）

---

## 阶段 2：基础层（阻塞所有用户故事）

**目的**：建立配置、审计、manifest v5、安全错误和两个隐藏解压单元的共同基础。

**⚠️ 关键**：本阶段完成前不得开始用户故事实现。

- [x] T006 实现 `app/models/schemas.py` 的 Product/PackageKind 规范化规则，巡检包只接受 `UMF`/`CSP`，日志补充包 product 为 `null`，并保持 `TaskRecord.customer["product"]` 为唯一持久化位置（FR-001、FR-002）
- [x] T007 更新 `deploy/config/dicts.yaml` 和 `app/core/dicts.py`，统一 product code 为大写 `UMF`/`CSP`，移除依赖展示层大小写转换的业务判断（FR-001）
- [x] T008 更新 `app/services/unit_runtime.py`，为 `RuleContext` 增加 `product`/`package_kind`，为可序列化 `UnitRequest` 增加同名字段，并让 worker 只使用请求值（FR-040、FR-051）
- [x] T009 在 `tests/test_classification_config.py` 先写严格 schema 测试，覆盖顶层键 `{version, profiles, routes}`、重复 YAML key、未知动作、非法 category/target、不可达 fallback、未知 profile 和错误详情（FR-037、FR-038）
- [x] T010 新建 `app/services/extraction/config.py`，实现分类配置读取、严格键校验、profile/anchor 校验、route/selection/target 校验、规范化和稳定错误码 `invalid_classification_config`（FR-037、FR-038）
- [x] T011 在 `tests/test_classification_config.py` 增加同 phase、同 priority、profile 交集 pattern 重叠的 ε-NFA 测试，覆盖 `*`、`?`、`**/`、scene/evidence 等价前缀和告警优先于 ignore（FR-009、FR-023、FR-024、FR-026）
- [x] T012 在 `app/services/extraction/config.py` 实现确定性的 ε-NFA 乘积重叠校验，配置冲突必须整体失败并报告两条 route id、phase、priority 和 profile 交集（FR-009、FR-038）
- [x] T013 新建 `tests/test_classification_runtime.py`，先写 LandedEntry、IgnoredRecord、ConflictRecord、FailureRecord 和 Summary 的严格字段、枚举、计数和 canonical 排序测试（FR-035、FR-036、FR-044、FR-045）
- [x] T014 新建 `app/services/extraction/audit.py`，实现审计记录构造函数、稳定消歧摘要、分类/动作/状态汇总、失败原因和 canonical JSON 序列化（FR-035、FR-036、FR-044、FR-045）
- [x] T015 在 `tests/test_extraction_package.py` 先写 manifest v5 严格结构测试，覆盖重复 JSON key、未知顶层键、entries/ignored/conflicts/failures/catalog 字段、summary 一致性和 v1-v4 一律不可复用（FR-041、FR-046）
- [x] T016 将 `app/services/extraction/manifest.py` 升级为 v5 读写与严格校验，使用 `manifest.json` 作为发布凭据，记录 main checksum/evidence fingerprint、product、classification snapshot、path limit、entries、ignored、conflicts、failures、catalog 和 summary（FR-040、FR-041、FR-046）
- [x] T017 在 `tests/test_archive_robustness.py`、`tests/test_extraction_site.py` 和 `tests/test_classification_runtime.py` 增加路径穿越、绝对路径、符号/硬链接、重复成员、归档深度、成员深度、文件数量、单文件大小、累计字节和目标越界测试，并断言稳定错误码（FR-035、FR-052、SC-012）
- [x] T018 更新 `app/core/archive.py`、`app/services/extraction/budget.py` 和 `app/services/extraction/nested.py`，实现 v5 稳定错误码、链接拒绝、重复成员检测、预算边界和单成员失败隔离（FR-035、FR-052、FR-053）
- [ ] T019 在 `tests/test_preparation.py` 和 `tests/test_executor.py` 先写两个隐藏单元测试，断言注册表只生产 `pkg.extract.main`、`pkg.extract.classification`，且 classification 为 `ERROR` 时 prepare/inspect 被阻断（FR-053、SC-011）
- [ ] T020 重构 `app/inspectors/pkg.py`，仅保留 `pkg.extract.main` 与 `pkg.extract.classification`；classification 返回 `PASS`/`WARN` 时发布有效 catalog，返回 `ERROR` 时禁止 prepare/inspect，并按要求升级隐藏单元 `rule_version`（FR-053、SC-011）
- [ ] T021 在 `tests/test_executor.py` 和 `tests/test_executor_parallel_faults.py` 先写父进程/worker product 与 package kind 传播、ERROR 阻断和 WARN 继续执行的失败测试（FR-051、FR-053）
- [ ] T022 更新 `app/services/executor.py`，把持久化 product/package kind 写入 `RuleContext` 与 `UnitRequest`，并让 EXTRACT 阶段只以两个隐藏解压单元的最终状态决定是否进入 PREPARE/INSPECT（FR-051、FR-053）

**检查点**：基础契约、配置校验、审计模型、manifest v5、安全错误和阶段屏障就绪。

---

## 阶段 3：用户故事 1 - UMF 文件按真实来源目录精细落位（优先级：P1）🎯 MVP

**目标**：只按真实目录后缀和明确文件名模式，把 UMF 文件放到 basic/debug/status/operation-log/mml/kpi/other 等目标路径；未声明展开的归档原样保留。

**独立测试**：使用不同包装深度、目录大小写变化、重复业务目录段和未命中文件的合成 UMF 包，核对目标路径、业务分类、KPI 73 成员和 MESH 14 CSV；不得依赖文件名或内容嗅探。

- [ ] T023 [P] [US1] 新建 `tests/test_classification_umf.py`，先写 scene root、目录段大小写不敏感、`capture_root` 取最右完整目录段、外层包装剥离和 target template 的失败测试，并覆盖仅含 `Operation Logs`/`MML Configurations` 时仍能推导场景根（FR-006、FR-007、FR-011、FR-012、FR-014、FR-015、FR-016、FR-017）
- [ ] T024 [US1] 在 `tests/test_classification_umf.py` 增加 precise route 测试，覆盖 Basic、Debugging、Equipment/MESH/System status、Operation Logs、MML 文本、MML ZIP、KPI ZIP、MESH Metrics ZIP 和 `fallback`，并断言 CSP 非告警与 UMF 未命中文件边界（FR-005、FR-012、FR-013、FR-016、FR-017、FR-018、FR-019、FR-033）
- [ ] T025 [P] [US1] 在 `tests/fixtures/make_real_package.py` 追加固定时间戳、幂等的 UMF 合成目录，覆盖外层设备/问题/包装层、大小写变化、73 个 KPI 成员、14 个 MESH CSV、MML 普通文件和 ZIP、未命中普通文件、`collectandcheck.ini` 和未知 ZIP（FR-006、FR-007、FR-010、FR-018、FR-019）
- [ ] T026 [US1] 新建 `app/services/extraction/classification.py`，实现 profile anchor 推导 scene root、来源后缀匹配、`capture_root` 截取、固定阶段 `alarm > precise > ignore > fallback` 和 priority 选择（FR-003、FR-007、FR-008、FR-009、FR-040）
- [ ] T027 [US1] 扩展 `app/services/extraction/classification.py` 与 `app/services/extraction/nested.py`，实现 `copy`、`expand` 和 `fallback`；KPI/MESH/MML 展开成员不得按成员名或扩展名二次分类（FR-010、FR-017、FR-018、FR-019、FR-033）
- [ ] T028 [US1] 更新 `deploy/config/classify_rules.yaml`，写入 UMF profile anchors 及 `umf.basic`、`umf.debug`、`umf.equipment-status`、`umf.mesh-status`、`umf.system-resources`、`umf.operation-log`、`umf.mml-file`、`umf.mml-archive`、`umf.kpi`、`umf.mesh-metrics`、`umf.other` 路线（FR-012 至 FR-019、FR-033、FR-037）
- [ ] T029 [US1] 在 `app/services/extraction/layout.py` 与 `app/services/extraction/classification.py` 实现多来源映射同一目标根、目标根 allowlist、同名目标稳定摘要消歧和不可消歧 `target_conflict`，禁止静默覆盖（FR-011、FR-036）
- [ ] T030 [US1] 扩展 `tests/test_real_package.py`，断言合成 UMF 包的 basic/debug/status/operation-log/mml/kpi/other 物理路径、业务分类、73 个 KPI 成员、14 个 MESH CSV、未命中 ZIP 原样保留及 CSP 非告警不落位（FR-005、FR-010、FR-012 至 FR-019、SC-003）
- [ ] T031 [US1] 在 `tests/test_kpi_measurement_matching.py` 回归 KPI 规则只消费 `kpi/` catalog 路径且 `rule_version=3.3.0` 不变，禁止为了新分类改写 KPI 判定逻辑（FR-018、FR-049）
- [ ] T032 [US1] 更新 `docs/example/real-package-structure.md`，记录 UMF 真实目录后缀、`capture_root`、目标路径和未命中归档规则，确保目录调整不再依赖源码硬编码（FR-006、FR-007、FR-037）

**检查点**：仅使用 US1 + 基础层，即可独立验证 UMF basic/debug/status/operation/mml/kpi/MESH/other 分类。

---

## 阶段 4：用户故事 2 - UMF 和 CSP 告警统一展开并集中保存（优先级：P1）

**目标**：任意前缀下完整目录段 `Alarm Information/` 或 `Alarm Data/` 都进入同一个 `alarm/`；告警优先于 `0/` ignore；ZIP/TAR/TAR.GZ/GZIP 递归展开；空文件、仅表头、零记录和有记录告警都保留。

**独立测试**：分别构造 UMF 告警、CSP `0/Problems/Alarm Data`、缺少 `Problems` 的 CSP 告警、嵌套 ZIP/TAR/GZIP、单文件 GZIP、0 字节、仅表头、零记录和损坏成员；所有合法告警进入同一个 `alarm/`，非告警 `0/` 和 CSP 非告警内容不进入 catalog。

- [ ] T033 [P] [US2] 新建 `tests/test_classification_alarm.py`，先写 `Alarm Information/`、`Alarm Data/` 任意前缀匹配、`Problems` 缺失、目录大小写变化和 `alarm > ignore` 阶段优先级测试（FR-004、FR-023、FR-024、FR-026、SC-007）
- [ ] T034 [US2] 在 `tests/test_classification_alarm.py` 增加告警普通文件、ZIP、TAR、TAR.GZ、单文件 GZIP、嵌套归档、0 字节、仅表头、零记录、含记录和损坏成员测试（FR-025、FR-027、FR-028、SC-008、SC-011）
- [ ] T035 [US2] 在 `tests/fixtures/make_real_package.py` 追加固定时间戳的 UMF 告警、CSP `0/Problems/Alarm Data`、缺少 Problems 的 CSP 告警、非告警 `0/`、非告警 CSP 和损坏告警归档样例（FR-023 至 FR-028、SC-002、SC-007、SC-008）
- [ ] T036 [US2] 更新 `deploy/config/classify_rules.yaml`，增加 `alarm.umf`、`alarm.csp`、`0/` ignore 和 CSP catch-all ignore；告警路线 profiles 为 `[UMF, CSP]`，两种网元告警均落位 `alarm/{member}`，CSP 非告警不得落位（FR-004、FR-005、FR-023 至 FR-026）
- [ ] T037 [US2] 在 `app/services/extraction/nested.py` 与 `app/services/extraction/classification.py` 实现告警 `expand_recursive`，去掉告警来源目录和归档外层，组合嵌套成员路径，并对不支持或损坏归档写 FailureRecord（FR-025、FR-028、FR-034、FR-035）
- [ ] T038 [US2] 在 `app/services/extraction/classification.py` 实现局部失败策略：单归档/GZIP 失败产生 `WARN` 和 FailureRecord，其他合法告警继续落位；配置、主包、catalog 或发布失败仍为 `ERROR`（FR-028、FR-035、FR-053、SC-011）
- [ ] T039 [US2] 扩展 `tests/test_real_package.py`，断言合成包中 UMF 与 CSP 告警共 2 个文件进入同一 `alarm/`、记录数可读取，`0/` 非告警和 CSP 非告警进入 catalog 的数量为 0（FR-005、SC-001、SC-002、SC-007、SC-008）
- [ ] T040 [US2] 在 `tests/test_executor.py` 验证 classification `WARN` 时 prepare/inspect 继续，损坏子归档不中断任务；classification `ERROR` 时不执行任何普通规则（FR-053、SC-011）

**检查点**：仅使用 US2 + 基础层，即可独立验证跨网元告警统一落位、优先级和局部失败隔离。

---

## 阶段 5：用户故事 3 - Service Logs 只保留业务主日志并解压（优先级：P1）

**目标**：Service Logs 只保留 98 个业务主日志并把 85 个 `.log.gz` 解压为 `.log`；CHR 只保留 3 个 `.bil.gz` 并解压为 `.bil`；主机日志成员 GZIP 同步解压；所有排除项写 ignored。

**独立测试**：构造 Service Logs 与 CHR 归档，包含全部 include、全部 exclude、未选成员和主机 `.log.gz`；验证最终日志数、CHR 数、解压后缀、目标路径和 ignored 原因，任何排除项不得进入 catalog。

- [ ] T041 [P] [US3] 新建 `tests/test_classification_logs.py`，先写 Service Logs 六类 include、全部 exclude、exclude 优先于 include、未选成员 `member_not_selected`、98 个业务主日志和 85 个 `.log.gz` 解压测试（FR-029、FR-030、FR-031、FR-032、SC-004）
- [ ] T042 [US3] 在 `tests/test_classification_logs.py` 增加 CHR `**/*.bil.gz` 选择、3 个 `.bil` 落位、`LocalLogReport.csv` 忽略、其他成员未选，以及 Host Debugging/System `DEBUG.tar.gz`/`OS.tar.gz` 的成员 `.log.gz` 解压测试（FR-020、FR-021、SC-005）
- [ ] T043 [US3] 在 `tests/fixtures/make_real_package.py` 追加固定时间戳、幂等的 98 个业务主日志、85 个 `.log.gz`、全部排除项、3 个 CHR `.bil.gz`、`LocalLogReport.csv`、DEBUG.tar.gz 和 OS.tar.gz 样例（FR-020 至 FR-022、FR-029 至 FR-032）
- [ ] T044 [US3] 更新 `deploy/config/classify_rules.yaml`，增加 `umf.chr`、`umf.service-logs`、`umf.host-debug`、`umf.host-system` 及 selection include/exclude、service、`name_without_gz` 和 `member_decompress` 配置（FR-020、FR-021、FR-029 至 FR-031）
- [ ] T045 [US3] 在 `app/services/extraction/nested.py` 实现 `select_and_decompress`、exclude 优先、include/service 唯一匹配、选中 GZIP 去一层 `.gz` 和归档成员 GZIP 解压；在 `app/services/extraction/classification.py` 将未选成员写入 ignored（FR-020、FR-029 至 FR-032）
- [ ] T046 [US3] 在 `app/services/extraction/audit.py` 为 Service Logs/CHR 排除原因建立稳定 reason（至少 `member_not_selected`、`report_not_log`、RScheck/dblog/UFP/monitor/start/proxy/bbox 原因），确保审计可区分规则未命中与成员未选（FR-031、FR-044、FR-045）
- [ ] T047 [US3] 扩展 `tests/test_real_package.py`，断言合成包 catalog 中 Service Logs 恰好 98 个、85 个 `.log.gz` 全部变为 `.log`、CHR 恰好 3 个 `.bil`，所有排除项在 ignored 且不在 catalog（SC-004、SC-005）
- [ ] T048 [US3] 在 `tests/test_kpi_only_rule_library.py` 回归本轮只保留 KPI 普通规则；不得因新增 logs/chr/status/operation 分类恢复已下线业务规则（FR-049、范围外）

**检查点**：仅使用 US3 + 基础层，即可独立验证 Service Logs、CHR 和主机日志的按需选择与解压。

---

## 阶段 6：用户故事 4 - 分类配置变化后从证据现场稳定重建（优先级：P2）

**目标**：语义配置不变时复用；有效配置、product、kind、extraction policy、target roots、budgets 或 path limit 变化时，只从 `.main/` 重建分类现场；证据损坏时复核原始包 checksum 后重建；发布必须 staging + manifest 原子切换。

**独立测试**：连续分类两次复用；只改注释/空白/顺序仍复用；改 route/target/product/path limit 触发重建；删除/损坏 manifest 或 `.main` 触发正确重建；失败发布回滚；旧分类根残留不进入 catalog；原包 checksum 前后不变。

- [ ] T049 [P] [US4] 在 `tests/test_classification_config.py` 增加 canonical fingerprint 测试，覆盖注释、空白、映射键顺序、route 顺序不变，anchor/pattern/profiles/priority/action/category/target/selection/member_decompress/id 变化，以及 64 位小写十六进制格式（FR-039、SC-009）
- [ ] T050 [P] [US4] 在 `tests/test_extraction_site.py` 增加证据指纹、`.main/` 链接/内容变化、原包 checksum 冲突和证据损坏重建测试，断言重建前后原始包哈希一致（FR-041、FR-042、SC-006）
- [ ] T051 [P] [US4] 在 `tests/test_extraction_package.py` 增加 staging 构建、manifest 隐藏、target roots 交换、`os.replace()` 发布、逆序回滚、legacy roots 清理、`.main/prepared/rules/reports` 不被触碰和重复执行无重复目标/分类的幂等测试（FR-043、FR-046、FR-054、SC-009）
- [ ] T052 [US4] 在 `app/services/extraction/config.py` 实现规范化有效配置 SHA-256，填充默认值、排序集合/route/selection、UTF-8 canonical JSON，并输出 classification snapshot 所需 config fingerprint（FR-039、FR-040）
- [ ] T053 [US4] 在 `app/services/extraction/site.py` 与 `app/services/extraction/manifest.py` 实现 `.main/` 证据指纹、checksum 复核和复用矩阵；只有 v5 且 checksum/evidence/product/kind/snapshot/path_limit/catalog 全部一致才复用（FR-040、FR-041、FR-042）
- [ ] T054 [US4] 在 `app/services/extraction/classification.py` 与 `app/services/extraction/manifest.py` 实现 `.classification.staging/`、catalog 摘要预校验、旧 manifest 隐藏、分类根交换、原子发布、回滚、成功后的 legacy allowlist 清理和重复执行幂等发布（FR-043、FR-046、FR-054、SC-009）
- [ ] T055 [US4] 在 `tests/test_extraction_package.py` 增加配置有效变化、product/kind 变化、path limit 变化、旧 v1-v4 manifest、manifest 损坏、`.main` 缺失和同输入重复执行的复用/重建矩阵测试（FR-039 至 FR-043、FR-054、SC-009）
- [ ] T056 [P] [US4] 在 `tests/test_api_robustness.py`、`tests/test_task_restore.py` 和 `tests/test_tasks_scene_missing.py` 先写 API 条件必填、`metadata_not_applicable`、checksum → kind → product 冲突顺序、同 checksum 同 kind 同 product 幂等恢复和现场清理后恢复不自动重跑测试（FR-001、FR-002、FR-050、FR-051）
- [ ] T057 [US4] 更新 `app/api/router.py`，按 T056 契约实现 product trim+upper、巡检包必填、日志补充包禁字段、三类稳定冲突错误码和既有任务恢复矩阵（FR-001、FR-002、FR-050、FR-051）
- [ ] T058 [P] [US4] 在 `tests/test_task_run_fields.py`、`tests/test_local_run.py`、`tests/test_cli_explain_match.py`、`tests/test_inventory_parser.py` 和 `tests/test_online_identity.py` 先写 product/package kind 从 API/CLI 到 RuleContext/UnitRequest/worker、台账过滤和本地/在线同构的失败测试（FR-003、FR-050、FR-051、SC-013）
- [ ] T059 [US4] 更新 `app/services/tasks.py`、`app/cli.py`、`app/services/unit_runtime.py`、`app/services/executor.py` 和 `app/services/inventory/parser.py`，传播持久化 product/package kind，台账使用同一规范化 product 比较，`log_supplement` 返回 `not_applicable`，不得从路径或台账反推（FR-001 至 FR-004、FR-050、FR-051）
- [ ] T060 [P] [US4] 更新 `web/src/pages/TaskListPage.test.tsx`，先写巡检包 product 必填、提交前 trim+upper、日志补充包隐藏并清空省份/运营商/product、稳定冲突错误可见的失败测试（FR-001、FR-002、FR-050）
- [ ] T061 [US4] 执行 `.venv/bin/python build.py gen-web-api` 更新 `web/src/api/client.ts`，再更新 `web/src/pages/TaskListPage.tsx` 实现条件显示、必填校验、空白/大小写规范化和错误码展示，禁止手写不合契约的请求字段（FR-001、FR-002、FR-050）
- [ ] T062 [US4] 新建 `web/e2e/archive-classification-upload.spec.ts`，覆盖巡检包上传 product 必填、`umf` 规范化为 `UMF`、日志补充包字段隐藏且不提交、缺 product/冲突错误的完整入口到结果展示（FR-001、FR-002、FR-050、SC-013）
- [ ] T063 [US4] 在 `tests/test_online_identity.py` 与 `tests/test_cli_explain_match.py` 完成 API/CLI 同 task_id、profile、catalog、ignored/failures 摘要和台账过滤一致性断言，并修正实现直到 SC-013 通过（FR-051、SC-013）

**检查点**：仅使用 US4 + 基础层，即可独立验证指纹复用、证据重建、原子发布、product/kind 传播和双模式一致性。

---

## 阶段 7：用户故事 5 - 分类过程可审计且巡检清单只含成功落位文件（优先级：P2）

**目标**：每个命中、未命中、忽略、冲突和失败均可解释；规则只看到 manifest v5 `catalog[]` 的成功落位文件；无匹配返回带 profile/配置指纹/ignored/failures 的 `skip_reason`。

**独立测试**：构造命中、ignore、fallback、冲突、局部失败和损坏 catalog；验证 manifest 审计逐项存在、summary 计数一致、catalog 仅含有效成功文件、目录扫描不回退，规则无匹配返回非空 skip 理由，`explain-match` 返回 v5 快照和摘要。

- [ ] T064 [P] [US5] 在 `tests/test_classification_runtime.py` 增加命中、未命中 fallback、ignore、resolved conflict、failure、按 route/category/action/status 汇总和逐项 reason 测试，断言 summary 与数组长度一致（FR-044、FR-045、SC-010）
- [ ] T065 [US5] 在 `app/services/extraction/audit.py` 与 `app/services/extraction/classification.py` 完成审计聚合和结构化分类日志，输出按 route/category/action/status 计数，并逐项列出未命中、忽略、冲突和失败（FR-044、FR-045、SC-010）
- [ ] T066 [P] [US5] 在 `tests/test_scanning_catalog.py` 重写 catalog 测试，要求只读取 v5 `manifest.json` 的 `catalog[]`，校验路径、普通文件、symlink、size/SHA-256、summary 和顺序，禁止回退扫描 `logs/kpi/alarm/...`（FR-046、FR-047）
- [ ] T067 [US5] 重写 `app/services/scanning/catalog.py`，只从有效 manifest v5 catalog 构建 `TaskFileCatalog`，拒绝缺失、越界、链接、摘要不符和 summary 不一致，不扫描固定分类目录（FR-046、FR-047）
- [ ] T068 [P] [US5] 在 `tests/test_executor.py` 和 `tests/test_rule_state_executor.py` 先写普通规则无 catalog 匹配时返回 `skip` 且 skip_reason 包含 patterns/profile/config/ignored/failures 的测试（FR-048）
- [ ] T069 [US5] 更新 `app/services/executor.py`，让普通规则只匹配 catalog 路径，无匹配返回 `skip` 和非空 `skip_reason`，不得把 `.main/`、prepared、rules、reports、task.json、execution.log 暴露给规则（FR-046 至 FR-048）
- [ ] T070 [US5] 在 `tests/test_cli_explain_match.py` 增加 explain-match v5 测试，断言返回 classification snapshot、config fingerprint、catalog 匹配、ignored/failures 摘要且不读取旧分类目录（FR-044、FR-045、FR-051）
- [ ] T071 [US5] 更新 `app/cli.py` 的 `explain-match`，输出 v5 snapshot、route/category/action/status 汇总、catalog 匹配和 ignored/failures 明细，不使用旧 manifest 或目录扫描（FR-044 至 FR-046、FR-051）
- [ ] T072 [P] [US5] 在 `web/src/utils/preparationDisplay.test.ts` 与 `web/src/pages/TaskDetailPage.test.tsx` 增加准备页只展示 `pkg.extract.main` 和 `pkg.extract.classification`、WARN/ERROR 可解释状态测试（FR-045、FR-053）
- [ ] T073 [US5] 更新 `web/src/utils/preparationDisplay.ts` 与 `web/src/pages/TaskDetailPage.tsx`，只展示两个隐藏解压单元，显示 classification 摘要、ignored/failures 计数和稳定错误码，不展示旧七分类单元（FR-045、FR-053）

**检查点**：仅使用 US5 + 基础层，即可独立验证审计、catalog 唯一入口、无匹配 skip 和准备页可解释性。

---

## 阶段 8：收尾与横切关注点

**目的**：移除旧分类链路、补齐文档和真实包验收，执行完整质量门禁。

- [ ] T074 [P] 更新 `docs/architecture.md`、`docs/data-model.md` 和 `docs/design/mechanisms.md`，记录 manifest v5、两个隐藏解压单元、按需展开、审计、重建矩阵和 catalog 唯一入口（FR-037 至 FR-048）
- [ ] T075 [P] 更新 `docs/example/real-package-structure.md` 与 `specs/038-on-demand-archive-classification/quickstart.md` 的最终命令和 fixture 计数，确保文档与实现、真实包基准一致（FR-006、FR-032、SC-001 至 SC-005）
- [ ] T076 停止生产链路对 `app/core/classify.py`、`app/services/extraction/policy.py` 和 `deploy/config/extract_policy.yaml` 的调用；删除或改写 `tests/test_classify.py`、`tests/test_extract_policy.py`、`tests/test_extraction_policy.py` 为迁移保护测试，确保成员内容嗅探和通用扩展名 fallback 不再进入 v5（FR-006、FR-033、范围外）
- [ ] T077 检查 `tests/test_kpi_only_rule_library.py` 和注册表，确认除隐藏解压单元外只保留既有 KPI 普通规则，不恢复日志、告警、配置、状态、资源或 CHR 业务规则（FR-049、范围外）
- [ ] T078 扩展 `tests/test_real_package.py` 和 `tests/fixtures/make_real_package.py` 的展示效果断言，覆盖真实目录正常路径、告警边界、Service Logs/CHR 选择、KPI/MESH、未知归档、损坏归档、0 字节/仅表头/零记录和路径安全边界，并保持固定时间戳与既有样例只增不减（SC-001 至 SC-013）
- [ ] T079 执行 `.venv/bin/python build.py contract` 与 `.venv/bin/python build.py gen-web-api`，修复 `docs/api/openapi.yaml`、Pydantic schema、生成客户端和测试之间的全部契约漂移（FR-001、FR-002、FR-050、FR-051）
- [ ] T080 执行 `.venv/bin/python build.py lint` 与 `.venv/bin/python build.py test`，修复全部静态检查、单元、契约和集成测试问题（宪法质量门禁）
- [ ] T081 执行 `.venv/bin/python build.py verify`，确认 CLI 与 API 全流程、两个隐藏解压单元、分类重建和 KPI 规则执行通过（宪法质量门禁）
- [ ] T082 执行 `.venv/bin/python build.py web-build` 与 `.venv/bin/python build.py e2e`，验证上传、准备摘要和分类结果在界面中真实可见（宪法展示效果门禁）
- [ ] T083 按 `specs/038-on-demand-archive-classification/quickstart.md` 对只读真实包 `DataCollect/ALL_20261031173253.zip` 使用隔离临时 HOME/输出运行；运行前后均校验 SHA-256 `df3d09eb065a407193b0178200f195cebf571e7ff1d8ef6266d98e5ccf459687`，核对 2 个告警、73 个 KPI 成员、14 个 MESH CSV、98 个业务日志和 3 个 CHR `.bil`，不得复制、移动、删除、重命名或提交真实包及派生数据（SC-001 至 SC-006）
- [ ] T084 执行 `git status --short`、`git diff --check` 并人工检查暂存候选，确认 `DataCollect/`、`uploads/`、`output/`、数据库、日志、临时验收目录和真实解压内容均未进入 Git（宪法真实数据隔离）

---

## 依赖与执行顺序

### 阶段依赖

- **阶段 1**：无前置，先完成；`docs/api/openapi.yaml` 必须先于 API 实现修改（T001）。
- **阶段 2**：依赖阶段 1；T006-T022 完成前不得开始 US1-US5 的实现任务。
- **阶段 3（US1）**：依赖阶段 2；实现按 T026 → T027 → T028 → T029 顺序推进，测试任务可并行先行。
- **阶段 4（US2）**：依赖阶段 2；实现依赖 T026 的阶段选择和 T027 的动作框架，可与 US1 集成但必须可独立测试。
- **阶段 5（US3）**：依赖阶段 2；实现依赖 T027 的归档动作框架，可与 US1/US2 集成但必须可独立测试。
- **阶段 6（US4）**：依赖阶段 2；原子发布依赖 T016 manifest v5，product/API 传播依赖 T006-T008。
- **阶段 7（US5）**：依赖阶段 2 与至少一个可产生 v5 现场的 US 故事；catalog 消费不得回退目录扫描。
- **阶段 8**：依赖所有目标用户故事完成；真实包验收必须在合成包和全部自动化门禁通过后执行。

### 用户故事完成顺序

1. US1 先交付 UMF 精细目录 MVP，验证目录路线、目标路径和 KPI/MESH 输入稳定。
2. US2 交付跨网元告警统一落位，验证 `alarm > ignore` 与递归安全展开。
3. US3 交付 Service Logs/CHR 业务日志选择，冻结 98/85/3 基准。
4. US4 交付指纹复用、证据重建、原子发布和 product/kind 双模式传播。
5. US5 交付审计、catalog 唯一消费、无匹配 skip 和准备页解释。
6. 最后执行真实包只读验收与完整门禁。

### 并行机会

- 阶段 1 的 T002-T005 可并行编写，分别修改不同测试文件。
- 阶段 2 的 T009/T011、T013/T015、T017/T019 可先并行写测试；实现按依赖顺序推进。
- US1 的 T023/T025、US2 的 T033、US3 的 T041 可并行编写不同测试文件；同一测试文件后续任务以及所有 `tests/fixtures/make_real_package.py` 修改必须串行执行，避免并行覆盖。
- US4 的 T049-T051 与 T056、T058、T060 可并行编写不同测试文件。
- US5 的 T064、T066、T068、T070、T072 可并行编写不同测试文件。
- 收尾文档 T074/T075 可并行；T079-T082 必须串行执行质量门禁，T083 必须最后执行真实包只读验收。

## 并行示例

```text
# 基础测试并行
T009 tests/test_classification_config.py
T013 tests/test_classification_runtime.py
T015 tests/test_extraction_package.py
T017 tests/test_archive_robustness.py

# 用户故事测试并行
T023 tests/test_classification_umf.py
T033 tests/test_classification_alarm.py
T041 tests/test_classification_logs.py

# US4 契约与前端测试并行
T056 tests/test_api_robustness.py
T058 tests/test_local_run.py
T060 web/src/pages/TaskListPage.test.tsx
```

## 实现策略

### MVP 优先

1. 完成阶段 1 和阶段 2。
2. 完成 US1 的测试、分类引擎、UMF 路线和 fixture。
3. 停止并运行 US1 独立测试与 KPI/MESH 回归。
4. 确认 UMF 目录精细落位后可演示；随后并行推进 US2 和 US3。

### 增量交付

1. 基础契约与 v5 骨架 → 单元测试。
2. US1 → UMF 目录分类演示。
3. US2 → 跨网元告警演示。
4. US3 → Service Logs/CHR 演示。
5. US4 → 配置重建、API/CLI/前端上传闭环。
6. US5 → 审计、catalog、explain-match 和准备页闭环。
7. 收尾门禁 → 合成包验收 → 真实包只读验收。

### 真实数据边界

- 所有自动化测试只使用 `tests/fixtures/` 中的合成、脱敏或可重复生成数据。
- 真实包验收只读打开 `DataCollect/ALL_20261031173253.zip`，输出进入隔离临时目录；不得执行任何复制、移动、删除、重命名、重新压缩或 Git 暂存操作。
- 不得使用 `git add -A` 或宽泛通配符暂存；提交时只按功能主题显式列出文件。
