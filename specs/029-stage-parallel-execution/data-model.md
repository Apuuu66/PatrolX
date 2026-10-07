# 数据模型：单包巡检阶段内并行执行

本功能不引入对外契约字段：`RuleResult`、`Metric`、`Finding`、`TaskSummary`、任务目录布局与 `docs/api/openapi.yaml` 全部保持不变。下面全部是执行器内部结构，仅用于串并行之间的数据搬运与验收断言。

## 1. 执行单元类型（UnitKind）

| 取值 | 含义 | 来源 |
| --- | --- | --- |
| `prepare` | 隐藏的规则私有预处理单元 | `registry.prepares()` |
| `inspect` | 普通巡检规则 | `registry.all()` 中非 hidden 且启用的规则 |

校验规则：

- 一个单元由 `(unit_kind, code)` 唯一确定；同一阶段内不允许重复出现。
- `prepare` 单元的 `owner_code` 必须等于注册表中该 prepare 的 owner；`inspect` 单元的 `owner_code` 等于自身 code。
- 单元集合与顺序由既有计划决定（`prepare_plan()` / `inspect_plan()`），并行不改变计划内容。

## 2. UnitPlan（父进程规划结果）

父进程在阶段开始前为每个单元生成一条规划项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `unit_kind` | `UnitKind` | 单元类型 |
| `code` | `str` | prepare code 或规则 code |
| `owner_code` | `str` | prepared 目录归属与 prepare 状态键 |
| `matched_files` | `list[str]` | 父进程用 `TaskFileCatalog` 匹配出的任务内相对路径（POSIX 分隔） |
| `matched_bytes` | `int` | 上述文件的字节总量，用于并行阈值判定与可观测 |
| `prepare_state` | `str \| None` | `HIT` / `REBUILT` / `SKIP` / `FAILED` / `None` |
| `short_circuit` | `RuleResult \| None` | 父进程直接产出的结果（无匹配 skip、prepare 未就绪 skip、缓存 HIT 无输出） |
| `needs_worker` | `bool` | 是否需要提交 worker 真正执行 |

校验规则：

- `short_circuit` 非空时 `needs_worker` 必须为 `False`。
- `prepare` 单元永不产生 `RuleResult`（prepare 不是普通规则结果）。
- `inspect` 单元的 `prepare_state == "SKIP"` 时短路为 `skip`，原因“未发现匹配源文件”；`== "FAILED"` 时短路为 `skip`，原因“预处理未就绪”（沿用现行语义）。
- `matched_files` 为空且规则声明了 `source_patterns` 时短路为 `skip`，并沿用现行的项目级解压策略补充说明。

## 3. UnitRequest（父进程 → worker 载荷）

`spawn` 要求载荷可 pickle，因此只传值、不传 `RuleContext`、注册表对象或日志函数。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `unit_kind` | `UnitKind` | 单元类型 |
| `code` | `str` | prepare code / 规则 code |
| `owner_code` | `str` | prepared 目录归属 |
| `task_id` | `str` | 任务标识，仅用于 worker 内上下文与日志 |
| `data_dir` | `str` | `output/<task_id>/` 绝对路径 |
| `prepared_dir` | `str` | `output/<task_id>/prepared/` 绝对路径 |
| `files` | `list[str]` | 已匹配的任务内相对路径 |
| `prepare_state` | `str \| None` | 该单元已知的 prepare 状态 |

校验规则：

- 所有路径字段必须是绝对路径字符串；`files` 必须是相对路径且不含 `..`。
- worker 不接收 `enabled_rules`、`LogFn`、`TaskFileCatalog` 或 `Inspector` 对象。

## 4. UnitOutcome（worker → 父进程载荷）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `unit_kind` | `UnitKind` | 回显单元类型 |
| `code` | `str` | 单元 code |
| `status` | `str` | `OK` / `CRASHED` |
| `result` | `RuleResult \| None` | `inspect` 结果；prepare 为 `None` |
| `prepare_state` | `str \| None` | prepare 执行后的状态（`REBUILT` / `FAILED`） |
| `logs` | `list[dict]` | worker 内 `ctx.log` 收集到的日志条目 |
| `duration_ms` | `int` | 单元自身执行耗时，不含排队（FR-010） |
| `worker_peak_rss_bytes` | `int` | worker 自身 `RUSAGE_SELF.ru_maxrss` 换算值 |

校验规则：

- `status == "CRASHED"` 由父进程在池失效/worker 退出时补写，不由 worker 自身返回。
- `inspect` 单元 `status == "OK"` 时 `result` 必须非空且 `result.code == code`。
- `prepare` 单元不得回传 `result`。
- `logs` 中每条必须是 `{"level": str, "message": str, "detail": dict}` 形态，可被既有 `execution.log` 行格式序列化。
- 父进程只信任父进程侧的规划数据：`execution_order`、落盘、`RULES_TOTAL` 自增都由父进程完成。

## 5. ParallelPolicy（并行策略）

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `max_workers` | `4` | 固定并行度，本版不暴露配置（FR-011） |
| `min_units` | `3` | 待执行单元少于此值时阶段直通串行 |
| `min_matched_bytes` | `8 * 1024 * 1024` | 匹配文件总字节低于此值时阶段直通串行 |
| `enabled` | `True` | 仅测试注入为 `False` 以生成串行基线 |

校验规则：

- `max_workers` 必须为正整数；实际池大小取 `min(max_workers, 待执行单元数)`。
- 该结构只作为 `Executor` 的构造参数存在，不进入 CLI 参数、环境变量、OpenAPI 或前端。

## 6. StageStats（阶段可观测）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `stage` | `str` | `PREPARE` / `INSPECT` |
| `mode` | `str` | `serial` / `parallel` / `degraded` |
| `reason` | `str` | 直通或降级原因（如 `units<3`、`matched_bytes<8MB`、`broker_broken`） |
| `workers` | `int` | 实际使用的 worker 数（串行为 0） |
| `pending_units` | `int` | 需要真正执行的单元数 |
| `matched_bytes` | `int` | 阶段内匹配文件字节总量 |
| `wall_ms` | `int` | 阶段墙钟（并行含池启动与结果回传） |
| `parent_peak_rss_bytes` | `int` | 父进程峰值 RSS |
| `children_peak_rss_bytes` | `int` | 子进程累计峰值 RSS |
| `slowest_unit_ms` | `int` | 阶段内最慢单元自身耗时 |

## 7. 状态迁移

单元执行状态（内部，不进入契约）：

```text
PLANNED ──short_circuit──▶ DONE(父进程产出结果)
   │
   └──needs_worker──▶ SUBMITTED ──OK──▶ DONE(worker 结果经父进程落盘)
                          │
                          └──CRASHED──▶ 该单元记 error；剩余 SUBMITTED 单元降级 SERIAL
```

prepare 状态（沿用现行契约不变）：

```text
matched 为空         → SKIP   （owner inspect 短路 skip）
marker 命中          → HIT    （不执行，owner inspect 正常读取 prepared）
marker 缺失/不一致   → REBUILT（worker 执行成功后由父进程写 marker）
worker/执行异常      → FAILED （owner inspect 短路 skip；其他单元不受影响）
```

## 8. 不变式

- `EXTRACT` 全部完成且主包成功，才允许出现任何 PREPARE 执行。
- 全部 PREPARE 完成（含 SKIP/FAILED 判定完成），才允许出现任何 INSPECT 执行。
- 同一任务同时活跃的 worker 数不超过 4。
- 任务结束后 `multiprocessing.active_children()` 为空。
- 串行与并行的单元结果除 `duration_ms` / `executed_at` 外逐字段一致。
