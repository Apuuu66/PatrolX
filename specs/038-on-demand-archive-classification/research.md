# 阶段 0 研究：按真实目录进行按需归档分类

**功能**：`038-on-demand-archive-classification`
**日期**：2026-11-02
**输入**：[spec.md](spec.md)
**结论**：所有规划未知项均已收敛，无 `NEEDS CLARIFICATION`。

## 1. 分类配置采用版本化 YAML 与显式 profile

### Decision

`deploy/config/classify_rules.yaml` 升级为版本化、只读的部署侧配置。顶层键集合严格为 `{version, profiles, routes}`；每条 route 明确声明 `id`、`phase`、`priority`、`profiles`、`source`、`action`、`category`、`target`，归档选择动作可额外声明 `selection` 与 `member_decompress`。资源预算不进入 YAML，而是作为代码常量写入 Manifest v5 快照。

巡检包的生效 profile 只由任务 `product` 决定：`UMF` 或 `CSP`。日志补充包没有 product，使用不会触发 UMF/CSP 精细路线和台账匹配的 `GENERIC` profile。告警 route 可同时声明 `[UMF, CSP]`，因此任一网元类型的包都能识别两种告警目录。

### Rationale

真实目录调整应只改配置，不应修改分类器。显式 profile 把“上传网元类型决定规则集”变成可校验的数据，而不是在代码中写网元分支；`GENERIC` 又避免日志补充包被强制绑定 UMF/CSP。

### Alternatives considered

- 继续使用文件名关键字和扩展名：无法区分 MESH CSV 与 KPI CSV，也会误收 `0/` 内容。
- 在 Python 中为 UMF/CSP 写硬编码分支：每次目录变化都要求改代码，违反配置驱动目标。
- 以包名推断 product：包名不是可信元数据，本地与在线模式也无法保持一致。

## 2. 使用受控目录 glob，不使用自由正则

### Decision

来源路线拆为 `source.directory` 与 `source.file`。`directory` 匹配文件父目录的完整规范化路径，目录段只允许 literal 或完整段 `**`；`file` 是只作用于文件名的 glob，支持 `*`、`?`，不得跨 `/`。配置不接受任意 regex。

`source.scope` 为 `scene` 时，路径相对于推导出的场景根；为 `evidence` 时，路径相对于 `.main/` 证据根。`source.capture_root` 可指定一个 literal 目录段，`{suffix}` 从该段之后开始；缺省时从 scope 根之后开始。若同一目录段出现多次，使用最右侧完整段。

### Rationale

真实包变化主要发生在外层包装深度。受控 `**` 段足以表达“任意前缀”，同时可执行静态重叠校验；文件名 glob 比自由 regex 更小、更稳定、更容易证明不会跨目录。

### Alternatives considered

- Python regex：表达力过强，无法可靠判定同优先级冲突，也容易引入灾难性回溯。
- 全目录通配符：容易跨目录误匹配，不满足“只用真实目录和明确文件名”。
- 固定绝对深度：真实包外层包装深度会变化，已经证明不可靠。

## 3. 场景根由 profile anchor 推导

### Decision

每个 profile 声明 `scene_anchors`。分类器扫描证据文件的父目录，将任意完整目录段匹配 anchor 的目录前缀收集为候选，并按 anchor 父目录精确聚类。若存在多个候选，依次选择覆盖 anchor 种类最多、命中次数最多、目录层数最多（路径最具体）的候选，最后按大小写归一化路径字典序稳定决胜；没有命中 anchor 时，场景根回退到证据根。UMF 场景根只使用 UMF anchor，CSP anchor 不参与 UMF 根推导。

UMF 的 anchor 至少包含 `Basic Information About the UMF`、`Debugging Commands`、`Equipment Status`、`MESH Information (Problem)`、`System Resources`、`Operation Logs`、`MML Configurations`、`Performance Measurement Results`、`MESH Application Metrics`、`CHR Information`、`Host Debugging Logs`、`Host System Logs` 和 `Service Logs (Problem)`。每个 scene-scope 精确复制路线都必须把对应业务目录声明为 `capture_root`，否则业务目录会错误进入目标路径。

### Rationale

真实包场景根是 `.../UMF Problem scene`，但其外层设备目录、问题编号和包装层可能变化。由已知业务子目录反向聚类，并优先选择覆盖 anchor 种类最多、命中次数最多且路径最具体的父目录，可以去掉包装层，同时不把场景内中间目录带入 fallback 目标。

### Alternatives considered

- 写死 `UMF Problem scene`：名称可能有变体，且不是所有来源都直接位于该目录。
- 以证据根作场景根：会把设备名、问题编号等外层目录写入 `other/`。
- 以所有候选的公共父目录作根：孤立共享 anchor 会拉宽场景根并污染相对路径。

## 4. 固定阶段优先于声明顺序

### Decision

匹配阶段固定为 `alarm > precise > ignore > fallback`，配置声明顺序不影响选择。阶段内按 `priority` 降序选择；只有同阶段、同 priority、profiles 有交集且来源模式可重叠时，配置才校验失败。不同 priority 的重叠允许存在，高 priority 稳定胜出。

告警 route 使用 `alarm` 阶段；UMF 精细路线使用 `precise`；普通 `0/` 内容使用 `ignore`；每个 profile 最终必须有可达的 `fallback` 或 catch-all `ignore`。route 必须显式声明优先级，不依赖 YAML 数组顺序。

### Rationale

`0/Problems/Alarm Data/` 同时符合“`0/` 普通内容”和 CSP 告警特征。把告警设为最高阶段，能从结构上保证告警不会被忽略规则截获，也避免操作者调整 YAML 顺序导致行为反转。

### Alternatives considered

- 按 YAML 顺序取第一条：配置重排会改变分类结果，不稳定。
- 仅给所有 route 一个全局 priority：告警与精细规则的语义优先级不够清楚。
- 运行时再判断冲突：任务结果可能依赖输入文件，无法在开始前保证配置可执行。

## 5. 同优先级重叠使用可执行 ε-NFA 乘积校验

### Decision

目录 literal 段、`**` 段和文件名 glob 编译为 ε-NFA。字符 universe 由规范化 pattern 中出现的 literal scalars 加一个 `OTHER` 等价类组成；locale 无关地使用 `str.upper()` 做大小写不敏感比较。`*` 匹配零个或多个非 `/` 字符，`?` 匹配一个非 `/` 字符，`**` 只匹配零个或多个完整目录段。

对同阶段、同 priority、profiles 有交集的两条 route，构建状态乘积并做 ε-closure 可达性搜索；任意共同接受路径即判定重叠并拒绝配置。scene scope pattern 在冲突检查中等价扩展为 `**/<scene-pattern>`，evidence scope 保持原样，因此跨 scope 的重叠也不会漏检。

### Rationale

受控 glob 可以转换成小型自动机；乘积校验能穷尽所有可匹配路径，而不是只比较示例字符串。等价字符类使 Unicode 文件名也能得到确定的“是否可能重叠”结论。

### Alternatives considered

- 抽样路径比较：会漏掉长路径、空目录段和边界组合。
- 只比较 literal 前缀：无法发现 `**`、`*` 和 `?` 的组合重叠。
- 允许同优先级重叠并运行时择一：违反配置完整校验要求。

## 6. 动作只覆盖明确保留和按需展开

### Decision

动作固定为：

- `copy`：复制普通文件到目标模板。
- `expand`：展开 route 命中的归档，成员继承 route 的 category/action 语义；可选 `member_decompress` 对指定成员 GZIP 解压。
- `decompress`：解压 route 命中的单文件 GZIP。
- `expand_recursive`：告警专用，递归展开 ZIP、TAR、TAR.GZ、GZIP，并保留非归档成员。
- `select_and_decompress`：按 `selection.include/exclude` 选择归档成员，对命中的 gzip 成员解压。
- `ignore`：不落位，只写忽略审计。
- `fallback`：profile 的 catch-all 复制动作。

`selection.include[]` 是 `{pattern, service?}`；`selection.exclude[]` 是 `{pattern, reason}`。未知归档如果未命中 expand/decompress 动作，必须作为普通文件原样复制，绝不通过成员名或内容嗅探自动展开。

### Rationale

动作名称直接表达证据处理方式，使“是否展开”成为配置事实。Service Logs 和 CHR 需要“选成员后再解压”，不能用“整个归档类别锁定”含糊代替。

### Alternatives considered

- 通用 `extract_if_needed`：无法审计某归档为何被展开。
- 自动识别所有压缩包：违反按需展开，也扩大攻击面和运行成本。
- 用成员扩展名决定 category：正是本次要移除的错误行为。

## 7. 目标模板只允许有限变量并稳定消歧

### Decision

目标模板必须是相对 POSIX 路径，首段必须属于固定工作根 allowlist。允许变量仅为 `{suffix}`、`{member}`、`{archive_stem}`、`{service}`、`{node_path}`、`{name_without_gz}`，并按动作限制可用变量。`{member}` 表示动作完成后的成员相对路径；单个 `.gz` 解压后去除该后缀。

目标冲突时不得覆盖。实际目标在首个扩展名前插入 `__<digest12>`；digest 为 `SHA-256(product + NUL + source_relative + NUL + member_relative)` 的前 12 个十六进制字符。若该名称仍存在，则依次追加 `-2`、`-3`，只使用确定性序列。entry 同时保存 `original_target` 与 `target`。

`{node_path}` 用于 Service Logs：取选中成员父路径，并在首个目录段与配置的 `{service}` 大小写不敏感相等时移除该段。空变量与相邻 `/` 一并省略。

### Rationale

有限模板可静态验证目标越界和未知变量，也能避免 Python format 注入。以 profile 和真实来源身份生成冲突后缀，能让同一输入重复执行得到相同路径，并保留全部证据。

### Alternatives considered

- 时间戳或随机 UUID：破坏幂等性。
- 直接覆盖：丢失证据。
- 保留完整证据绝对路径作为目标：泄漏外层包装结构且路径过长。
- 在冲突时按处理遍历顺序编号：并发和排序变化会导致结果漂移。

## 8. Manifest 升级为 v5，并把 catalog 作为唯一巡检入口

### Decision

Manifest v5 顶层字段固定为 `version`、`main`、`product`、`classification`、`path_limit`、`entries`、`ignored`、`conflicts`、`failures`、`catalog`、`summary`。`classification.snapshot` 保存 profile、package kind、规则集、配置指纹、解压策略指纹、路径限制和目标根集合。

`catalog[]` 是成功落位文件的稳定排序对象列表，包含 `path/category/route_id/source_relative/sha256/size`。`TaskFileCatalog.build()` 只读取 v5 catalog，不再扫描固定七个目录。证据、配置、审计、prepared、rules、报告、任务元数据和执行日志永不进入 catalog。

### Rationale

固定目录扫描无法表达新的多级目录，也会把未成功或明确忽略的文件暴露给规则。持久化成功文件清单能同时在执行、单规则重跑、CLI explain 和 API 展示中复用同一事实。

### Alternatives considered

- 运行时再次 `rglob`：会把残留文件、审计文件和失败临时文件带入规则。
- 保留七个分类目录：无法覆盖 `basic/debug/status/mml/chr/logs` 等新结构。
- 在规则中解析 entries：会把审计模型变成普通规则依赖，违反规则隔离。

## 9. 复用分类前先校验证据与语义快照

### Decision

每次执行先加载并完整校验配置，再计算当前快照。复用 v5 manifest 必须同时满足：主包 checksum 一致、`.main/` 存在且 evidence fingerprint 一致、product/profile/package kind 一致、配置指纹一致、解压策略与路径限制指纹一致、catalog 均指向合法普通文件。

证据现场有效但快照变化时，只从 `.main/` 重建分类工作现场；证据现场缺失或损坏时，复核原始包 checksum 后重新安全解压 `.main/`。v4 manifest 一律视为不可复用并重建。配置无效时任务分类规则返回 `ERROR`，不得回退旧配置或部分规则。

### Rationale

分类配置和网元类型变化不影响主包证据，应该避免重复解压原包；但任何语义变化都必须清除旧工作结果，否则会出现目录已更新、catalog 仍旧的隐蔽错误。先校验配置也修复当前实现“先复用、后加载配置”的缺陷。

### Alternatives considered

- 只看 manifest 版本和主包 checksum：配置变化后错误复用。
- 每次删除 `.main` 重解压：慢且增加真实包读取，虽然安全但不必要。
- 配置无效时保留旧现场继续跑：违反 fail-closed 和可审计要求。

## 10. 分类现场采用 staging + manifest 发布屏障

### Decision

分类器在 `.classification.staging/` 中完整构建新工作目录和审计，主进程完成全部写入后，先使旧 manifest 不可见，再逐根目录交换 staging 内容并回滚失败项，最后通过 `os.replace()` 发布新 manifest。读取方只认可有效 manifest v5；manifest 未发布的中间目录不构成可巡检现场。

重建只替换配置目标根和有历史记录的分类根，删除旧分类残留；绝不删除 `.main/`、原始上传包、`rules/`、`prepared/`、报告或任务元数据。v4 遗留的 `logs/kpi/traffic/alarm/config/resource/other` 目录只在成功建立 v5 现场后按已知 allowlist 清除。

### Rationale

同一任务目录还承载规则结果等无关数据，不能整体替换 `output/<task_id>`。以 manifest 作为唯一发布屏障，可以让多目录交换在逻辑上原子，并在进程中断时依靠缺失/无效 manifest 触发下次重建。

### Alternatives considered

- 原地逐文件覆盖：残留文件和部分更新会污染 catalog。
- 整个任务目录 rename：会误删规则结果、prepared 和报告。
- 使用工作现场 symlink：TaskFileCatalog 禁止链接，且存在路径逃逸风险。

## 11. 资源预算、错误码和失败边界固定

### Decision

沿用并明确固定预算：嵌套归档深度 8、成员路径深度 12、单归档文件数 100,000、任务累计文件数 200,000、单文件 2GB、解压总字节 3GB。错误码固定为 `archive_depth_exceeded`、`member_path_depth_exceeded`、`file_count_exceeded`、`task_file_count_exceeded`、`file_too_large`、`total_bytes_exceeded`、`archive_corrupt`、`unsafe_path`、`link_rejected`、`duplicate_member`、`target_conflict`、`invalid_classification_config`。

主包 `.main` 无法建立时 `pkg.extract.main=ERROR`，任务不得进入 prepare/inspect。配置无效时 `pkg.extract.classification=ERROR`，同样阻断后续。子归档或单文件 GZIP 失败写入 `failures[]`，classification 返回 `WARN`，其他文件继续。

### Rationale

原有 `ArchiveError` 只有自然语言消息，执行器和界面无法稳定区分预算、损坏、路径和配置错误。固定错误码使审计、测试和 UI 聚合不依赖中文文本。

### Alternatives considered

- 继续解析异常字符串：文案变化会破坏调用方。
- 任一子包损坏都使任务失败：违反局部失败隔离要求。
- 放宽预算避免真实包失败：会失去解压炸弹防护。

## 12. 只保留两个隐藏解压单元

### Decision

隐藏规则固定为 `pkg.extract.main` 与 `pkg.extract.classification`。main 负责主包安全解压、`.main` 证据指纹和主包 checksum；classification 负责配置校验、profile/场景根、复用或重建、v5 manifest、catalog 和分类审计。旧 `pkg.extract.<category>` 单元全部移除。

准备页只展示这两项。main 或 classification 任一为 `ERROR` 时执行器设置解压门禁，prepare/inspect 均不进入。classification 为 `WARN` 时允许继续。两个隐藏规则逻辑均改变，`rule_version` 分别升级为 `4.0.0` 和 `1.0.0`。

### Rationale

分类不再是七个独立扩展名桶，而是同一个配置驱动的原子现场。拆成七个单元会让 catalog 在部分目录尚未成功时提前可见，也会让全局重叠校验和快照一致性无法成立。

### Alternatives considered

- 每个物理目录一个 hidden inspector：无法保证一次分类快照和单一 catalog。
- 保留旧 category inspector 兼容：UI 会展示不存在的分类，旧逻辑继续运行，违反清理目标。

## 13. KPI 兼容通过路径稳定实现，不修改 KPI 判定

### Decision

既有 `kpi.measurement_units` 保持规则代码、判定逻辑、指标契约和 `rule_version=3.3.0` 不变。PerfResult 成员必须全部进入 `kpi/<成员相对路径>`；`scan_rules.yaml` 的 KPI group 继续只含 `^kpi/.*\.csv$` 与 `^traffic/.*\.csv$`。MESH `CollectExport*.zip` 只进入 `other/MESH Application Metrics/<archive_stem>/`，不得进入 `kpi/`。

### Rationale

KPI 是当前唯一保留的普通巡检规则，分类重构必须保持其输入可见性。真实包 73 个 PerfResult 成员进入 `kpi/` 后，规则无需因新分类架构改版。

### Alternatives considered

- 修改 KPI `source_patterns` 以适配新目录：会改变规则可见输入，增加版本和回归风险。
- 把 MESH CSV 也放入 KPI：违反真实目录语义，制造 KPI 误匹配。

## 14. product 作为规范化任务元数据贯穿 API、CLI 和 worker

### Decision

巡检包上传时 `product` 条件必填；trim 后统一转大写，只接受 `UMF`、`CSP`。日志补充包禁止 product/province/operator。缺失和无值返回 `400 missing_product`，非法值返回 `400 invalid_product`。

同名任务命中幂等恢复路径时，必须先完成校验和判定，再按以下固定顺序判定 package kind 与 product，避免同一个请求因检查顺序不同返回不同错误：

1. 上传 checksum 与任务首次接收 checksum 不同：`409 package_checksum_conflict`。
2. checksum 相同，但上传 `package_kind` 与既有任务不同：`409 package_kind_conflict`。
3. 上传与既有任务均为 `inspection`，但规范化 product 不同：`409 package_product_conflict`。
4. 上传与既有任务均为 `inspection`，历史任务缺少 product：`409 package_product_conflict`，提示补充任务元数据后重试。
5. checksum、package kind、product 全部一致：幂等返回既有任务；磁盘现场已被清理时按既有恢复语义写回原始包，但不自动重跑。

product 保存在现有 `customer` JSON，不新增 SQLite 列。API、CLI、`RuleContext`、`UnitRequest`、分类 profile、inventory parser 和台账筛选使用同一个规范化值。OpenAPI 3.1 multipart 的 `product` 继续保持 optional nullable，但描述写明巡检包条件必填，并由服务端运行时校验承担条件约束，以保持生成客户端兼容。新增 `missing_product`、`invalid_product`、`package_kind_conflict`、`package_product_conflict` 错误码，既有 `package_checksum_conflict` 语义不变。`deploy/config/dicts.yaml` 的 product code 改为 `UMF`、`CSP`。

### Rationale

任务元数据已经存在于 `customer` JSON，新增列不会带来收益。统一大写消除字典、表单、台账和分类配置之间的大小写差异，同时不破坏既有客户元数据结构。先判定 checksum 再判定语义元数据，可以保证“不同内容永远优先按内容冲突处理”，并让恢复矩阵具有唯一结果。

### Alternatives considered

- 保留小写字典：product 在 API、DB 和配置间持续需要转换，容易漂移。
- 新增 product 列：需要数据库迁移，但当前 JSON 已足够查询和回填。
- 从真实路径或文件内容推断 product：不满足“上传时指定网元类型”的明确要求。
- 在 checksum 冲突前比较 package kind/product：会把同名不同内容误报为元数据冲突，掩盖真实覆盖风险。

## 15. 旧内容嗅探和策略链停止参与新分类

### Decision

新链路不得调用 `classify_content()`、`peek_*()`、按通用扩展名兜底或旧 `extract_policy.yaml` 的 skip/whitelist 策略。旧 `classify.py` 可删除或仅保留给明确的历史兼容测试；生产 extraction 不导入。旧 `policy.py`、`nested.py` 中与新链路冲突的实现迁移为 v5 分类引擎的一部分或移除。

未命中的 UMF 普通文件进入 `other/<场景相对路径>`，未声明展开的归档原样保留。所有忽略都必须来自配置 route 并进入 `ignored[]`，不能使用不可审计的全局静默跳过。

### Rationale

内容嗅探既慢又不可预测，还会把 MESH CSV 误判为 KPI；旧 whitelist 只按 `alarm` 关键字保留，无法表达真实目录和按需动作。保留这些旁路会让新配置失效而不易发现。

### Alternatives considered

- 新旧分类器并行并回退旧规则：配置错误时会产生隐蔽行为，违反显式失败。
- 保留扩展名兜底：真实同名 CSV 的业务含义由来源目录决定，扩展名不携带足够信息。
- 删除所有未知文件：会丢失证据并违反 UMF fallback 要求。

## 16. 真实包验收只读、可重复并核对基准计数

### Decision

真实包 `DataCollect/ALL_20261031173253.zip` 的已知基准为：SHA-256 `df3d09eb065a407193b0178200f195cebf571e7ff1d8ef6266d98e5ccf459687`，96 个外层文件；UMF product 分类后 2 个告警、73 个 KPI 成员、14 个 MESH CSV、98 个 Service Logs 业务日志、3 个 CHR `.bil`。每次真实验收必须在运行前后执行 `shasum -a 256`，输出和数据库置于隔离临时目录，真实包不得复制进仓库、进入 Git 或暂存区。

### Rationale

真实包包含被检环境数据，只能作为只读验收源；基准计数能发现分类中的静默丢失、过度保留和错误展开。前后哈希是宪法规定的真实性证明。

### Alternatives considered

- 将真实包加入 fixture：违反真实数据隔离。
- 只检查测试夹具：无法证明真实目录适配正确。
- 运行后移动或重新压缩真实包：破坏原始证据，禁止。
