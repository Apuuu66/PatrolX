# 数据模型：规则私有预处理与轻量缓存

## 1. 实体关系

```text
InspectionTask 1 ── N PrepareRun
InspectionTask 1 ── N PreparedData
InspectRule 1 ── 0..1 PrepareSpec
PrepareSpec 1 ── 0..1 PreparedData
PrepareSpec 1 ── 0..1 PrepareCacheMarker
```

- `InspectRule` 是对外展示的普通巡检规则。
- `PrepareSpec` 是隐藏基础设施单元，不是普通巡检规则。
- `PreparedData` 只属于一个任务和一个 owner 规则。
- prepare 不对外生成 `RuleResult`，也不进入任务摘要的规则列表。

## 2. Inspector 扩展

### Inspector

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source_patterns` | `list[str]` | 普通规则必填 | Python regex；以 `re.fullmatch()` 匹配 `output/<task_id>/` 下 POSIX 相对路径 |
| `prepare` | `PrepareSpec \| None` | 否 | 规则私有预处理声明 |

既有 `inputs`、`outputs_artifacts` 保留用于当前 extract / 未迁移规则兼容；prepare 不新增公共 artifact key。

### PrepareSpec

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | `str` | 是 | 隐藏 prepare 代码，建议 `pkg.prepare.<owner_code>` |
| `owner_code` | `str` | 是 | 必须等于声明它的 `Inspector.code` |
| `run` | `Callable` | 是 | prepare 执行函数，由框架传入任务上下文和 owner prepared 目录 |

约束：

- 一个 `InspectRule` 最多拥有一个 prepare。
- `PrepareSpec.code` 必须全局唯一。
- `PrepareSpec.owner_code` 必须唯一且指向存在的 inspect 规则。
- prepare 不声明 outputs、priority、severity 或 recommendation。
- prepare 的执行优先级和 `source_patterns` 均继承 owner。
- source patterns 统一使用 `re.fullmatch()`；路径分隔符归一为 `/`，并拒绝任务目录逃逸。
- 既有解压目录保持现状，例如 `logs/`、`kpi/`；不引入 `data/` 迁移。

## 3. PreparedData

| 属性 | 说明 |
| --- | --- |
| 任务隔离 | 根目录为 `output/<task_id>/prepared/` |
| owner 隔离 | 子目录为 `output/<task_id>/prepared/<owner_code>/` |
| 内容 | 由 prepare 自行决定，不要求统一 manifest 或 schema |
| 生命周期 | prepare 重建前清空 owner 目录；任务删除时随任务目录级联删除 |
| 消费者 | 只有 owner inspect 规则可读取 |
| 展示 | 不写入规则结果 JSON，不出现在前端规则列表 |

### 首批样例数据

| owner | prepared 文件 | 用途 |
| --- | --- | --- |
| `kpi.threshold` | `kpi_values.json` | 保存从 KPI CSV/TXT 归并出的 metric/value |
| `log.app_service` | `app_service_records.jsonl`、`source_files.json` | 保存 AppService 相关规范化日志记录和来源文件 |

文件名是实现建议，不构成 prepared 输出声明契约；框架不校验这些文件是否存在。

## 4. PrepareCacheMarker

| 属性 | 值 |
| --- | --- |
| 路径 | `output/<task_id>/prepared/<owner_code>/.prepare.sha256` |
| 内容 | 当前 owner 规则代码文件内容 SHA-256 |
| 命中条件 | marker 存在且内容与当前规则文件 SHA-256 一致 |
| 重建条件 | marker 不存在，或内容不一致 |
| 成功写入 | prepare 成功后由框架写入 |
| 失败写入 | 不写入 |
| 目录删除 | owner prepared 目录删除后 marker 自然消失，下一次重建 |

## 5. PrepareRun 状态

| 状态 | 含义 | owner inspect 后续动作 |
| --- | --- | --- |
| `HIT` | marker 命中，复用 prepared | 执行 owner inspect |
| `REBUILT` | marker 未命中，重新执行 prepare 后成功 | 执行 owner inspect |
| `SKIP` | 无匹配输入或数据不适用 | owner inspect 显式 `skip` |
| `FAILED` | prepare 执行异常 | owner inspect 显式 `skip`，原因说明预处理未就绪 |

## 6. 主流程状态

| 阶段 | 进入条件 | 失败语义 |
| --- | --- | --- |
| `EXTRACT` | 任务开始 | 主包失败则任务失败；category 失败记录为 warning/error |
| `PREPARE` | extract 阶段完成且主包成功 | 单个失败不阻断其他 prepare |
| `INSPECT` | prepare 阶段完成 | 单个规则失败不阻断其他规则 |

## 7. 执行排序

### Prepare 阶段

```text
(owner.priority, owner.code, prepare.code)
```

### Inspect 阶段

```text
(rule.priority, rule.code)
```

排序只用于执行顺序和执行编号，不建立规则依赖关系。

## 8. 日志事件

| 事件 | 必要字段 |
| --- | --- |
| `prepare_cache_hit` | task_id、owner_code、prepare_code |
| `prepare_cache_rebuild` | task_id、owner_code、prepare_code |
| `prepare_skip` | task_id、owner_code、prepare_code、skip_reason |
| `prepare_error` | task_id、owner_code、prepare_code、error |
| `inspect_skip_prepare_not_ready` | task_id、owner_code、prepare_code、skip_reason |

日志必须进入任务执行日志；不要求暴露新的 API 字段。
