# PatrolX 设计机制参考

本文整理项目中反复出现、需要长期参考的设计机制。它不替代架构文档或契约文档：

- 系统结构和数据流以 [`docs/architecture.md`](../architecture.md) 为准。
- 契约字段和数据模型以 [`docs/data-model.md`](../data-model.md) 为准。
- 接口结构以 [`docs/api/openapi.yaml`](../api/openapi.yaml) 为准。
- 项目不可妥协原则以 [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) 为准。

每类机制尽量区分：

- **目标设计**：长期期望遵循的模型。
- **当前实现**：当前代码中的实际行为。
- **差异**：需要后续迁移、修正或评审的点。

## 1. 解压与分类机制

### 目标设计

- 一个压缩包对应一个任务和一个输出目录。
- 原始上传包只读，不被修改。
- 只使用两个隐藏的 P0 基础设施单元：`pkg.extract.main` 与
  `pkg.extract.classification`，不作为普通巡检规则展示。
- `pkg.extract.main` 只建立并校验 `.main/` 证据现场；分类动作只从该证据现场读取。
- `pkg.extract.classification` 按上传网元类型选择 `UMF`、`CSP` 或 `GENERIC` profile，
  按真实来源路径执行告警、精细、忽略和 fallback 路线。
- 只有配置明确声明的归档才展开；未知归档按 fallback 原样保留，不通过内容嗅探或扩展名猜测分类。
- `manifest.json` v5 是分类现场的唯一发布凭据；普通规则只能读取其中的 `catalog[]`。
- 解压必须具备路径穿越、链接、成员深度和资源预算防护，并且同一包、同一配置重复执行保持幂等。

### 当前实现

实现入口位于 `app/inspectors/pkg.py`，核心位于 `app/services/extraction/`。

- `pkg.extract.main`：
  - 从只读原始包安全展开到 `.main/`，记录普通文件数量、checksum 和 evidence fingerprint。
  - 证据缺失、损坏、含链接或指纹不符时，复核原始包 checksum 后整场重建。
- `pkg.extract.classification`：
  - 读取 `deploy/config/classify_rules.yaml`，校验 profile、route、selection 和 fallback 可达性。
  - 在 `.classification.staging/` 构建目标根，完成 catalog 摘要复核后交换目标根并原子发布 `manifest.json`。
  - 发布失败时逆序回滚；成功后仅清理明确的 legacy 分类根，不触碰 `.main/`、`prepared/`、`rules/` 或 `reports/`。
  - 告警按 `Alarm Information/` 或 `Alarm Data/` 识别并递归展开；Service Logs、CHR、Host Debug/System、KPI 和 MML 只在配置声明时选择性解压。
  - `entries[]` 记录成功落位，`ignored[]` 记录未选成员或规则忽略，`conflicts[]` 记录稳定消歧，`failures[]` 记录局部失败；`summary` 按 route、category、action、status 汇总。
  - 单个成员归档损坏或预算拒绝使 classification 为 `WARN`，其余合法文件继续发布；配置、主包或发布失败为 `ERROR`，阻断 prepare/inspect。
- 解压规则均为 `hidden=true`，优先级为 `P0`。
- 分类配置是部署侧静态配置；没有在线修改 API、任务级覆盖或热更新契约。
- manifest v1-v4 一律不可复用。v5 仅在 checksum、evidence fingerprint、product、package kind、
  有效配置指纹、发布语义指纹、path-limit 和 catalog 校验全部一致时复用。
- 单文件选择遵循 exclude 优先于 include；未选成员写入稳定 ignored reason，成功选中的 `.gz` 只去除一层后缀。

### 差异

- 活动 KPI 规则只通过 `source_patterns` 读取自身匹配的最终文件；`.main/` 只作为证据现场，不进入规则匹配。
- manifest v5 catalog 是普通规则的唯一文件输入来源；普通规则不再扫描分类目录或通过隐藏规则直接交换数据。
- 日志规则已下线；日志文件仍按分类现场安全保留并可供历史结果追溯，但不会触发当前普通规则。

## 2. TaskFileCatalog 机制

### 目标设计

- `EXTRACT` 是统一屏障；主包、嵌套子包和 `.log.gz` 全部先展开到终态。
- 分类发布后从 v5 manifest 的 `catalog[]` 构建一次任务级内存文件清单，不扫描目录、不复制文件。
- catalog 只包含成功落位的普通文件，返回稳定排序、去重的 POSIX 相对路径及摘要。
- 链接、越界路径、非法 pattern 和路径穿越立即拒绝。
- 普通规则和 owner 私有 prepare 的输入必须来自同一个 `TaskFileCatalog`。

### 当前实现

实现位于：

- `app/services/extraction/`
- `app/services/scanning/catalog.py`
- `app/services/scanning/matcher.py`
- `app/services/executor.py`

关键机制：

- `Executor.run_all()` 在 `pkg.extract.main` 与 `pkg.extract.classification` 完成后调用 `ctx.ensure_catalog()`。
- `TaskFileCatalog.build()` 只读取有效 manifest v5 的 `catalog[]`，并校验路径边界、普通文件、size、SHA-256 和 summary 一致性。
- `TaskFileCatalog.match()` 委托 matcher，对每个相对路径执行 `re.fullmatch()`。
- `RuleContext.resolved_files()` 通过 catalog 将相对路径解析到任务根内。
- 单规则重跑先确保 manifest 和 `.main/` 可复用，必要时重建主包现场，再构建 catalog。
- fallback 保留的未知归档是目标根下的最终文件，会进入 catalog；未展开成员不会进入 catalog。普通规则仍只依赖自身 `source_patterns[]`。
- 普通规则无匹配时，执行器可根据 manifest 的 ignored/failures 摘要补充可读 `skip_reason`；规则本身不读取 manifest 或其他规则数据。

### 差异

当前核心路径已解耦；后续新增数据入口必须接入 catalog，不得恢复规则内遍历任务目录。

## 3. `source_patterns` 机制

### 目标设计

- 普通规则声明 `source_patterns[]`。
- pattern 对 `TaskFileCatalog` 中的 POSIX 相对路径执行完整匹配。
- 路径分隔符统一为 `/`。
- 规则只能读取匹配到的文件，不得直接依赖其他规则实现。
- 无匹配文件、格式不适用或解析失败时返回 `skip` 和非空 `skip_reason`。

### 当前实现

- `Inspector.source_patterns[]` 在注册时校验非空、无首尾空白、无绝对路径、无穿越和 `~`。
- matcher 在运行时再次防御校验，拒绝非法正则、绝对路径、Windows 盘符、`~` 和路径穿越。
- 执行器把匹配结果交给普通规则；owner prepare 使用同一机制接收自己的 source_patterns 输入。
- 无匹配的普通规则返回 `skip`，prepare 状态为 `SKIP`。

### 差异

核心路径已统一；新增规则不得引入规则间 artifact 或 prepare 依赖。

## 4. 日志过滤机制（历史，已下线）

> 037 规则库收缩已删除日志规则实现与活动注册。以下 4-9 节仅用于解释历史 `RuleResult`，不得作为当前实现或恢复规则的设计依据。

### 历史实现

实现位于 `app/inspectors/log/filter.py`。

`log.filter` 是 P0 普通日志统计规则，不产出供其他规则消费的规范化 artifact。

输入：

```text
TaskFileCatalog 中匹配 ^logs/.*\.log$ 的文件
```

输出：

```text
output/<task_id>/rules/log.filter.json
```

处理逻辑：

1. 通过 `TaskFileCatalog` 接收匹配到的最终 `.log` 文件。
2. 按目录结构推导服务名和节点名：
   - 去掉 `ServiceLog_*` 前缀目录；
   - 忽略 `log` / `logs` 目录名；
   - 如果没有目录信息，则用文件名推导服务名。
3. 使用正则解析标准日志行：`timestamp LEVEL message`。
4. 统计 `WARN` / `WARNING` / `ERROR` / `FATAL` / `CRITICAL` 保留行和总扫描行。
5. 错误级日志后的无法独立解析的连续非空行标记为 `STACK`。
6. 无匹配日志或没有可解析记录时返回 `skip`；读取异常返回 `error`。

### 差异

- 过滤等级当前是模块常量 `MIN_LEVEL = 30`，阈值参数化是后续优化点。
- 该规则只是统计入口；分析类日志规则同样直读各自匹配的源日志。

## 5. 日志服务与节点识别机制（历史，已下线）

### 历史实现

规则通过目录结构识别服务与节点：

```text
logs/ServiceLog_<timestamp>/<service>/logs/<node>/<file>.log
```

处理策略：

- 忽略 `ServiceLog_*` 目录。
- 忽略 `log` / `logs` 目录。
- 第一个剩余路径段作为 `service`。
- 其余路径段拼接为 `node`。
- 没有目录信息时，用文件名作为服务名。

示例：

```text
logs/UmfService/logs/paas-192.168.2.2/UmfService.log
```

会被识别为：

```text
service = UmfService
node    = paas-192.168.2.2
```

## 6. 堆栈识别机制（历史，已下线）

### 历史实现

在 `log.filter` 中：

- 标准日志行如果能解析出 `ERROR` / `FATAL` / `CRITICAL`，会进入“堆栈跟随”状态。
- 后续无法解析为标准日志头、且非空的行会被标记为：

  ```text
  level = "STACK"
  ```

- 遇到下一个可解析的标准日志头时重新判断是否开启堆栈跟随。
- `log.stacktrace` 通过共享解析结果统计 `STACK` 行：
  - 用正则识别异常类名，例如 `FooException`、`BarError`；
  - 按 `(service, exception_type)` 聚合。

### 差异

- 当前堆栈识别是启发式的，依赖日志格式和缩进/非空行连续性。
- 对于多行日志框架、JSON 日志或非标准堆栈格式，不一定可靠。

## 7. 错误归一化机制（历史，已下线）

### 历史实现

实现位于 `app/inspectors/log/repeat_error.py`。

用于识别高频重复错误：

- 跳过 `STACK` 行。
- 对错误消息做归一化：
  - UUID 替换为 `<var>`；
  - 数字替换为 `<var>`；
  - 消息转小写。
- 按 `(service, normalized_message)` 计数。
- 阈值：
  - `>= 5`：`warn`
  - `> 20`：`fail`

该机制适合识别连接池耗尽、认证失败、重试风暴等重复模式。

### 差异

- 当前只替换 UUID 和数字，尚未处理时间戳、请求 ID、IP、端口、内存地址等常见变量。
- 归一化结果直接作为 finding 标题，可能影响可读性。

## 8. 服务专属日志规则机制（历史，已下线）

### 历史实现

服务专属规则目前通过精确服务名过滤：

- `log.umf_service` 只处理 `service == "UmfService"`。
- `log.umf_acc` 只处理 `service == "UMFAcc"`。

这些规则直接过滤 `TaskFileCatalog` 匹配到的源日志记录。

| 规则 | 匹配方式 | 判定 |
| --- | --- | --- |
| `log.umf_service` | 文本包含 `auth failure` / `retry timer exceeded` | 任一类命中数 `>= 3` 时 `fail` |
| `log.umf_acc` | 文本包含 `connection pool exhausted` 或包含 `sctp` | 连接池 `>= 2` 或 SCTP `>= 3` 时 `fail` |

### 差异

- 服务名目前是硬编码常量。
- 匹配条件主要是字符串包含，不是显式配置化模式。
- 服务和错误类型的扩展目前需要改代码；长期更适合由规则配置或模式声明驱动。

## 9. 日志状态判定约定（历史，已下线）

历史日志规则普遍遵循：

- 无匹配源文件或无可解析记录：`skip`
- 无匹配服务日志：`skip`
- 无错误或无命中：`pass`
- 有轻微问题：`warn`
- 超过阈值或命中高风险模式：`fail`

主要阈值集中在各规则文件顶部：

| 规则 | warn | fail |
| --- | ---: | ---: |
| `log.error_density` | 错误数 `> 100` | 错误数 `> 200` |
| `log.service_errors` | 单服务错误数 `>= 5` | 单服务错误数 `> 20` |
| `log.repeat_error` | 重复次数 `>= 5` | 重复次数 `> 20` |
| `log.stacktrace` | 有异常 | 异常总数 `> 5` |
| `log.fault_pattern` | 有命中 | HIGH 模式命中 `>= 2` 或单模式 `> 10` |
| `log.aaa_service` | 有命中 | 任一模式 `>= 3` |
| `log.app_service` | 有命中 | 连接池 `>= 2` 或 SCTP `>= 3` |

## 10. 规则注册与展示一致性机制

### 目标设计

注册表是规则元数据的唯一来源；API 和前端展示不应手写规则列表，必须全部从注册表读取，保证"注册了什么就展示什么"。

### 当前实现

注册和展示的完整链路：

```text
app/inspectors/**  各模块文件末尾调用 registry.register(inspector)
        │
        ▼
RuleRegistry       启动时 load_all() 自动扫描 app/inspectors/** 装载全部规则
        │
        ▼
GET /api/v2/inspectors   调用 registry.all(include_hidden=...) 返回规则元数据
        │
        ▼
前端 InspectorsPage       调用 api.listInspectors() 展示规则管理列表
前端 TaskDetailPage       用 hidden 字段过滤任务结果中隐藏规则的展示
```

关键约束：

- 注册表自动扫描 `app/inspectors/` 下所有 Python 模块；每个模块在文件末尾通过 `registry.register()` 注册。
- 普通规则与两个隐藏解压单元（`pkg.extract.main`、`pkg.extract.classification`）统一注册；隐藏单元通过 `hidden=True` 区分。
- `GET /api/v2/inspectors` 默认 `include_hidden=False`，只返回普通规则；传 `?include_hidden=true` 可返回全部。
- 前端规则管理页（`InspectorsPage.tsx`）和任务详情页（`TaskDetailPage.tsx`）都通过 API 获取规则列表，不硬编码规则编码。
- 任务详情页使用 `hidden` 字段构建隐藏集合，从任务结果中过滤隐藏规则后再展示。

### 差异

当前活动普通规则为 `alarm.active_state`、`alarm.recurrence` 和 `kpi.measurement_units`，隐藏单元只有
`pkg.extract.main` 和 `pkg.extract.classification`。两条告警规则独立执行，不互相导入或消费 prepare；已删除规则的历史结果仍可从
持久化数据读取，但不会因历史数据重新出现在活动目录。新增普通规则必须经过新的规格、契约和规则库范围审查，
不能通过注册旧模块恢复。

## 11. 后续迁移建议

为了收敛机制，建议后续按以下方向处理：

1. 新增规则必须只通过 `TaskFileCatalog` 接收 source_patterns 匹配结果。
2. 不为普通规则引入规则间 artifact 或 prepare 依赖。
3. 阈值继续收敛到可配置参数，并保持结果契约稳定。
4. 为 KPI 大文件解析补充流式处理和内存边界测试。

## 12. KPI 测量单元与指标自动入库机制

### 目标设计

KPI 指标列必须按测量单元归属，并在任务执行时完成归属与登记：目录未覆盖的指标自动入库且默认启用，
人工注册与绑定确认只作为异常修正手段；派生指标以受控公式（成功率/反向成功率）在前台维护。

### 当前实现

#### 文件归属与指标登记

任务执行 `kpi.measurement_units` 规则时（`app/services/kpi_measurement_units.py`）：

- 按文件名主干匹配已启用测量单元；未匹配文件计入 `unmatched_files`，多周期文件中非首选周期计入 `skipped_files` 并记录原因。
- 解析 CSV 表头（允许表头前存在 `key：value` 元数据行）；中英文表头互斥，中文按 `测量开始时间`、`测量结束时间`、`周期(分钟)` 定位，英文按 `StarTime`/`StartTime`、`EndTime`、`Period(Minute)` 定位。
- 成功率空值只有在业务主体唯一匹配的请求数为 `0` 时记为 `not_applicable_count`，不再计为空值异常；正分母、分母缺失或匹配歧义仍按异常处理。名称相近的 Media / DC / Data Channel 成功率指标保持独立。
- 指标列归属规则：
  - 目录已有同名指标 → 复用既有指标，不重复创建；
  - 指标已归属其他测量单元 → 生成跨测量单元冲突记录，不自动改绑；
  - 目录中不存在 → 自动创建指标资源并归属当前测量单元，默认启用（specs/021）。
- 绑定状态为 `confirmed` / `candidate` / `conflict`；只有绑定 `status=confirmed`、绑定 `enabled=true` 且 ME 指标资源 `enabled=true` 的指标参与解析、判定和历史索引，停用指标不写入 `kpi/history/index.jsonl`；人工注册指标走
  `POST /api/v5/kpi/measurement-bindings/{binding_id}/register-metric`，批量确认走 `POST /api/v5/kpi/measurement-bindings/batch-confirm`。

#### 判定维度

| 维度 | 说明 |
| --- | --- |
| 文件归属 | 未匹配、周期跳过与解析失败按文件记录，不中断其他测量单元 |
| 数值可读性 | 空值、非数值、时间列异常计入数据异常 |
| 业务阈值 | 按指标方向（higher_better / lower_better / neutral）与预警、失败阈值输出 warn / fail（specs/022） |
| 任务内趋势 | 同一指标在任务内多个时间点上的恶化判定计入趋势恶化计数 |

#### 派生指标

界面派生指标保存在 SQLite `kpi_measurement_derived`（测量单元 + 指标资源 + 分子/分母指标 + 模板），
经 `POST /api/v5/kpi/measurement-derived` 维护；模板限 `success_rate` 与 `reverse_success_rate`，
依赖的分子、分母指标必须已确认绑定。

#### 结果形态

规则结果 `output/<task_id>/rules/kpi.measurement_units.json` 的 `metadata.measurement_units[]` 保存每个测量单元的
指标明细、状态与来源文件；结果组织完成后重建任务私有历史索引 `kpi/history/index.jsonl`，跨任务趋势按需流式读取候选任务索引。

### 差异

历史设计的 v4 动态口径配置中心、任务级分类线索接口与
`metric-rules.json` 公式配置已被测量单元模型替代，不再作为现行实现描述。

## 13. SQLite 数据库文件使用注意

### 目标设计

SQLite 单文件数据库（`data/patrolx.db`）在程序空闲时可直接复制；程序运行中需使用 `sqlite3 .backup` 保证一致性。

### 当前实现

- 空闲时（API / CLI 均未运行）：直接 `cp data/patrolx.db <目标>` 即可。
- 运行中：使用 `sqlite3 data/patrolx.db ".backup <目标>"`，避免只拷主文件而丢失 journal/WAL 导致副本不一致。
- 迁移到其他机器或目录：拷贝后修改 `app/core/config.py` 中 `sqlite_path` 或环境变量即可。

### 差异

当前无已知差异。

## 14. 阶段内并行执行机制

### 目标设计

- 单包任务内按 `EXTRACT → PREPARE → INSPECT → 收尾` 的固定阶段屏障执行，阶段内最多 4 个进程并行。
- 并行只做执行层优化：规则判定逻辑、`rule_version`、结果契约、任务目录布局与 prepare 私有语义全部不变。
- 父进程唯一写盘；worker 不写 `execution.log`、`rules/*.json`、任务摘要与报告。
- 小任务不为并行付固定开销：待执行单元 < 3 或匹配文件总字节 < 8MB 时整体串行直通。

### 当前实现

- `app/services/unit_runtime.py`：`UnitRequest` / `UnitOutcome` / `RuleContext` 与 `execute_unit()`；串行与并行共用同一份单元执行实现，规则异常与 prepare 失败都在单元内收敛为结果。
- `app/services/parallel.py`：`ParallelPolicy`（`max_workers=4`、`min_units=3`、`min_matched_bytes=8MB`，无 CLI/环境变量/API 入口）与阶段运行时 `StageRunner`（`spawn` 上下文、惰性建池、跨阶段复用、`finally` 回收）。
- `app/services/executor.py`：父进程规划（源文件匹配、缓存命中、skip 判定）后把需要执行的单元交给阶段运行时；`EXTRACT`、`run_rule_with_deps()` 与收尾保持串行。
- 单写者：单元日志先缓冲、父进程按计划序 flush 到 `execution.log`；`RULES_TOTAL` 只由父进程自增；prepare 成功后由父进程写 `.prepare.sha256` marker，失败不写。
- 降级：worker 非正常退出写 `parallel_degraded`（`broker_broken` + 受影响单元数 + 仍失败单元数），未完成单元在独立单进程池内逐个补跑，只在该单元仍崩溃时记 `error`，不重试，后续阶段不再并行。
- 可观测：`stage_parallel_start` / `stage_parallel_done` 记录 `mode`、直通原因、`workers`、`pending_units`、`matched_bytes`、`wall_ms`、`slowest_unit_ms` 与父子峰值 RSS（统一换算为字节）。

### 差异

- 并行度固定 4，本版不提供配置项；放开 prepare 跨规则共享消费属于后续独立版本，需先修订宪法与相关契约。
- 解压阶段、收尾阶段与单条规则内的 chunk 级并行不在本版范围。

## 15. 未清除告警与反复上报机制

### 扫描与独立性

`alarm_all` 只声明 `^alarm/[^/]+\.csv$`，两条规则均引用该扫描组，只读取任务内 `alarm/` 直属 CSV。嵌套目录、
非 CSV、操作日志、配置、状态文件与跨任务数据都不在输入范围。规则不声明 prepare，不写 prepared 数据，也不能
读取另一条告警规则的 JSON。

公共实现集中在 `app/inspectors/alarm/common.py`，只负责解码、表头解析、字段归一化、去重、质量统计与覆盖
范围，不生成 `RuleResult`。单文件失败只记录在该文件质量中，不阻断其他文件；文件大小、行数和任务行数均有固定预算。

### 中英文映射

表头、状态、严重级和对象键别名集中维护，当前覆盖英文与中文常见导出。未识别术语保留在
`unknown_headers`、`unknown_status_values` 或 `unknown_severity_values` 质量统计中；后续补充权威映射时只扩展
公共映射与测试，不改变两条规则的判定语义。UTF-8 BOM、GB18030、无时区按 UTC+8、带偏移时间转 UTC 均由公共解析层处理。

### 双计数与事实边界

| 口径 | 定义 | 用途 |
| --- | --- | --- |
| 原始重复次数 | `Σ Repeat Times` | 保留源字段的原始累计值 |
| 估算上报总数 | `Σ(1 + Repeat Times)` | 仅用于比较潜在上报规模，不是精确事件总数 |

`alarm.active_state` 以状态列的 `Not Cleared` 作为活动判据，不使用“清除时间为空”另行推断活动状态。它按
应用、告警 ID 与对象聚合，并依据 `coverage.end_at` 计算活动持续时长。`alarm.recurrence` 按应用与告警 ID
聚合全部生命周期，输出对象明细、状态与严重级分布、`multi_lifecycle`、`repeat_reporting`、`short_alarm`、
`rapid_recurrence`、`reset_cleared` 证据。

`coverage.end_at` 是最大有效告警时间，不是恢复时刻或任务执行时刻。规则不判断操作时间/非操作时间，也不把某个
时间窗称为计划外窗口。`Reset Cleared` 不代表稳定恢复；观察末刻之后没有记录也不能证明已经恢复。

### 结果与展示

规则结果分别使用 `metadata.alarm_active` 与 `metadata.alarm_recurrence`。规则详情页分别渲染“未清除告警”和
“告警反复上报”，HTML 报告读取活动规则结果生成“告警优先处置”摘要。历史 `metadata.alarm_flapping` 只按旧结构
只读展示，不迁移为上述命名空间。

## 16. 告警生命周期与闪断判定机制（历史，已下线）

### 目标设计

- 恢复结论必须来自清除时间与观察窗口，不能信任告警源系统的状态字段。
- 闪断（反复出现）与未恢复是两个独立事实，必须同时呈现，不能互相掩盖。
- 数据不足、数据脏和真正"稳定"要显式区分：不确定时标注，不猜测。
- 规则只读自身 `source_patterns` 匹配文件，不消费其他规则结果与 prepare 数据。

### 历史实现

历史 `alarm.flapping` 实现曾按 `alarm_code + object` 分组，单次遍历解析记录后聚合；其源码与活动注册均已删除：

1. 解析层：CSV 与 TXT 统一解码（UTF-8 / GB18030，CSV 兼容 UTF-8 BOM），字段名归一为小写去空白后经别名表映射
   真实导出中文表头（`应用名称` → `object`、`告警ID` → `alarm_code`、`发生时间` / `清除时间` → 生命周期起止等）；
   时间兼容 ISO-8601 与 `YYYY-MM-DD HH:MM:SS`，无时区按 +08:00 解释；TXT 没有清除时间时按未清除处理。
2. 清洗层：行级校验（时间不可解析、清除早于创建、缺 `alarm_code`）计入 `excluded_rows`；
   四元组 `alarm_id + created_at + alarm_code + object` 去重计入 `duplicate_rows`。
3. 聚合成组：每条分组的记录按出现时间排序，计算出现/清除计数、首末时间、持续时长、最短复发间隔与闪断事件。
4. 判定层：`_main_state()` 输出六态互斥主状态——未清除且反复（fail/CRITICAL）、未清除未反复（warn）、
   已清除但反复（fail/HIGH）、已清除但短告警（warn/MEDIUM）、观察窗不足（warn）、已清除且稳定（pass）。
5. 证据层：Finding 文案携带分组键、出现分布、首末与最近清除时间、最短复发间隔、定位信息（去重、最多展示 3 处）、
   本次生效阈值、操作窗证据与来源文件行号；`metadata.alarm_flapping` 输出 `policy`、`coverage`、`totals`、`state_counts`
   与分组明细，明细携带展示用 `app_ids` / `locations` / `event_types` / `clear_types` / `source_repeat_max`（不参与判定）。

窗口与阈值口径：

| 口径 | 定义 | 默认值 |
| --- | --- | --- |
| 短告警 | 已清除分组的最长持续时长 ≤ 阈值 | `short_alarm_sec=300` |
| 复发 | 同一窗口内出现次数 ≥ 阈值 | `repeat_window_sec=3600`、`min_repeat_count=3` |
| 闪断事件 | 相邻出现间隔 ≤ 阈值时并入同一事件 | `flap_gap_sec=1800` |
| 稳定观察窗 | 最后一次清除距覆盖末端 ≥ 阈值才可判稳定 | `stable_observation_sec=1800` |
| 操作窗 | 只标注窗口内/外出现与窗口外再现、窗口后未恢复，不降级主状态 | `operation_window=00:00-02:00`、`operation_window_enabled=true` |

判定优先级固定：未清除事实 > 反复事实 > 短告警 > 观察窗不足兜底 > 稳定。因此一个分组可能同时携带
`cleared_repeated` 主状态与 `observation_insufficient` 标记（例如三次闪断后刚清除），两者在界面上分别呈现。

### 差异

- 该规则已不可重跑或重建；本节阈值与字段仅用于解释已持久化的历史结果。
- 历史操作窗参数只解释旧结果，不能用于现行告警规则判断操作时间或非操作时间。
- 时间轴联动（把闪断结论叠加到设备时间轴）不在本版范围，后续版本必须通过既有 `RuleResult` 读取，
  不得让其他普通规则直接消费本规则产物。
