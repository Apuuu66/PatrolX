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

### 当前实现

实现位于 `app/inspectors/pkg.py`。

- `pkg.extract.main`：
  - 解压主包到 `.main/` 证据现场。
  - 调用共享解压服务，按 `deploy/config/classify_rules.yaml` 和内容特征递归分类。
  - 生成只包含最终文件的分类工作现场，并写入 `.patrolx-extracted.json` manifest v3。
- `pkg.extract.<category>`：
  - 汇总 manifest 中对应分类的子包与 `.log.gz` 终态。
  - 失败或冲突时返回 `warn`，不阻断其他规则。
- 解压规则均为 `hidden=true`，优先级为 `P0`。

### 差异

- 目前日志过滤通过 `source_patterns` 直读最终 `.log`；`.main/` 只作为证据现场，不进入规则匹配。
- 文档和红线期望普通规则通过 `source_patterns` 匹配文件；当前部分规则仍以 artifact 依赖为主，尚未全面迁移。

## 2. Artifact 依赖机制

### 目标设计

- 规则之间不直接导入、实例化或调用。
- 规则可以通过显式 artifact 表达数据依赖。
- artifact 必须记录生产者规则、生产者版本和路径。
- artifact 只能由唯一规则生产。
- 执行器负责在依赖缺失或版本过期时补跑生产者。
- 依赖优先级必须保证生产者优先于消费者执行。

### 当前实现

实现位于：

- `app/services/executor.py`
- `app/services/artifacts.py`
- `app/inspectors/registry.py`

关键机制：

- `Inspector.outputs_artifacts[]` 声明产出。
- `Inspector.inputs[]` 声明消费。
- `ArtifactStore` 使用 `.artifacts.json` 记录 artifact 元数据。
- `ArtifactStore.valid()` 校验：
  - artifact 存在；
  - producer rule code 一致；
  - producer `rule_version` 一致。
- `Executor.plan()` 按 priority 分组执行，并在同优先级内按依赖拓扑排序。
- `Executor.run_rule_with_deps()` 会补跑缺失或版本过期的依赖。

### 差异

- artifact 机制已经落地，但和 AGENTS.md 中“规则只读取自己的 `source_patterns` 匹配文件”的模型并存，需要明确迁移边界。
- 不应把普通规则间的 artifact 依赖当作长期设计；可保留基础设施规则产出数据的模式，普通规则之间的消费关系仍需收敛。

## 3. `source_patterns` 机制

### 目标设计

- 普通规则声明 `source_patterns[]`。
- pattern 使用正则语义，执行器用完整匹配匹配任务输出目录内的相对路径。
- 路径分隔符统一为 `/`。
- 规则只能读取匹配到的文件，不得直接依赖其他规则实现。
- 无匹配文件、格式不适用或解析失败时返回 `skip` 和非空 `skip_reason`。

### 当前实现

- `Inspector` 数据类尚未定义 `source_patterns[]` 字段。
- 当前日志规则主要通过 `log.filter` artifact 获取数据。
- 解压规则通过分类目录和隐藏规则准备数据。
- 测试中已有按类别目录构造输入的用例，但没有统一的 source pattern 执行路径。

### 差异

这是当前最明显的机制差异：

| 主题 | 期望 | 当前 |
| --- | --- | --- |
| 数据来源 | 规则声明 `source_patterns[]`，由执行器匹配 | 部分规则依赖前置规则 artifact |
| 规则耦合 | 不依赖其他规则实现 | 下游日志规则依赖 `log.filter.artifacts.filtered_logs` |
| 无匹配文件 | 返回 `skip` | 当前多数规则可以跳过，但匹配机制未统一 |
| 路径边界 | 执行器统一控制 | 尚未完整落地 |

## 4. 日志过滤机制

### 当前实现

实现位于 `app/inspectors/log/filter.py`。

`log.filter` 是 P0 日志规则，负责把原始日志转换为规范化 artifact。

输入：

```text
output/<task_id>/log/**/*.log
output/<task_id>/log/**/*.log.gz
```

输出：

```text
artifacts/log.filter/log.filter.artifacts.filtered_logs/
├── filtered.jsonl
├── filtered.log
└── index.json
```

处理逻辑：

1. 扫描 `ctx.data_dir / "log"` 下的 `.log` 和 `.log.gz` 文件。
2. 按目录结构推导服务名和节点名：
   - 去掉 `ServiceLog_*` 前缀目录；
   - 忽略 `log` / `logs` 目录名；
   - 如果没有目录信息，则用文件名去掉 `.log` / `.log.gz` 作为服务名。
3. 使用正则解析标准日志行：

   ```text
   timestamp LEVEL message
   ```

4. 只保留 `WARN` / `WARNING` / `ERROR` / `FATAL` / `CRITICAL`。
5. 错误级日志后的无法独立解析的连续非空行标记为 `STACK`。
6. 单个文件读取失败只记录 warn，不中断整个任务。
7. 无日志文件时返回 `skip`。

### 差异

- `params` 中声明了 `min_level`，但实际使用硬编码：

  ```python
  MIN_LEVEL = 30
  ```

- `index.json` 的 `files[]` 来自扫描到的文件列表，不一定全部成功解析。
- `filtered.jsonl` 是中间产物契约；长期是否保留需要结合 `source_patterns` 机制重新评审。

## 5. 日志服务与节点识别机制

### 当前实现

规则通过目录结构识别服务与节点：

```text
log/ServiceLog_<timestamp>/<service>/logs/<node>/<file>.log.gz
```

处理策略：

- 忽略 `ServiceLog_*` 目录。
- 忽略 `log` / `logs` 目录。
- 第一个剩余路径段作为 `service`。
- 其余路径段拼接为 `node`。
- 没有目录信息时，用文件名作为服务名。

示例：

```text
log/ServiceLog_20260901011314/AAAService/logs/paas-192.168.2.2/aaa_service_20260901011314.log.gz
```

会被识别为：

```text
service = AAAService
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
- `log.stacktrace` 会读取 `filtered.jsonl`：
  - 统计 `STACK` 行；
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

- `log.aaa_service` 只处理 `service == "AAAService"`。
- `log.app_service` 只处理 `service == "AppService"`。

这些规则仍然依赖 `log.filter` 的规范化 artifact。

| 规则 | 匹配方式 | 判定 |
| --- | --- | --- |
| `log.aaa_service` | 文本包含 `auth failure` / `retry timer exceeded` | 任一类命中数 `>= 3` 时 `fail` |
| `log.app_service` | 文本包含 `connection pool exhausted` 或包含 `sctp` | 连接池 `>= 2` 或 SCTP `>= 3` 时 `fail` |

### 差异

- 服务名目前是硬编码常量。
- 匹配条件主要是字符串包含，不是显式配置化模式。
- 服务和错误类型的扩展目前需要改代码；长期更适合由规则配置或模式声明驱动。

## 9. 日志状态判定约定

当前日志规则普遍遵循：

- 无依赖 artifact：`skip`
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

## 10. 后续迁移建议

为了收敛机制，建议后续按以下方向处理：

1. 为 `Inspector` 增加 `source_patterns[]` 字段，并由执行器统一匹配文件。
2. 明确 artifact 机制只允许基础设施或显式前置准备使用，避免普通规则之间形成实现级依赖。
3. 将日志规则逐步迁移到 `source_patterns`，让规则只声明自己关心的日志文件。
4. 如果保留 `log.filter`，应将其定位为显式的基础设施规则，而不是普通业务规则。
5. 将阈值从代码常量迁移到可配置参数，并保持结果契约稳定。
6. 补充日志量大时的流式处理和内存边界测试。
