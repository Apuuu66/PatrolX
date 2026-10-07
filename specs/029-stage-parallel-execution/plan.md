# 实现计划：单包巡检阶段内并行执行

**分支**：`029-stage-parallel-execution` | **日期**：2026-10-08 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/029-stage-parallel-execution/spec.md` 的功能规格

## 摘要

在 `Executor.run_all()` 内部把 PREPARE 与 INSPECT 两个阶段改为“阶段内最多 4 个进程并行、阶段之间保留全局屏障”。执行编排仍是 `EXTRACT → PREPARE → INSPECT → 收尾`：解压与收尾保持串行，全部 PREPARE 完成后才允许任何 INSPECT 规则开始。

并行只搬运“执行”这件事：源文件匹配、skip 判定、prepare 缓存命中判定、结果落盘、日志落盘、指标自增全部留在父进程；子进程只负责执行单元函数并回传结果、日志条目与自身耗时。因此串行路径与并行路径共用同一份单元执行实现，FR-004 的逐字段一致不是靠测试兜底，而是靠结构保证。

小任务不启用并行：阶段内待执行单元少于 3 个、或匹配文件总字节低于阈值时，该阶段直接走串行，保证小任务劣化（FR-012、SC-007）为 0。并行只覆盖任务内阶段内；`verify-one` 单规则重跑、解压与收尾路径保持串行。

本版不改动宪法条文：宪法“轻量默认”已允许“后续引入并发，前提是不破坏契约或规则隔离”，本功能无外部依赖、无跨规则数据共享。放开 prepare 私有消费限制的后续版本才需要宪法 MINOR 修订。

## 技术上下文

**语言/版本**：Python 3.11+（仓库 `.venv` 为 3.12.x）

**主要依赖**：仅标准库 `concurrent.futures` 与 `multiprocessing`（`mp_context=spawn`）；不新增运行时依赖

**存储**：文件存储 + 在线模式 SQLite 元数据；本功能不新增存储结构、不改任务目录布局

**测试**：pytest（等价性、故障注入、策略阈值、残留进程）；`python build.py lint/test/verify`

**目标平台**：macOS 开发机（Python 3.12，默认 start method 为 `spawn`）+ Linux 容器部署；目标机至少 4 逻辑核

**项目类型**：离线巡检后端（FastAPI 在线模式 + 本地 CLI 模式），两模式共用执行器

**性能目标**：88MB / 16 日志文件 / ≥10 条规则的基准包，规则阶段墙钟相对串行基线下降 ≥50%（实测 2.7x 以上）；小任务劣化 ≤10%

**约束条件**：固定并行度 4 且不可配置；保留阶段屏障；结果与日志由父进程单写者落盘；并行不得引入规则间数据访问；不改变 `RuleResult` 契约与 rule_version

**规模/范围**：执行器阶段内并行 + 基准资产入库 + 执行契约文档同步；不改解压、不改单条规则内部逻辑、不做跨任务并发

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 处理 |
| --- | --- | --- |
| 离线优先 | 通过 | 并行只读取任务解压数据，不引入任何在线采集 |
| 一个包、一个任务 | 通过 | 并行范围限于单任务目录内；不新增目录身份，输出路径不变 |
| 契约驱动 | 通过 | 不改 OpenAPI、不改 `RuleResult`/`Metric`/`Finding` 字段语义；无接口变更，无需 `gen-web-api` |
| 模式同构 | 通过 | CLI 与 API 共用 `Executor.run_all()`，并行度、屏障与降级语义完全一致 |
| 巡检器插件架构 | 通过 | 并行调度基于注册表计划，不新增按规则名的分支，不硬编码业务规则 |
| 源文件显式匹配 | 通过 | `TaskFileCatalog` 匹配仍在父进程完成，worker 只消费父进程给出的匹配结果；无规则间导入或调用 |
| 增量重跑 | 通过 | `run_rule_with_deps()` 保持串行，单规则重跑语义与产物范围不变（SC-005） |
| 解压先行 | 通过 | `EXTRACT` 全部完成且主包成功后才进入 PREPARE，屏障保留 |
| 规则私有预处理 | 通过 | prepared 仍写入 `prepared/<owner_code>/` 且只被 owner 消费；本版不引入共享 prepared |
| 幂等与可追溯 | 通过 | 结果、报告由父进程按计划顺序落盘，顺序确定；重复执行结果等价 |
| 轻量默认 | 通过（需说明） | 宪法允许“后续引入并发，前提是不破坏契约或规则隔离”；本功能只用标准库进程池、不需要外部服务、不跨规则共享数据，符合该前提 |
| 容错 | 通过 | 单单元失败隔离；worker 非正常退出时该单元记 error，其余单元降级串行继续 |
| 安全解压 | 通过 | 不改动解压与路径校验逻辑 |
| 语言策略 | 通过 | 规格、计划、任务与文档均使用中文 |

**阶段 1 复查**：设计未引入新契约字段、新依赖、新目录层或规则间依赖，上述结论不变；不需要修订宪法版本。

## 阶段 0 研究结论

详见 [research.md](research.md)。关键决定：

- 并行边界用**进程**：规则是 CPU 密集的大文件解析，线程受 GIL 限制（实测约 1.00x）。
- 进程启动方式用 **`spawn`**：在线模式在线程里调用 `run_all()`，`fork` 在多线程进程中不安全且在 macOS 上不受支持；`spawn` 跨平台一致，实测 4 worker 启动 + 预热约 0.29s。
- 池按阶段**惰性创建并跨 PREPARE/INSPECT 复用**，任务结束在 `finally` 内 `shutdown(wait=True, cancel_futures=True)`；不引入常驻池。
- 并行前先在父进程完成“匹配 + skip/缓存命中判定”，只为真正需要执行的单元建池，小任务零开销。
- 小任务直通阈值：阶段内待执行单元 < 3 或匹配文件总量 < 8MB 时该阶段走串行。
- 父子协议只回传 `UnitOutcome`（结果 / 状态 / 日志条目 / 自身耗时 / worker 峰值 RSS）；`execution.log`、规则 JSON、摘要与报告由父进程单写者写出。
- 日志顺序取**计划序前缀 flush**：单元完成后先缓冲，父进程按计划顺序把已就绪前缀写入日志，块内保序、块间不交错。
- `BrokenProcessPool` 视为 worker 非正常退出：该单元记 error，剩余未完成单元**降级串行**执行，不重建池、不重试。
- FR-015 可观测口径：阶段事件记录 `stage`、`workers`、`mode(serial/parallel)`、`reason`、`wall_ms`、父子峰值 RSS 与最慢单元耗时；`ru_maxrss` 按平台换算为字节。

## 阶段 1 设计

### 1. 数据与模型

详见 [data-model.md](data-model.md)。全部为执行器内部结构，不进入对外契约：

- `UnitRequest`：单元执行载荷（单元类型、code、owner、任务上下文路径、相对匹配文件、prepare 状态）。
- `UnitOutcome`：单元执行结果（状态、`RuleResult`、日志条目、`duration_ms`、worker 峰值 RSS）。
- `UnitPlan`：父进程规划结果（计划序、可短路结果、是否需要提交 worker、匹配字节数）。
- `ParallelPolicy`：固定 4 进程 + 直通阈值；默认常量，仅测试可注入，不暴露给 CLI/API（FR-011）。
- `StageStats`：阶段可观测事件载荷。

### 2. 执行编排

- `EXTRACT`：保持现状，逐条串行；主包失败立即返回，不进入后续阶段。
- 屏障：`ctx.ensure_catalog()` 之后先完成 PREPARE 计划，再规划 INSPECT。
- `PREPARE`：父进程按 `owner priority → owner code → prepare code` 逐条做匹配与缓存判定；HIT/SKIP/FAILED 由父进程直接产出日志与状态，只有 REBUILT 提交 worker；成功回传后由父进程写 `.prepare.sha256` marker。
- `INSPECT`：父进程按 `priority → code` 逐条做匹配与 skip 判定；需要真正执行的规则提交 worker，`prepare_state ∈ {SKIP, FAILED}` 的规则由父进程直接产出 skip。
- 收尾：`run_all()` 返回前按计划顺序把结果写入 `self.collected`，`execution_order` 仍由既有 `assign_order()`/`plan()` 决定；`cli.run_task()` 的落盘循环不变。
- 单规则重跑 `run_rule_with_deps()` 完全保留串行实现，不经过并行框架。

### 3. 并行策略与降级

- 建池条件：`待执行单元数 ≥ 3` 且 `Σ 匹配文件字节 ≥ 8MB`；否则阶段内串行（同一执行函数）。
- 池：`ProcessPoolExecutor(max_workers=min(4, 待执行单元数), mp_context=spawn, initializer=load_registry_once)`。
- 收集：按计划序取 future 结果；任一单元异常只影响该单元（worker 内部已 try/except）。
- 池失效（`BrokenProcessPool`）：已提交未完成的单元按计划序改在父进程串行执行，并写 `parallel_degraded` 日志说明原因；已经完成的单元结果保留。
- 资源回收：`try/finally` 保证任务结束、异常或主包失败路径都关闭池；任务返回后 `multiprocessing.active_children()` 必须为空。

### 4. 可观测

- 新日志事件（`execution.log`）：`stage_parallel_start`、`stage_parallel_done`、`parallel_degraded`、`unit_parallel_error`。
- `stage_parallel_done` 记录 `stage`、`mode`、`workers`、`pending_units`、`matched_bytes`、`wall_ms`、`parent_peak_rss_bytes`、`children_peak_rss_bytes`、`slowest_unit_ms`。
- 事件由父进程写入，保持既有 `execution.log` 行格式（每行一个 JSON 对象）。

### 5. 兼容与边界

- 结果契约、任务目录布局、报告内容、`verify-one` 产物范围不变（SC-005）。
- 无匹配文件、prepare 未就绪、全部规则 skip 的场景必须与串行基线逐字段一致。
- 并行只影响规则阶段墙钟；`duration_ms` 只包含单元自身执行时间，不含排队（FR-010）。
- 任务运行期间的删除/BUSY 语义、KPI 快照与台账归档路径不变。
- 若后续放开 prepare 共享消费：本设计不构成阻碍（单元请求已按 owner 携带 prepared 路径），但该变更必须先改宪法与 prepare 契约，不在本版。

### 6. 测试设计

- 等价性：同一基准包分别以串行与并行执行，逐字段比对全部单元结果、摘要与报告（排除 `duration_ms`、`executed_at` 等时间字段）。
- 屏障：断言任一 INSPECT 日志时间戳晚于全部 PREPARE 完成事件。
- 并行度：断言并发峰值 worker 数 ≤ 4 且 > 1（用测试钩子在 worker 内记录 PID）。
- 故障注入：prepare 失败、规则抛异常、worker `os._exit` 崩溃三种场景下其余单元结果与无故障基线一致，崩溃单元为 error。
- 小任务直通：1~2 个单元的任务不建池（断言 `active_children()` 为空且无池启动日志）。
- 日志完整性：并行执行下 `execution.log` 每行可解析为 JSON，单元日志块内顺序稳定。
- 资源回收：任务结束后残留子进程数为 0。
- 基准脚本：生成确定性日志包并输出串行/并行墙钟与峰值内存，作为 SC-001/SC-004 的验收证据。

### 7. 交付验证

```bash
python build.py lint
python build.py test
python build.py verify
```

本功能不改 OpenAPI，无需 `python build.py contract` / `gen-web-api`；前端无变更。基准脚本单独运行作为性能证据（见 [quickstart.md](quickstart.md)）。

### 8. 文档同步（FR-017）

- `docs/architecture.md`：执行编排章节补充阶段内并行、固定并行度、父进程单写者与降级语义；修正“第一版顺序执行 prepare”的表述。
- `docs/design/mechanisms.md`：执行编排机制补充阶段内并行与屏障关系。
- `AGENTS.md`：执行编排约定补充并行语义（固定 4、阶段屏障、父进程单写者、单规则重跑不并行）。
- 不改 `docs/api/openapi.yaml`（无对外接口变更）。

## 项目结构

### 文档（本功能）

```text
specs/029-stage-parallel-execution/
├── plan.md                                   # 本文件
├── research.md                               # 阶段 0 输出
├── data-model.md                             # 阶段 1 输出
├── quickstart.md                             # 阶段 1 输出
├── contracts/
│   └── executor-parallel-runtime.md          # 执行器内部并行契约
└── tasks.md                                  # 阶段 2 输出（$speckit-tasks）
```

### 源代码（仓库根目录）

```text
app/
├── services/
│   ├── executor.py          # 阶段编排：规划、建池、收集、落盘、指标
│   ├── unit_runtime.py      # 新增：单元载荷、worker 入口、串并行共用的执行实现
│   └── parallel.py          # 新增：并行策略、池生命周期、降级与阶段统计
├── inspectors/
│   └── registry.py          # worker initializer 复用 load_all()，不改契约
└── cli.py                   # 保持调用点不变（run_all / run_rule_with_deps）

bench/
├── parallel_bench.py        # 新增：确定性基准包生成 + 串行/并行墙钟与内存对比
└── README.md                # 新增：基准脚本用法与结果解读

tests/
├── test_executor_parallel.py         # 等价性、屏障、并行度、日志顺序
├── test_executor_parallel_faults.py  # prepare 失败 / 规则异常 / worker 崩溃降级
└── test_executor_parallel_policy.py  # 小任务直通阈值、资源回收

docs/
├── architecture.md
└── design/mechanisms.md
AGENTS.md
```

**结构决策**：沿用 `api → services → inspectors/models` 分层。并行调度属于服务层（`app/services/`）；规则只提供 `run`/`prepare` 入口，不感知并行。worker 入口放在服务层模块内、以模块级函数暴露，保证 `spawn` 可 pickle。

## 复杂度跟踪

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 引入多进程执行（宪法“轻量默认”原本要求优先顺序执行） | 单任务规则阶段墙钟是核心体验瓶颈，实测 4 并行可缩短到 1/2.7，且宪法已允许“后续引入并发，前提是不破坏契约或规则隔离” | 线程池：实测 1.00x，GIL 下无收益；chunk 级并行：超出本版范围且需改规则内部实现；跨任务并发：用户已排除 |
| 新增 `app/services/unit_runtime.py` 与 `app/services/parallel.py` 两个服务层模块 | 单元执行实现必须被父进程串行路径与 worker 路径共用，池生命周期与降级逻辑需要独立可测边界 | 全部塞进 `executor.py`：串并行逻辑容易分叉，等价性只能靠测试兜底；用线程局部全局变量模拟隔离：不可测且错误 |
| 内部保留 `ParallelPolicy` 注入点 | 等价性与阈值测试必须能在同一进程内切换串行/并行 | 用环境变量切换：把测试开关暴露成运行时配置，违背 FR-011 的“本版不提供并行度配置项” |
