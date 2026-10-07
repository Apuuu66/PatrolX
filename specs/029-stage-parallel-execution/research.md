# 研究记录：单包巡检阶段内并行执行

本记录对应 [plan.md](plan.md) 阶段 0，解决“怎么并行、怎么保证等价、怎么不劣化”三类未知。

## 1. 并行边界：进程还是线程

**Decision**：用**进程**（`concurrent.futures.ProcessPoolExecutor`）执行阶段内并行；不用线程，也不用 asyncio。

**Rationale**：规则主体是日志/KPI 大文件的解析与统计，属于 CPU 密集任务，受 GIL 限制。实测同一基准包（88.8MB、16 文件、10 条日志规则）：串行 14.92s；线程池并行度 2/4/8 均约 1.00x，无加速；进程池 P=4 为 5.43s（2.75x）。进程还天然隔离每个单元的内存与崩溃，符合 FR-005/FR-006 的失败隔离要求。

**Alternatives considered**：

- 线程池：无加速（实测 1.00x），且共享内存导致结果解析失败的隔离更弱。
- asyncio：规则是同步阻塞 IO + CPU 混合代码，异步化需要重写规则，超出本版范围。
- 单进程内消息传递/协程：无法绕过 GIL，收益为零。

## 2. 进程启动方式：spawn / fork / forkserver

**Decision**：显式使用 `multiprocessing.get_context("spawn")`。

**Rationale**：

- 在线模式在 `TaskService` 的 worker 线程中调用 `run_all()`；`fork` 在多线程进程中不安全（子进程可能继承锁状态），Python 3.12 起在多线程进程中 fork 会给出 `DeprecationWarning`，macOS 上 fork 本身也不受支持。
- `spawn` 跨 macOS 与 Linux 行为一致，且不会继承父进程状态，避免“父进程已加载的规则注册表状态”被隐式带入 worker。
- 实测启动成本（4 worker + `registry.load_all()` 预热、M1 Pro / Python 3.12.14）：`fork` 0.25s、`forkserver` 0.25s、`spawn` 0.29s；主线程与线程内创建差异可忽略。成本差异不足以抵消 `fork` 的安全风险。

**Alternatives considered**：

- `fork`：启动略快 0.03s，但在多线程在线模式下不安全（见上）。
- `forkserver`：启动成本与 spawn 持平，跨平台行为不一致（Windows 不支持），统一用 spawn 更简单。
- 常驻预热池：会长期占用 4 个进程内存，违背“轻量默认”，且任务串行消费时无收益。

## 3. 池生命周期与复用

**Decision**：池按阶段**惰性创建**、在 PREPARE 与 INSPECT 之间**复用**，任务结束在 `finally` 中 `shutdown(wait=True, cancel_futures=True)`。

**Rationale**：固定开销实测约 0.3s，跨阶段复用时整任务只付一次；惰性创建保证小任务（直通串行）完全不付这个成本。不引入常驻池，避免空闲进程长期占用内存。

**Alternatives considered**：

- 每阶段各建一次池：多付一次启动成本，收益为零。
- 进程级常驻池（跨任务复用）：任务串行消费下省下的只是 0.3s，却要处理跨任务状态残留与崩溃恢复，收益不匹配复杂度。

## 4. 并行前的父进程规划

**Decision**：父进程先完成“计划序、源文件匹配、skip 判定、prepare 缓存命中判定”，只为**真正需要执行**的单元建池并把单元载荷发给 worker。

**Rationale**：`TaskFileCatalog` 匹配、manifest 读取与 skip 原因组装都依赖父进程已有状态，且成本低；把它们留在父进程可以避免每个 worker 重复构建目录清单，也避免把这类逻辑分叉成两份。worker 只做“执行”，串行路径与并行路径共用同一份实现，等价性由结构保证。

**Alternatives considered**：

- 把整个阶段计划下发给 worker：worker 需重复构建 `TaskFileCatalog`（大任务下是明显的重复开销），且 skip 语义需要两条实现。
- 让 worker 自己读注册表决定计划：与注册表解耦失败，且并行度、屏障校验无法在父进程集中验证。

## 5. 小任务直通阈值

**Decision**：阶段内**待执行单元 < 3** 或**匹配文件总字节 < 8MB** 时，该阶段整体串行执行，不建池。

**Rationale**：池固定开销约 0.3s，而基准包串行吞吐约 88.8MB / 14.9s ≈ 6MB/s；阈值 8MB 相当于“并行收益 ≈ 1.3s − 0.3s 固定开销”，留了约 4 倍余量。取“单元数 < 3 也直通”是为了覆盖规则多但都 skip/缓存命中的场景（此时无重活可并行）。FR-012 要求小任务劣化 ≤10%，直通串行时劣化为 0。

**Alternatives considered**：

- 恒建池：小任务要多付 0.3s；对秒级以内完成的小包，劣化比例远超 10%。
- 按规则数量估算耗时：规则耗时差异大（单条 4.45s ~ 0.05s），估算不可靠。
- 按压缩包大小估算：解压后规模与压缩比无关，且解压阶段串行时无法提前获得解压体积（`ctx.ensure_catalog()` 之后可直接拿到，本方案即采用解压后字节数）。

## 6. 父子协议与落盘顺序

**Decision**：worker 只回传 `UnitOutcome`（`RuleResult`、日志条目、自身耗时、worker 峰值 RSS）；父进程是 `execution.log`、规则 JSON、摘要与报告的唯一写入者。日志按“计划序前缀 flush”写入：单元完成后先入缓冲，父进程按计划顺序把已连续就绪的前缀写入。

**Rationale**：FR-008 要求单一写入者与稳定顺序；前缀 flush 让日志顺序与串行基线一致（可复现、易比对），同时避免等全部单元结束才写出日志。多个 worker 直接写同一日志文件会出现行交错与顺序漂移。

**Alternatives considered**：

- worker 直接 append 日志文件：无法保证块顺序，且违背 FR-008/FR-009。
- 完成序流式写入：可见性略好，但顺序不确定、串并行结果无法直接比对。
- 全部完成后统一写入：顺序正确但日志延迟最大。

## 7. 崩溃与降级

**Decision**：worker 内部异常由单元自身捕获并转为 `error` 结果；`BrokenProcessPool`（worker 非正常退出）视为该单元异常退出，剩余未完成单元在父进程**降级串行**继续执行，并写 `parallel_degraded` 日志。不重建池、不自动重试。

**Rationale**：`ProcessPoolExecutor` 在一个 worker 异常退出后整个池不可用；重建池会把 0.3s 成本叠加到故障路径，并且可能反复崩溃（损坏输入）。降级串行保证“其余单元继续完成”（FR-006）且行为确定。

**Alternatives considered**：

- 重建池重试：故障路径成本高、可能死循环，收益不确定。
- 整任务失败：违反 FR-006 与既有容错原则（单文件解析失败不得中断任务）。

## 8. 内存与阶段可观测（FR-015、SC-004）

**Decision**：阶段结束写 `stage_parallel_done` 事件，字段为 `stage`、`mode`、`workers`、`pending_units`、`matched_bytes`、`wall_ms`、`parent_peak_rss_bytes`、`children_peak_rss_bytes`、`slowest_unit_ms`。峰值内存用标准库 `resource.getrusage()`：`RUSAGE_SELF` 取父进程，`RUSAGE_CHILDREN` 取子进程累计峰值；Linux 的 `ru_maxrss` 单位是 KB、macOS 是字节，统一换算为字节后写入。

**Rationale**：不引入 `psutil` 等新依赖；`ru_maxrss` 是内核维护的峰值，读取成本为零。基准实测 P=4 峰值 1.9GB、P=10 峰值 4.2GB，用该口径可以复现并验证 SC-004。

**Alternatives considered**：

- `psutil`：依赖新增，收益与原语相同。
- 逐个 worker 采样 RSS：需要后台采样线程，与“父进程只做规划与落盘”的简洁边界冲突。

## 9. 基准资产形式（FR-016）

**Decision**：仓库内提供 `bench/parallel_bench.py`（确定性生成基准包 + 串行/并行墙钟与峰值内存对比），测试使用同源生成器的小规模参数。不入库大体积日志二进制。

**Rationale**：基准包按固定种子生成行数、文件数与记录分布，结果可复现且不污染仓库体积；自动化等价性测试复用同一生成器的小规模参数，保证“基准资产”与“回归测试”共用一套语义。

**Alternatives considered**：

- 提交 88MB 日志样例：仓库膨胀，且与“不修改原始上传包/轻量默认”方向不符。
- 依赖 `/tmp` 里的临时 spike 脚本：不可复现，无法作为验收证据。

## 10. 不纳入并行的路径

**Decision**：`EXTRACT` 阶段、收尾（结果落盘、摘要、报告、台账、KPI 快照）与 `verify-one` 单规则重跑保持串行；单条规则内部不做 chunk 级并行。

**Rationale**：解压是全局前置且 IO 密集，阶段屏障要求它先行；收尾是单写者路径；单规则重跑要保持最小改动范围（SC-005）。单条规则内部并行属于本版范围外，且用户已明确“不考虑单条规则耗时”。

**Alternatives considered**：

- 解压并行：用户已排除解压优化，且解压顺序与清单语义敏感。
- 单规则内 chunk 并行：需要改规则实现，收益不确定（最慢规则 4.45s 已是墙钟下限，但改造成本高）。
