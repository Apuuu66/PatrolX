# 实现计划：按真实目录进行按需归档分类

**分支**：`feature/038-on-demand-archive-classification`（实现目标名；规划在 `main` 完成，实现阶段创建独立 worktree） | **日期**：2026-11-02 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/038-on-demand-archive-classification/spec.md` 的功能规格

## 摘要

将现有“按文件名/扩展名猜测 + 七个分类隐藏单元”的解压分类链路，替换为一个配置驱动、可审计、可从只读证据现场重建的 v5 分类现场：

1. **真实目录优先**：路线只使用业务目录后缀和文件名模式匹配，不依赖外层设备、问题编号或固定绝对深度；同一目录段重复出现时以最右侧为 `capture_root`。目标路径只保留业务目录之后的相对路径，去掉外层包装和中间归档层。
2. **按需展开**：只有配置明确声明的 KPI、MML、MESH、CHR、主机日志、Service Logs 和告警归档才展开；未声明归档原样进入 `other/`，CSP 非告警内容不进入工作分类现场。
3. **UMF/CSP 分离**：上传网元类型规范化后作为唯一 profile 依据；UMF 使用精细路线，CSP 本阶段只处理两类告警，日志补充包使用 `GENERIC` profile。
4. **清单驱动巡检**：manifest 升级为 v5，记录配置指纹、证据指纹、分类审计和成功落位 catalog；普通规则只消费 catalog，不再扫描固定分类目录。
5. **安全重建**：分类配置、网元类型、解压策略或路径限制变化时，从 `.main/` 证据现场重建；只有 staging 完成并通过校验后才原子发布新 manifest。
6. **双模式一致**：API、CLI、`RuleContext`、`UnitRequest` 和 worker 传递同一个 product/package kind；错误码、恢复矩阵和 UI 表单同步更新。

本功能不改变既有 KPI 规则的判定逻辑或 `rule_version`，只保证 `PerfResult_*.zip` 成员稳定落到 `kpi/`。

## 技术上下文

**语言/版本**：Python 3.11+（仓库虚拟环境为 3.12.x）；前端 TypeScript 5.x。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy 2.x、SQLite、structlog、PyYAML；React 18、Vite、Ant Design 5、Playwright。不新增运行时依赖。

**存储**：
- `uploads/<task_id>/`：原始上传包只读现场，不修改、移动、删除或重命名。
- `output/<task_id>/.main/`：主包安全展开的证据现场，可按原始包幂等重建。
- `output/<task_id>/manifest.json`：manifest v5；分类现场唯一发布凭据。
- `output/<task_id>/<target-root>/...`：由配置声明的 UMF/CSP/GENERIC 工作分类目录。
- SQLite：继续使用 `TaskRecord.customer` JSON 保存 product，`package_kind` 使用既有列；不新增表或列。
- `manifest.json`、分类审计和 catalog 是文件现场事实；数据库不保存分类明细。

**测试**：pytest 单元/集成测试、OpenAPI-Pydantic 契约校验、前端 Vitest/Testing Library、Playwright E2E，以及真实包只读验收脚本或测试入口。

**目标平台**：离线部署的 Linux/macOS；本地 CLI 与在线 API/Web 共用分类引擎。

**性能目标**：
- 分类遍历以 `.main/` 文件清单为基线，避免对每个未知归档做内容嗅探。
- 同一任务、同一配置重复执行必须复用有效 v5 现场，不重复展开主包。
- 预算固定为归档深度 8、成员路径深度 12、单归档 100,000 文件、任务累计 200,000 文件、单文件 2 GiB、累计解压字节 3 GiB。

**约束条件**：
- 完全离线，不引入在线采集或连接被检系统能力。
- 真实包及其解压内容、日志、数据库和报告不得进入 Git；验收前后必须复核 SHA-256。
- 兼容 Python 3.11+，保持 `python build.py` 为唯一构建入口。
- 分类配置为部署侧只读静态配置，不支持在线编辑、热加载或任务级覆盖。
- 分类只决定安全落位与规则可见 catalog，不恢复已下线业务规则，不扩展公共 `RuleCategory`。

**规模/范围**：覆盖 API `/api/v3/tasks`、CLI `run`/`run-one`/`explain-match`、隐藏解压单元、manifest v5、TaskFileCatalog、准备页摘要、前端上传表单和真实包验收；不新增在线配置页面或 CSP 非告警精细分类。

## 宪法检查

*门禁：必须在阶段 0 研究前通过；阶段 1 设计后重新检查。*

| 宪法原则 | 计划合规性 | 证据/约束 |
| --- | --- | --- |
| 离线优先 | PASS | 只读取上传包和本地配置，不引入网络调用或被检系统访问 |
| 一个包、一个任务 | PASS | task_id 仍只由包名派生；分类目标全部位于同一 `output/<task_id>/` |
| 真实数据隔离 | PASS | 真实验收使用隔离临时目录；原始包只读；不暂存、不提交 `DataCollect/` 或派生数据 |
| 契约驱动 | PASS | 先更新 `docs/api/openapi.yaml`，再同步 schema、生成客户端和测试；manifest v5 契约先冻结 |
| 模式同构 | PASS | 分类服务、RuleContext、UnitRequest 和台账解析共享规范化 product；CLI/API 使用同一引擎 |
| 巡检器插件架构 | PASS | 只保留 `pkg.extract.main` 与 `pkg.extract.classification` 两个隐藏 P0 单元；普通规则不互相调用 |
| 源文件显式匹配 | PASS | 普通规则仍只按自己的 `source_patterns` 匹配 catalog；分类审计不成为规则输入 |
| 增量重跑 | PASS | `verify-one` 与单规则重跑先确保 v5 分类现场，再只写目标规则产物 |
| 解压先行 | PASS | EXTRACT 阶段和阶段屏障保留；main/classification 任一 ERROR 阻断 prepare/inspect |
| 规则私有预处理 | PASS | 不改变 prepare owner、缓存和路径隔离 |
| 幂等与可追溯 | PASS | 配置语义指纹、证据指纹、staging + manifest 发布、逐项 audit 和稳定冲突消歧 |
| 轻量默认 | PASS | 不新增依赖；未知归档不嗅探、不展开 |
| 数据分页默认 | PASS | 不新增列表接口；任务和台账分页语义不变 |
| 容错 | PASS | 单个子归档/GZIP 失败为 WARN + FailureRecord，不中断其他文件 |
| 输入文本编码兼容 | PASS | 分类路径按 UTF-8/POSIX 规范化；业务内容编码解析保持既有能力 |
| 安全解压 | PASS | 拒绝路径穿越、绝对路径、链接、重复成员、越界目标、超限深度/大小/数量 |
| 时间、命名与日志 | PASS | 继续使用 UTC 和 `*_at`；分类日志携带 task_id、route、status、error_code |
| 新功能验证与展示效果 | PASS | 扩充合成包生成器、API/CLI/Web 自动化测试，并提供真实包只读验收步骤 |

**阶段 0 复核**：研究问题已在 [research.md](./research.md) 收敛，无 `NEEDS CLARIFICATION`。不需要宪法修正或例外。

**阶段 1 复核**：v5 数据模型、分类配置契约、manifest 契约和任务 product API 契约均符合上述门禁；唯一复杂度来自分类链路整体替换，属于需求范围，不需要更简单的兼容分支。

## 阶段 0：研究结论

详细决策见 [research.md](./research.md)，实现时以以下结论为准：

1. 分类配置升级为版本化 YAML，顶层严格为 `{version, profiles, routes}`。
2. 路线来源使用受控目录 glob 和文件名 glob，不接受自由正则；外层前缀不参与业务分类判断。
3. 场景根由 profile anchors 推导，优先去掉设备名、问题编号和包装目录。
4. 匹配阶段固定为 `alarm > precise > ignore > fallback`，阶段内按 priority 降序。
5. 动作仅为 `copy`、`expand`、`decompress`、`expand_recursive`、`select_and_decompress`、`ignore`、`fallback`。
6. 目标模板只允许有限变量：`{suffix}`、`{member}`、`{archive_stem}`、`{service}`、`{node_path}`、`{name_without_gz}`。
7. manifest 升级为 v5，采用 staging 构建、摘要复核、manifest 发布屏障和目标根交换/回滚。
8. 复用分类现场前必须同时校验主包 checksum、证据指纹、product/kind、profile、配置指纹、解压策略和路径限制。
9. 固定错误码和资源预算，子归档局部失败不阻断任务。
10. 旧文件名/扩展名分类、内容嗅探和 `extract_policy.yaml` skip/whitelist 不参与生产分类。
11. KPI 规则输入路径保持 `kpi/`，MESH 指标只进入 `other/MESH Application Metrics/<archive_stem>/`。
12. product 在 API/CLI 入口 `trim().upper()`，只接受 `UMF`/`CSP`，巡检包必填、日志补充包禁止。

## 阶段 1：设计产物

- [data-model.md](./data-model.md)：`Product`、`PackageKind`、`ClassificationConfig`、`ClassificationSnapshot`、`EvidenceSnapshot`、`ClassificationAudit`、`ManifestV5`、`CatalogEntry` 及状态迁移。
- [contracts/classification-config.md](./contracts/classification-config.md)：分类配置 v1 的严格 schema、匹配阶段、UMF/CSP/GENERIC 路线、目标模板、重叠校验和指纹算法。
- [contracts/manifest-v5.md](./contracts/manifest-v5.md)：manifest v5 JSON 结构、catalog、复用矩阵、原子发布、错误码和旧版本迁移。
- [contracts/task-product-api.md](./contracts/task-product-api.md)：product/package kind 条件必填、错误码、同名恢复矩阵、上下文传播、CLI 和 Web 行为。
- [quickstart.md](./quickstart.md)：合成包、API、CLI、重建、失败边界和真实包只读验收步骤。

### 关键实现决策

1. **路径后缀匹配**：`source.directory` 按目录段匹配，`**/` 只吸收外层无关前缀；`source.capture_root` 指定目标路径起点。`Alarm Data/`、`Performance Measurement Results/`、`Service Logs (Problem)/` 等业务目录之前的内容既不参与分类，也不进入目标路径。这样 `Problems` 缺失、设备目录变化或包装层变化不会改变分类结果。
2. **场景根与 fallback**：UMF anchor 只由 UMF profile 参与场景根推导；未命中精细路线的普通文件进入 `other/<scene-relative-suffix>`，不把外层设备、问题编号或包装目录带入目标。
3. **告警优先**：UMF 的 `Alarm Information/` 和 CSP 的 `Alarm Data/` 使用 `alarm` 阶段、`expand_recursive`，优先于任何 `0/` ignore；告警下所有普通文件、0 字节、仅表头、零记录和归档成员都落位，分类阶段不做内容有效性判断。
4. **业务日志按成员选择**：Service Logs 与 CHR 使用 `select_and_decompress`；exclude 先于 include，未选成员写 `IgnoredRecord`，选中 `.gz` 解压并去掉一个 `.gz` 后缀。真实包基准分别为 98 个业务日志和 3 个 `.bil`。
5. **原子发布**：在 `.classification.staging/` 构建目标根和审计，校验 catalog 摘要后隐藏旧 manifest、交换目标根、用 `os.replace()` 发布 manifest；失败逆序回滚。发布只替换分类根，不碰 `.main/`、规则、prepared、报告和任务元数据。
6. **catalog 唯一入口**：`TaskFileCatalog.build()` 只读有效 manifest v5 的 `catalog[]`，校验路径类型、摘要和 summary 一致性；不存在则报错，不回退扫描旧分类目录。普通规则无匹配返回 `skip` 并带 profile、配置指纹、ignored/failures 计数。
7. **产物隔离**：旧 v1–v4 manifest 一律不可复用；旧七个分类根只在 v5 成功发布后按已知 allowlist 清理，避免历史文件残留污染规则匹配。
8. **product 传播**：API/CLI 标准化后写入 `TaskRecord.customer["product"]`，经 `TaskService._task_info()`、`run_task(product=...)`、`RuleContext.product/package_kind`、`UnitRequest` 传到分类器；worker 不得从路径或包名推断。

### 接口与契约变更

- `docs/api/openapi.yaml`：补充 `product` 条件必填语义、`missing_product`/`invalid_product`/`package_kind_conflict`/`package_product_conflict` 响应，以及日志补充包元数据限制。
- `app/models/schemas.py`：新增或收敛 `Product`/`PackageKind` 规范化；任务摘要仍使用既有 `customer_product` 字段。
- `app/api/router.py`：巡检包要求 product，日志补充包拒绝 product/province/operator；同名任务按 checksum → kind → product 固定顺序处理冲突。
- `web/src/api/client.ts`：由 OpenAPI 重新生成，不手写字段或错误分支。
- `web/src/pages/TaskListPage.tsx`：巡检包显示网元类型必填，提交前 trim + uppercase；日志补充包隐藏并清空局点元数据。
- `deploy/config/dicts.yaml`：product code 统一为 `UMF`、`CSP`，展示名不再依赖大小写转换。

## 项目结构

### 文档（本功能）

```text
specs/038-on-demand-archive-classification/
├── plan.md                  # 本文件
├── research.md              # 阶段 0 技术决策
├── data-model.md            # v5 领域模型与状态转换
├── contracts/
│   ├── classification-config.md
│   ├── manifest-v5.md
│   └── task-product-api.md
├── quickstart.md            # 可运行验收指南
├── checklists/
│   └── requirements.md
└── tasks.md                 # 阶段 2 输出（/speckit.tasks）
```

### 源代码（仓库根目录）

```text
app/
├── core/
│   ├── archive.py                       # 复用安全 ZIP/TAR/GZIP 原语；补充稳定错误码映射
│   ├── config.py                        # 配置路径与分类配置读取入口
│   └── dicts.py                         # product 字典规范化
├── inspectors/
│   └── pkg.py                           # 仅保留 main/classification 两个隐藏单元及门禁状态
├── models/
│   └── schemas.py                       # Product/PackageKind、任务上下文相关 schema
├── services/
│   ├── extraction/
│   │   ├── classification.py            # 新增：配置驱动分类编排、场景根、路线执行
│   │   ├── config.py                    # 新增：严格 YAML 解析、route 校验、语义指纹
│   │   ├── audit.py                     # 新增：Landed/Ignored/Conflict/Failure/Summary
│   │   ├── manifest.py                  # 升级：v5 校验、catalog、staging 发布
│   │   ├── layout.py                    # 收敛：工作根 allowlist、路径模板与安全目标
│   │   ├── nested.py                    # 收敛：按需递归、选择成员、GZIP 解压
│   │   └── policy.py                    # 退役：生产链路不再读取旧 skip/whitelist 策略
│   ├── scanning/
│   │   └── catalog.py                   # 只读 manifest v5 catalog，禁止目录扫描回退
│   ├── preparation.py                   # 准备摘要只显示两个隐藏解压单元
│   ├── executor.py                      # classification ERROR 阻断阶段；传递 product/kind
│   ├── unit_runtime.py                  # RuleContext/UnitRequest 增加 product 与 package_kind
│   ├── tasks.py                         # 任务恢复矩阵、product 传播、重建/单规则重跑
│   └── inventory/
│       └── parser.py                    # 用同一规范化 product 做台账网元类型过滤
├── api/
│   └── router.py                        # product 条件必填、冲突错误、日志补充包限制
└── cli.py                               # run/run-one/explain-match 的 product/kind 同构

deploy/config/
├── classify_rules.yaml                  # v1 profile + 真实目录路线配置
├── dicts.yaml                           # UMF/CSP 大写 code
└── extract_policy.yaml                  # 不再被 v5 生产链路消费

tests/
├── test_classification_config.py        # 新增：schema、阶段、重叠、指纹
├── test_classification_runtime.py       # 新增：后缀匹配、路由动作、审计、局部失败
├── test_extraction_package.py           # v5 复用/重建/发布
├── test_extraction_site.py              # 证据现场和安全边界
├── test_scanning_catalog.py             # manifest catalog 唯一入口
├── test_preparation.py                  # 两个隐藏单元展示
├── test_api_robustness.py               # product 条件必填与冲突矩阵
├── test_task_restore.py                 # 恢复顺序和日志补充包
├── test_local_run.py / test_cli_explain_match.py
├── test_real_package.py                 # 合成真实结构包的分类基准
└── fixtures/make_real_package.py        # 累积真实结构样例和边界

web/
├── src/pages/TaskListPage.tsx           # 网元类型必填、日志补充包字段隐藏
├── src/pages/TaskListPage.test.tsx
├── src/api/                             # 生成客户端
└── e2e/                                 # 上传到分类结果可见的 E2E

docs/
├── api/openapi.yaml
├── architecture.md
├── data-model.md
└── design/mechanisms.md
```

**结构决策**：分类配置解析、分类编排、审计和 manifest 发布分别落在 `extraction/config.py`、`classification.py`、`audit.py`、`manifest.py`，避免继续堆在单个 `nested.py`。`archive.py` 只保留安全解压原语，不承载业务分类；TaskFileCatalog 只做 manifest 读取和路径校验，不重新推断目录。

## 实现顺序与依赖

1. **契约先行**：更新分类配置、manifest v5 和 product API 契约；同步 OpenAPI、调度器错误码和前端生成客户端。
2. **数据模型与配置**：实现严格 YAML 加载、profile/route 校验、语义指纹和固定预算；先把真实目录路线写成可测试配置。
3. **证据与分类引擎**：拆分 main/classification 隐藏单元；实现 `.main/` 指纹、后缀匹配、场景根、按需展开、审计和 staging 发布。
4. **catalog 与执行器**：TaskFileCatalog 改读 v5 manifest；classification ERROR 阻断 prepare/inspect；单规则重跑复用同一分类现场。
5. **product 传播**：API、CLI、TaskService、RuleContext、UnitRequest、worker 和台账统一规范化值；实现同名恢复矩阵。
6. **前端与展示**：上传表单网元类型必填、日志补充包字段禁用；准备页只展示两个解压单元；补充 API/UI 错误提示。
7. **测试与样例**：扩展 `make_real_package.py`，覆盖 UMF/CSP 告警、Problems 缺失、0 目录、KPI/MESH、Service Logs、CHR、MML、主机日志、损坏归档、0 字节和路径安全边界。
8. **真实包只读验收**：使用 `ALL_20261031173253.zip` 在隔离临时输出中运行，核对 SHA-256、2 个告警、73 个 KPI、14 个 MESH CSV、98 个业务日志和 3 个 CHR `.bil`；不得把包或输出放入 Git。

## 测试与验证

### 自动化门禁

```text
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
.venv/bin/python build.py verify
```

涉及前端时追加：

```text
.venv/bin/python build.py web-build
.venv/bin/python build.py e2e
```

### 必须覆盖的行为

- 不同外层包装深度、目录名大小写变化、`Problems` 缺失时，路线仍只按业务目录后缀命中。
- UMF 的 basic/debug/status/operation/mml/kpi/mesh/chr/host logs/service logs 目标路径和业务分类。
- CSP 告警进入 `alarm/`，CSP 非告警不进入 catalog；UMF 告警不受 `0/` ignore 影响。
- 告警中的 ZIP/TAR/GZIP/单文件 GZIP、0 字节、仅表头和零记录文件不丢失。
- PerfResult 全部成员进 `kpi/`；CollectExport 全部成员进 `other/MESH Application Metrics/<archive_stem>/`。
- Service Logs 只保留 98 个业务主日志，85 个 `.log.gz` 解压；CHR 选择 3 个 `.bil.gz`。
- 未命中 UMF 文件按场景相对路径进入 `other/`；未知归档原样保留且不嗅探成员。
- 配置仅注释/空白变化时复用；有效规则、product、path limit 或策略变化时重建；旧 manifest 不可复用。
- 损坏子包只产生局部 `FailureRecord` 和 WARN，其他文件继续落位；主包失败或配置无效阻断执行。
- API/CLI 对同一包、product、kind 生成相同 task_id、profile、catalog 和错误码；日志补充包禁止元数据。
- 前端上传字段条件显示、错误码可见、任务详情准备页只显示两个解压单元。

### 真实数据验收边界

```text
# 只读检查，不复制、不移动、不修改真实包
shasum -a 256 DataCollect/ALL_20261031173253.zip
# 使用临时 HOME/数据目录运行分类
# 运行结束后再次执行同一命令，前后哈希必须一致
```

验收输出必须位于系统临时目录或项目已忽略的任务输出目录；不得使用 `git add` 的任何宽泛模式暂存 `DataCollect/`、`uploads/`、`output/` 或临时现场。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 真实目录进一步变化导致路线漏匹配 | 配置集中、后缀匹配、`explain-match` 和逐项 `IgnoredRecord` 可定位；未命中有审计而不静默丢弃 |
| 目录重叠导致误分类 | 固定阶段优先级 + 同阶段同优先级重叠静态校验；高优先级规则显式声明 |
| 多目标根发布中断 | staging + manifest 发布屏障 + 逆序回滚；无有效 manifest 时整体重建 |
| catalog 与物理文件不一致 | 发布前逐文件复核 size/SHA-256；运行时缺失或链路/摘要异常直接 ERROR |
| 历史 v4 现场残留污染 | v5 成功后按 allowlist 清理旧分类根；catalog 不扫描目录 |
| product 在 worker 中丢失 | 将 product/kind 纳入可序列化 `UnitRequest`，worker 只使用请求值 |
| 真实包无法进入 Git 或测试 | 只用合成/脱敏 fixture；真实包通过隔离验收命令只读验证 |

## 复杂度跟踪

| 违规项/额外复杂度 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 无宪法豁免 | 本功能未引入与宪法冲突的新架构或数据留存行为 | 不需要宪法修正；复杂点属于分类链路替换，已在设计阶段分解 |
| 分类配置解析/审计/manifest 分为多个模块 | 避免把配置校验、业务路由、审计与文件发布耦合在一个文件 | 全部塞进 `nested.py`：难以独立测试和定位配置错误，也无法保证发布原子性 |
| 新增 staging 与目标根交换 | 旧目录原地覆盖会留下残留文件并污染 catalog | 整个任务目录 rename：会误删规则结果、prepared、报告和元数据 |

## 阶段 1 后宪法复核

分类配置、manifest v5 和 product API 设计均未改变一个包/一个任务、离线执行、规则隔离或真实数据边界；安全解压、阶段屏障和 UTC 日志仍由现有执行器契约承载。`pkg.extract.classification` 作为唯一分类发布单元，避免旧七个分类路线各自发布造成 catalog 不一致。门禁通过，可进入 `$speckit-tasks`。

**下一阶段**：生成 `tasks.md`，运行 `$speckit-analyze` 做 spec/plan/tasks 一致性检查，完成 review 后再在 `main` 提交全部 Speckit 产物并创建实现 worktree。
