# 内部契约：执行器阶段内并行运行时

本契约描述 `Executor.run_all()` 与并行运行时（`app/services/parallel.py`、`app/services/unit_runtime.py`）之间的内部约定。它不是对外 API：`docs/api/openapi.yaml`、`RuleResult` 与任务目录布局均不因本契约变化。

## C1 阶段屏障

- 执行顺序固定为 `EXTRACT → PREPARE → INSPECT → 收尾`。
- `EXTRACT` 阶段与收尾阶段永不并行；主包 `pkg.extract.main` 失败时任务失败，不进入 PREPARE。
- 任一 INSPECT 单元开始执行前，全部 PREPARE 单元必须已结束（含 `SKIP` / `FAILED` 判定）；任一 PREPARE 单元开始前，全部 `pkg.extract.*` 必须已结束。
- 屏障不得因“并行更快”而被打破，包括降级路径。

## C2 并行度

- 同一任务同时活跃的 worker 进程数不超过 4；实际池大小为 `min(4, 待执行单元数)`。
- 不提供并行度配置入口（CLI 参数、环境变量、API 字段、前端设置均无）。
- 单元在阶段内的调度顺序不构成契约；结果顺序由既有计划序决定。

## C3 父进程单写者

- 只有父进程写 `output/<task_id>/execution.log`、`output/<task_id>/rules/*.json`、`sys/task/report` 等结果产物。
- worker 不写上述产物；worker 的 `ctx.log` 调用被收集为日志条目随结果回传。
- `prepared/<owner_code>/` 下的业务输出由 prepare 单元自身写入（与现状一致），但 `.prepare.sha256` marker 由父进程在收到成功结果后写入；失败时不写 marker。
- `RULES_TOTAL` 指标只由父进程自增；worker 内不得自增。

## C4 结果等价

- 串行路径与并行路径必须调用同一份单元执行实现（`UnitOutcome` 的产出逻辑只有一处）。
- 除 `duration_ms`、`executed_at` 等时间字段外，全部单元的状态、发现、指标、skip 原因、`metadata`、`execution_order`、任务摘要与报告必须逐字段一致。
- `duration_ms` 只包含单元自身执行时间，不含排队等待。
- 规则判定逻辑与 `rule_version` 不因并行而改变。

## C5 失败隔离

- 单个 prepare 失败：只把该 owner 的 inspect 置为 `skip`（原因“预处理未就绪”），其他单元继续。
- 单个规则异常：该规则记 `error` 并携带错误摘要，其他单元继续。
- worker 非正常退出（`BrokenProcessPool`）：该单元记 `error`（说明 worker 异常退出），已提交未完成的剩余单元在父进程降级串行执行；池不重建、不自动重试。
- 降级必须在 `execution.log` 留下 `parallel_degraded` 事件，包含原因与受影响单元数。

## C6 日志完整性

- `execution.log` 每行是一个完整 JSON 对象，不得出现跨进程交错或半行。
- 单元日志块按计划序写入（前缀 flush）；同一单元内部日志保持原始调用顺序。
- 并行执行不得让既有日志事件（`prepare_cache_hit`、`prepare_cache_rebuild`、`inspect_skip_no_match`、`规则 xxx 执行异常` 等）消失或改名。

## C7 可观测

- 每个阶段结束写 `stage_parallel_done`，字段见 `data-model.md` 的 `StageStats`。
- 峰值内存统一以字节记录；Linux（KB）与 macOS（字节）的 `ru_maxrss` 差异必须在本契约内归一化后才写入日志。
- 阶段事件只在阶段结束时写一次，不得按单元重复写。

## C8 资源回收

- 池的关闭发生在 `try/finally` 中，覆盖成功、异常、主包失败与降级路径。
- 关闭方式为 `shutdown(wait=True, cancel_futures=True)`。
- `run_all()` 返回后（无论成功或失败）不得存在本任务创建的残留子进程。

## C9 路径与隔离

- worker 只读取 `data_dir` 下 `UnitRequest.files` 指定的相对路径，以及自己的 `prepared/<owner_code>/`。
- worker 不得读取其他 owner 的 prepared 数据，不得修改原始上传包。
- `UnitRequest` 中不得出现任务目录之外的路径；`files` 中不得出现 `..` 或绝对路径。

## C10 不并行化的路径

- `verify-one` 单规则重跑（`run_rule_with_deps()`）保持串行，仅改动目标规则 JSON、任务摘要与报告。
- 全量/增量重建的执行入口不变，仅复用 `run_all()` 的并行行为。
- 单条规则内部执行不被拆分（无 chunk 级并行）。

## 验收对应

| 契约 | 对应用例 |
| --- | --- |
| C1 | 屏障用例：INSPECT 首条日志晚于全部 PREPARE 完成事件 |
| C2 | 并行度用例：并发 PID 峰值 ≤ 4 且 > 1 |
| C3 | 落盘用例：并行与串行的规则 JSON 除时间字段外一致；marker 只在成功后存在 |
| C4 | 等价性用例：串/并行全量逐字段比对 |
| C5 | 故障注入用例：prepare 失败、规则异常、worker `os._exit` |
| C6 | 日志用例：每行可解析、块内顺序稳定 |
| C7 | 可观测用例：阶段事件字段完整、单位换算正确 |
| C8 | 资源用例：任务结束后 `active_children()` 为空 |
| C9 | 隔离用例：worker 载荷路径校验与非法路径拒绝 |
| C10 | 重跑用例：`verify-one` 产物改动范围不变 |
