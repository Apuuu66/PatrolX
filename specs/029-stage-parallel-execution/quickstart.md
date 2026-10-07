# 快速验证：单包巡检阶段内并行执行

**前置条件**

1. 已执行 `python build.py install`，`.venv` 可用。
2. 基准包由仓库内脚本生成（不需要外部样例）：`python bench/parallel_bench.py --generate-only --out /tmp/patrolx-bench`
3. 目标机至少 4 个逻辑核；机器内存建议 ≥8GB（基准包并行峰值实测约 1.9GB）。

## 场景 1：自动化门禁

```bash
python build.py lint
python build.py test
python build.py verify
```

重点测试文件：

- `tests/test_executor_parallel.py`
- `tests/test_executor_parallel_faults.py`
- `tests/test_executor_parallel_policy.py`

## 场景 2：基准包串行 vs 并行提速（SC-001、SC-004）

```bash
python bench/parallel_bench.py --files 16 --rows 40000 --out /tmp/patrolx-bench
```

预期输出：

- `serial.rule_wall_s` / `parallel.rule_wall_s`：串行与 4 并行的 `PREPARE + INSPECT` 墙钟之和。
- `speedup`：`serial.rule_wall_s / parallel.rule_wall_s`，要求 `≥ 2.0`。
- `peak_rss_ratio`：基准脚本用后台采样线程 + `ps rss` 采集的**进程树真实并发峰值**之比，要求 `≤ 4 × 1.1`。
- `stages[]`：逐阶段 `mode` / `reason` / `workers` / `pending_units` / `matched_bytes` / `wall_ms` / `slowest_unit_ms`。

判定：`parallel.rule_wall_s ≤ serial.rule_wall_s × 0.5` 记为通过 SC-001。

**实测（2026-10-08 / M1 Pro / Python 3.12.14，`--files 16 --rows 40000`）**：

| 指标 | 串行基线 | 4 并行 |
| --- | --- | --- |
| 规则阶段墙钟 | 8.937s | 3.465s |
| INSPECT 阶段墙钟（8 单元，匹配 370MB） | 8180ms | 2726ms（`workers=4`、最慢单元 2144ms） |
| PREPARE 阶段（1 单元，匹配 46MB） | 757ms | 739ms（`units<3` 直通串行） |

`speedup = 2.58`，`sc001_pass = true`；进程树并发峰值 436.8MB → 1830.3MB、`peak_rss_ratio = 4.16`，在 SC-004 的 4 × 1.1 误差边界内。

两种内存口径必须区分：`stage_parallel_done.children_peak_rss_bytes` 是**各 worker 自身峰值之和**（本轮 3.42GB，会重复计入不同时活跃的 worker，用于单机排障），`peak_rss_ratio` 是基准脚本采样的**同时活跃进程树峰值**（SC-004 的判定口径）。

## 场景 3：任务级端到端验证

1. 把生成的基准包放入 `uploads/`。
2. 运行：

   ```bash
   python build.py run
   ```

   或直接跑本地 CLI 全流程（会扫描 `uploads/` 下全部数据包）：

   ```bash
   python main.py run
   ```

3. 打开 `output/<task_id>/execution.log`，确认出现：

   - `stage_parallel_start` / `stage_parallel_done`，其中 `mode=parallel`、`workers≤4`；
   - `stage_parallel_done` 中 `wall_ms` 明显低于串行基线；
   - 不存在 `parallel_degraded`（无故障场景）。

4. 打开 `output/<task_id>/rules/*.json`，规则结果与串行基线逐字段一致（`duration_ms`、`executed_at` 除外）。

## 场景 4：阶段屏障验证

1. 在同一份 `execution.log` 中定位 prepare 事件与第一条规则执行日志。
2. 预期：全部 prepare 事件（`prepare_cache_hit` / `prepare_cache_rebuild` / `prepare_skip`）都早于任何 `执行规则 <code>` 事件。
3. 预期：`pkg.extract.*` 相关日志全部早于任何 prepare 事件。

## 场景 5：故障注入

| 场景 | 注入方式 | 预期 |
| --- | --- | --- |
| prepare 失败 | 让测试用规则的 prepare 抛异常 | `prepare_error`；owner 规则 `skip`（原因“预处理未就绪”）；其他规则结果与无故障基线一致 |
| 规则异常 | 让测试用规则 `run` 抛异常 | 该规则 `error` 且带错误摘要；其他规则继续完成 |
| worker 崩溃 | 测试用规则调用 `os._exit(1)` | 该规则 `error`；出现 `parallel_degraded`；未完成单元降级为单进程顺序补跑（不重试、不再并行）；任务不失败 |

三种场景结束后都必须满足：`output/<task_id>/` 无残留子进程（`multiprocessing.active_children()` 为空），任务可通过既有重建/重跑能力恢复。

## 场景 6：单规则重跑语义不变（SC-005）

```bash
python build.py verify-one --rule log.fault_pattern
```

预期：

- 只有目标规则 JSON、`sys/task` 摘要与 HTML 报告被重写；
- 其他规则 JSON 的 mtime 与内容不变；
- 不创建进程池（该路径串行）。

## 场景 7：小任务不劣化（SC-007、FR-012）

1. 生成一个只有 1~2 条规则命中的小包（例如只含少量 KPI 文件）。
2. 串行基线（`ParallelPolicy.enabled = False`）与默认执行各跑一次。
3. 预期：默认执行不建池，总时长劣化 ≤10%，日志中对应阶段 `mode=serial`、`reason` 说明直通原因。

## 边界与验收清单

- [x] 4 并行度下 `execution.log` 每行可解析为 JSON，无交错（`tests/test_executor_parallel.py::test_execution_log_keeps_complete_json_lines_and_plan_order`）。
- [x] 并行执行不改变 `RuleResult` 字段、任务目录布局、报告内容（串并行逐字段比对用例；CLI/API 双模式比对用例）。
- [x] 任务结束后无残留子进程（成功、异常、主包失败三路径 `active_children() == []`）。
- [x] `verify-one` 只改动目标规则相关产物（`test_single_rule_rerun_never_builds_pool_and_preserves_other_results`，重跑期间禁用 `ProcessPoolExecutor` 也必须通过）。
- [x] 未命中并行的阶段（单元 < 3 或匹配字节 < 8MB）不产生池启动日志（`mode=serial` + `reason=units<3` / `matched_bytes<8MB`）。
- [x] 三类故障注入下任务仍完成，失败单元原因可解释，其余单元与无故障基线逐字段一致（`tests/test_executor_parallel_faults.py`）。
- [x] 本版不引入 prepare 共享消费、chunk 级并行、解压优化与跨任务并发（`app/inspectors/**` 零改动；放开 prepare 单规则使用限制列为本版本之后的独立版本）。

**门禁实测（2026-10-08）**：`ruff check` + `ruff format --check` 通过；`pytest` 全量 `550 passed`；`python build.py verify` 通过。
