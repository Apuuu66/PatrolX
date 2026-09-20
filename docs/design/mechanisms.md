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
- 解压使用隐藏的 P0 基础设施规则，不作为普通巡检规则展示。
- 主包内容按类别落位，日志、KPI、话统、告警、配置、资源等分别进入对应目录。
- 主包保留 `.main/` 原始解压现场；嵌套压缩包和 `.log.gz` 通过共享服务安全递归展开。
- 解压必须具备路径穿越、链接和资源预算防护，并且同一子包只解压一次。
- 部署侧可配置压缩项跳过与白名单；白名单优先于全局保留和路径跳过，主包本身不可跳过。

### 当前实现

实现位于 `app/inspectors/pkg.py`。

- `pkg.extract.main`：
  - 解压主包到 `.main/` 证据现场。
  - 调用共享解压服务，按 `deploy/config/classify_rules.yaml` 和内容特征递归分类。
  - 生成只包含最终文件的分类工作现场，成员直落 `<category>/<压缩包内部相对路径>`，并写入 `.patrolx-extracted.json` manifest v4。
- `pkg.extract.<category>`：
  - 汇总 manifest 中对应分类的子包与 `.log.gz` 终态。
  - 失败或冲突时返回 `warn`，不阻断其他规则。
- 解压规则均为 `hidden=true`，优先级为 `P0`。
- 解压策略加载自 `deploy/config/extract_policy.yaml`：
  - `whitelist.paths[]` 和 `whitelist.name_keywords[]` 命中后恢复既有解压流程。
  - `nested.skip_all=true` 或 `nested.skip_paths[]` 命中的非白名单压缩项不读取成员，保留为最终文件。
  - 路径前缀归一化后必须有目录边界；名称关键字按目录段和文件名忽略大小写匹配。
  - 保留项计入任务预算；只有复制成功才是 `skipped`，冲突/失败/拒绝分别是 `conflict`、`failed`、`rejected`。
  - manifest v4 的 `policy` 节保存快照、fingerprint、计数器和逐项决策；path-limit 快照变化时重建现场，v3 及更早清单不允许静默迁移。
- 策略是部署侧静态配置；没有在线修改 API、任务级覆盖或热更新契约。有效旧任务不因策略变化重建，现场缺失或损坏重建时使用当时配置。

### 差异

- 目前日志过滤通过 `source_patterns` 直读最终 `.log`；`.main/` 只作为证据现场，不进入规则匹配。
- 解压分类现场是普通规则的唯一磁盘输入来源；普通规则不再通过隐藏规则直接交换数据。

## 2. TaskFileCatalog 机制

### 目标设计

- `EXTRACT` 是统一屏障；主包、嵌套子包和 `.log.gz` 全部先展开到终态。
- 解压完成后构建一次任务级内存文件清单，不持久化、不复制文件。
- 清单只扫描七个 category 根目录，返回稳定排序、去重的 POSIX 相对路径。
- 链接、越界路径、非法 pattern 和路径穿越立即拒绝。
- 普通规则和 owner 私有 prepare 的输入必须来自同一个 `TaskFileCatalog`。

### 当前实现

实现位于：

- `app/services/extraction/`
- `app/services/scanning/catalog.py`
- `app/services/scanning/matcher.py`
- `app/services/executor.py`

关键机制：

- `Executor.run_all()` 在 `EXTRACT` 主包屏障和其余解压规则完成后调用 `ctx.ensure_catalog()`。
- `TaskFileCatalog.build()` 只扫描 `logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other`。
- `TaskFileCatalog.match()` 委托 matcher，对每个相对路径执行 `re.fullmatch()`。
- `RuleContext.resolved_files()` 通过 catalog 将相对路径解析到任务根内。
- 单规则重跑先确保 manifest 和 `.main/` 可复用，必要时重建主包现场，再构建 catalog。
- 策略跳过后的压缩项是 category 根下的最终文件，会进入 catalog；其内部成员不会进入 catalog。普通规则仍只依赖自身 `source_patterns[]`。
- 普通规则无匹配时，执行器可根据同 category 的 manifest 审计补充可读 `skip_reason`；规则本身不读取 manifest、策略对象或其他规则数据。

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

## 4. 日志过滤机制

### 当前实现

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

## 5. 日志服务与节点识别机制

### 当前实现

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

## 6. 堆栈识别机制

### 当前实现

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

## 7. 错误归一化机制

### 当前实现

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

## 8. 服务专属日志规则机制

### 当前实现

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

## 9. 日志状态判定约定

当前日志规则普遍遵循：

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
- 普通规则与隐藏规则（`pkg.extract.*` 解压族）统一注册；隐藏规则通过 `hidden=True` 区分。
- `GET /api/v2/inspectors` 默认 `include_hidden=False`，只返回普通规则；传 `?include_hidden=true` 可返回全部。
- 前端规则管理页（`InspectorsPage.tsx`）和任务详情页（`TaskDetailPage.tsx`）都通过 API 获取规则列表，不硬编码规则编码。
- 任务详情页使用 `hidden` 字段构建隐藏集合，从任务结果中过滤隐藏规则后再展示。

### 差异

当前无已知差异。新增规则时只需在 `app/inspectors/` 下创建模块并调用 `registry.register()`，API 和前端展示自动生效，无需修改展示层代码。

## 11. 后续迁移建议

为了收敛机制，建议后续按以下方向处理：

1. 新增规则必须只通过 `TaskFileCatalog` 接收 source_patterns 匹配结果。
2. 不为普通规则引入规则间 artifact 或 prepare 依赖。
3. 阈值继续收敛到可配置参数，并保持结果契约稳定。
4. 补充日志量大时的流式处理和内存边界测试。

## 12. KPI 指标公式与增量分类机制

### 目标设计

- 指标公式以声明式配置驱动，不在调度器或规则代码中硬编码。
- 派生指标通过 ratio 公式从原始指标计算得到，先汇总输入再算比率（sum-then-divide）。
- 增量分类通过任务快照隔离历史状态：任务执行时固化当时的指标目录，后续分类线索只读该快照，不使用数据库最新状态重写历史任务。
- 分类线索只读规则结果中记录的真实 CSV 列名，不引入规则间依赖。

### 当前实现

#### 公式配置

公式定义在 `deploy/data/kpi/rules/metric-rules.json`，每条指标通过 `source_type` 和 `formula` 字段区分：

```json
{
  "key": "me_call_success_rate",
  "source_type": "derived",
  "formula": {
    "kind": "ratio",
    "numerator": "me_call_success_count",
    "denominator": "me_call_attempts",
    "scale": 100,
    "denominator_fallback": null
  }
}
```

计算逻辑在 `app/inspectors/kpi/catalog.py` 的 `aggregate_kpi_metric()`：

- 先对所有记录中分子和分母的值做 `sum` 聚合，再算比率。
- 分母为 0 返回 `denominator_zero`，不产生值。
- 分子或分母数据缺失返回 `missing_input: <key>`，不产生值。
- 可选 `denominator_fallback` 列表提供分母回退输入。
- 结果附带 provenance（来源列名、回退是否触发）供审计。

#### 两个聚合层次

| 用途 | 范围 | 加法含义 |
|---|---|---|
| `main_value`（总览卡片） | 所有时间点全部记录 | 所有值加在一起再算比率 |
| `series`（趋势图每个点） | 单个时间窗口 `(start_at, end_at, period_minutes)` | 只加该时段内的值再算比率 |
| 逐行阈值检查 | 单条 CSV 记录 | 不加，直接用该行的值 |

#### 增量分类线索

任务执行时写出两个关键产物：

1. 规则结果 `output/<task_id>/rules/kpi.*.json` 的 `metadata.kpi_files` 记录 CSV 列名（`objects`）和样本值（`records[].values`）。
2. 配置快照 `output/<task_id>/kpi/kpi_catalog_snapshot.json` 记录执行时刻的 `base_metrics`（基础指标全集）和 `metrics`（已分配业务域的指标）。

调用 `GET /api/v4/tasks/{task_id}/kpi/classification-clues` 时，系统把 CSV 真实列名与快照中的指标目录逐个比对（归一化：NFKC + 去空白 + casefold），返回四种状态：

| 状态 | 含义 | 处理建议 |
|---|---|---|
| `classified` | 已匹配且已分配业务域 | 无需处理 |
| `unclassified` | 匹配到基础指标但未分配业务域 | 去数据库分配 domain |
| `ambiguous` | 匹配到多个基础指标 | 人工确认唯一指标 |
| `unregistered` | CSV 有此列但基础资源库没有 | 先离线导入基础指标 |

关键实现位于 `app/services/kpi_classification_clues.py`。

### 差异

当前无已知差异。新增派生指标时只需在 `metric-rules.json` 中声明 `source_type: "derived"` 和 `formula`，聚合逻辑自动生效。快照中缺少 `base_metrics` 字段的历史任务（schema 版本较低）所有线索都会显示为 `unregistered`，需重跑任务生成新快照。

## 13. SQLite 数据库文件使用注意

### 目标设计

SQLite 单文件数据库（`data/patrolx.db`）在程序空闲时可直接复制；程序运行中需使用 `sqlite3 .backup` 保证一致性。

### 当前实现

- 空闲时（API / CLI 均未运行）：直接 `cp data/patrolx.db <目标>` 即可。
- 运行中：使用 `sqlite3 data/patrolx.db ".backup <目标>"`，避免只拷主文件而丢失 journal/WAL 导致副本不一致。
- 迁移到其他机器或目录：拷贝后修改 `app/core/config.py` 中 `sqlite_path` 或环境变量即可。

### 差异

当前无已知差异。
