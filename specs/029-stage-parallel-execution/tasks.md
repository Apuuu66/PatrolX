---
description: "单包巡检阶段内并行执行 — 实现任务清单"
---

# 任务：单包巡检阶段内并行执行

**输入**：来自 `specs/029-stage-parallel-execution/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/executor-parallel-runtime.md、quickstart.md

**测试**：本清单包含测试任务；每个用户故事先写失败测试，再补实现（TDD）。

**组织方式**：按用户故事分组，每个故事可独立实现与验证。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件、无未完成依赖）
- **[故事]**：该任务所属用户故事（US1/US2/US3）

## 路径约定

仓库根目录：`app/`、`tests/`、`bench/`、`docs/`、`specs/`。所有实现与测试都在实现 worktree 内完成。

---

## 阶段 0：设置

**目的**：准备可复现的基准资产与测试脚手架，避免各故事重复搭建环境

- [ ] T001 [P] 在 `bench/parallel_bench.py` 中实现确定性基准包生成器：按 `--files/--rows/--seed/--out` 生成与真实包结构一致的 `logs/*.log` 目录并打包为 zip；同时提供 `--serial/--parallel` 对比运行、墙钟与峰值内存输出（SC-001、SC-004 的证据来源）
- [ ] T002 [P] 在 `bench/README.md` 中说明基准脚本用法、参数含义、结果解读与机器前提（≥4 逻辑核）
- [ ] T003 [P] 在 `tests/test_executor_parallel.py` 中搭建并行测试 helper：注册假 prepare/规则、构造临时任务目录与 `RuleContext`、捕获 `execution.log`、可注入 `ParallelPolicy`
- [ ] T004 [P] 在 `tests/test_executor_parallel_faults.py` 与 `tests/test_executor_parallel_policy.py` 中搭建故障注入与策略测试 helper（异常规则、`os._exit` 崩溃规则、命中/未命中并行的 fixture）

**检查点**：基准脚本可生成包并运行；新增测试文件可被 pytest 收集且当前失败。

---

## 阶段 1：基础层（阻塞全部用户故事）

**目的**：建立单元运行时、并行策略与执行器重构，串行行为零变化

- [ ] T005 在 `app/services/unit_runtime.py` 中新增 `UnitKind`、`UnitRequest`、`UnitOutcome`、日志条目结构与 `load_registry_once()` initializer；实现 `execute_unit(request)`：worker 内构造 `RuleContext`（`catalog=None`、`files` 来自请求）、只计时单元自身执行、规则异常在 worker 内捕获为 `error` 结果、prepare 异常返回 FAILED、日志写入收集器、返回自身 `ru_maxrss`
- [ ] T006 在 `app/services/unit_runtime.py` 中实现请求校验：路径必须绝对、`files` 必须为任务内相对路径且不含 `..`，非法载荷直接拒绝；并断言 worker 只能读取自身匹配文件与 owner 私有 prepared 目录，不得跨 owner 或跨规则读取（契约 C9、FR-007）
- [ ] T007 在 `app/services/executor.py` 中把 `run_one` 拆分为“父进程规划”（源文件匹配、prepare 状态短路、skip 原因组装）+“单元执行”（调用 `unit_runtime.execute_unit`）；串行路径与并行路径共用同一执行实现（契约 C4）
- [ ] T008 在 `app/services/parallel.py` 中新增 `ParallelPolicy`（`max_workers=4`、`min_units=3`、`min_matched_bytes=8MB`、`enabled=True`）与其默认常量；不接入 CLI/环境变量/API（FR-011）
- [ ] T009 在 `app/services/parallel.py` 中实现阶段并行运行时：`spawn` 上下文、`ProcessPoolExecutor(max_workers=min(4, 单元数))`、惰性创建并跨 PREPARE/INSPECT 复用、`finally` 中 `shutdown(wait=True, cancel_futures=True)`（契约 C2、C8）
- [ ] T010 在 `app/services/parallel.py` 中实现计划序收集与日志前缀 flush：worker 日志先入缓冲，父进程按计划序写入 `execution.log`；结果映射保持计划顺序（契约 C3、C6）
- [ ] T011 在 `app/services/parallel.py` 中实现 `BrokenProcessPool` 降级：崩溃单元记 error，剩余未完成单元在父进程串行执行，写 `parallel_degraded` 事件，不重建池（契约 C5）
- [ ] T012 在 `app/services/executor.py` 的 `run_all` 中接入并行：PREPARE 与 INSPECT 阶段改为“规划 + 并行运行时”；prepare 成功回传后由父进程写 `.prepare.sha256` marker；`RULES_TOTAL` 只由父进程自增；`EXTRACT` 与收尾保持串行（FR-003、FR-008）
- [ ] T013 在 `app/services/executor.py` 中实现阶段可观测：写 `stage_parallel_start` / `stage_parallel_done`（`stage`、`mode`、`reason`、`workers`、`pending_units`、`matched_bytes`、`wall_ms`、父子峰值 RSS、`slowest_unit_ms`），RSS 单位按平台归一化为字节（FR-015、契约 C7）
- [ ] T014 确认并断言 `run_rule_with_deps()`、`EXTRACT` 与收尾路径不经并行框架（契约 C10、SC-005）
- [ ] T015 在 `tests/test_executor_parallel.py` 中补充基础层回归：现有串行行为基线（`tests/test_executor.py`、`test_prepare_pipeline.py`、`test_prepare_cache.py`）必须全绿，且串行路径无进程池

**检查点**：执行器可在 `enabled=False` 与默认策略之间切换且结果一致；现有测试全绿。

---

## 阶段 2：用户故事 1 - 大包任务显著提速且结果不变（优先级：P1）🎯 MVP

**目标**：同一基准包并行执行，规则阶段墙钟 ≤ 串行 50%，且结果与串行逐字段一致。

**独立测试**：对同一临时任务用串行基线与 4 并行分别执行，比对全部单元结果、摘要与报告，并测量墙钟。

- [ ] T016 [US1] 在 `tests/test_executor_parallel.py` 中编写等价性失败测试：串行 vs 并行，逐字段比对状态、发现、指标、skip 原因、`metadata`、`execution_order`（时间字段除外），并断言 `duration_ms` 不含排队等待（FR-004、FR-010、SC-002）
- [ ] T017 [US1] 在 `tests/test_executor_parallel.py` 中编写阶段屏障测试：任一 INSPECT 执行日志晚于全部 PREPARE 完成事件，且全部 PREPARE 晚于 `pkg.extract.*` 完成（FR-003、契约 C1）
- [ ] T018 [US1] 在 `tests/test_executor_parallel.py` 中编写并行度测试：worker PID 峰值 >1 且 ≤4，单元数 <4 时池大小取实际数量（FR-001、FR-002、FR-011）
- [ ] T019 [US1] 在 `tests/test_executor_parallel.py` 中编写日志完整性测试：并行下 `execution.log` 每行可解析为 JSON、单元块内顺序稳定、不出现交错（FR-009、契约 C6）
- [ ] T020 [US1] 在 `tests/test_executor_parallel.py` 中编写可观测测试：`stage_parallel_done` 字段完整、`mode` 与直通原因正确、RSS 单位为字节（FR-015）
- [ ] T021 [US1] 运行 `bench/parallel_bench.py` 生成基准包并记录串行/并行墙钟与峰值内存，作为 SC-001、SC-004 证据；把实测结果补进 `specs/029-stage-parallel-execution/quickstart.md` 的参考量级
- [ ] T022 [US1] 依据基准结果校准 `ParallelPolicy.min_matched_bytes` 阈值（保持保守），并在 `specs/029-stage-parallel-execution/research.md` 中更新结论

**检查点**：等价性与屏障测试通过；基准显示 ≥2x 提速且峰值内存 ≤4× 串行。

---

## 阶段 3：用户故事 2 - 单执行单元失败被隔离（优先级：P1）

**目标**：prepare 失败、规则异常、worker 非正常退出都只影响该单元，任务继续完成。

**独立测试**：三类故障注入后检查其余单元结果与无故障基线一致，任务状态正常。

- [ ] T023 [US2] 在 `tests/test_executor_parallel_faults.py` 中编写 prepare 失败用例：owner 规则 `skip`（原因“预处理未就绪”）、其他规则结果与基线逐字段一致、marker 不写入（FR-005）
- [ ] T024 [US2] 在 `tests/test_executor_parallel_faults.py` 中编写规则异常用例：该规则 `error` 且带错误摘要，其他规则继续完成（FR-006）
- [ ] T025 [US2] 在 `tests/test_executor_parallel_faults.py` 中编写 worker 崩溃用例：`os._exit(1)` 所在规则记 error，出现 `parallel_degraded`，剩余规则降级串行完成（FR-006、契约 C5）
- [ ] T026 [US2] 在 `tests/test_executor_parallel_faults.py` 中编写资源回收用例：成功、异常、主包失败三条路径结束后 `multiprocessing.active_children()` 为空（FR-013、SC-006）
- [ ] T027 [US2] 补齐实现使上述用例通过；确认降级路径不产生结果重复、不丢日志事件

**检查点**：三类故障注入全部通过，任务仍可通过既有重建/重跑恢复。

---

## 阶段 4：用户故事 3 - 日常操作与单规则重跑语义不变（优先级：P2）

**目标**：CLI、API、`verify-one`、任务详情与报告行为与并行前一致；小任务不劣化。

**独立测试**：运行单规则重跑检查产物范围；并行下小任务与串行基线耗时差 ≤10%。

- [ ] T028 [US3] 在 `tests/test_executor_parallel_policy.py` 中编写小任务直通用例：1~2 个单元或匹配字节 <8MB 时不建池（无池启动日志、`active_children()` 为空），总时长劣化 ≤10%（FR-012、SC-007）
- [ ] T029 [US3] 在 `tests/test_executor_parallel_policy.py` 中编写重跑语义用例：`run_rule_with_deps()` 只改动目标规则产物、不创建进程池（SC-005、契约 C10）
- [ ] T030 [US3] 在 `tests/test_executor_parallel_policy.py` 中编写 CLI/API 双模式一致性用例：同一包两种模式结果一致（宪法“模式同构”）
- [ ] T031 [US3] 运行并确认既有测试全部通过：`tests/test_executor.py`、`test_prepare_pipeline.py`、`test_prepare_cache.py`、`test_rule_state_executor.py`、`test_robustness_execution.py`、`test_local_run.py`
- [ ] T032 [US3] 在 `tests/test_executor_parallel_policy.py` 中验证任务删除/BUSY 与重建路径不受并行影响（边界情况）

**检查点**：小任务不劣化、重跑范围不变、既有测试零回归。

---

## 阶段 5：收尾与交付

**目的**：文档同步、质量门禁与验收证据

- [ ] T033 [P] 在 `docs/architecture.md` 中同步执行编排章节：阶段内并行、固定并行度 4、父进程单写者、降级语义，并修正“第一版顺序执行 prepare”的表述
- [ ] T034 [P] 在 `docs/design/mechanisms.md` 中同步执行编排机制与阶段屏障关系
- [ ] T035 [P] 在 `AGENTS.md` 中同步执行编排约定：阶段内最多 4 进程并行、父进程单写者、单规则重跑不并行
- [ ] T036 运行 `python build.py lint` 并修复全部问题
- [ ] T037 运行 `python build.py test` 并确认全绿
- [ ] T038 运行 `python build.py verify`（涉及执行器与全流程）并确认通过
- [ ] T039 更新 `specs/029-stage-parallel-execution/tasks.md` 复选框与 `quickstart.md` 验收清单，记录最终基准数据与验证结论
- [ ] T040 检查最终 diff：本功能不得改动 `app/inspectors/**` 的规则判定逻辑、规则元数据与 `rule_version`（仅允许新增测试用假规则）（FR-018）

---

## 依赖关系

- 阶段 0 完成 → 阶段 1
- 阶段 1（T005~T015）完成 → US1、US2、US3 可并行推进
- US1（T016~T022）是 MVP：等价性与提速验证是本功能核心价值
- US2 依赖阶段 1 的降级实现（T011）与执行器接入（T012）
- US3 依赖阶段 1 的策略（T008）与重跑边界（T014）
- 阶段 5 依赖 US1~US3 完成

## 并行执行示例

```text
US1：T016、T017、T018、T019、T020 可在同一测试文件的不同测试函数上并行编写（注意文件冲突时串行合并）
US2：T023、T024、T025、T026 可在同一文件的不同用例上并行编写
US3：T028、T029、T030、T032 可在同一文件的不同用例上并行编写
收尾：T033、T034、T035 是不同文件，可并行
```

## 实现策略

1. **MVP**：阶段 1 基础层 + US1（等价性与提速），完成即可交付“大包显著提速且结果不变”。
2. **增量**：US2 补齐故障隔离，US3 保证既有行为与重跑语义不回退。
3. **验收证据**：`bench/parallel_bench.py` 输出串行/并行墙钟与峰值内存；pytest 覆盖等价性、屏障、故障注入、策略与资源回收。
