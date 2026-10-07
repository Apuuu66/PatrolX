# 基准资产：单包巡检阶段内并行

`parallel_bench.py` 生成与真实包结构一致的 `logs/**/*.log` 数据包，并在同一台机器上分别以
串行基线与默认 4 并行跑完整巡检，输出规则阶段墙钟、加速比与父子峰值内存。

脚本只读取本地生成的数据包：不连接被检系统、不访问 `uploads/`、不修改原始压缩包（每次运行前重建工作目录）。

## 用法

```bash
# 只生成数据包（快速验证/离线分析）
python bench/parallel_bench.py --generate-only --out /tmp/patrolx-bench

# 生成 16 个日志文件、每个 40000 行（约 88MB），跑串行 + 并行对比
python bench/parallel_bench.py --files 16 --rows 40000 --out /tmp/patrolx-bench

# 按 SC-001（并行墙钟 ≤ 串行基线 50%）判定退出码
python bench/parallel_bench.py --files 16 --rows 40000 --out /tmp/patrolx-bench --check
```

参数：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--files` | 16 | 生成的日志文件数 |
| `--rows` | 40000 | 单个日志文件行数（约 5.5MB/文件） |
| `--seed` | 20261008 | 内容随机种子；固定种子保证同一版本可复现 |
| `--out` | `/tmp/patrolx-bench` | 基准工作目录；生成包、解压现场与任务输出都收敛在这里 |
| `--generate-only` | 关 | 只生成数据包，不执行对比 |
| `--check` | 关 | SC-001 未达标时返回退出码 1 |

## 结果解读

JSON 关键字段：

- `serial.rule_wall_s` / `parallel.rule_wall_s`：`PREPARE + INSPECT` 两个阶段墙钟之和，
  不含解压与收尾（解压耗时不在本功能范围内）。
- `speedup`：`serial.rule_wall_s / parallel.rule_wall_s`。
- `*_peak_rss_bytes`：阶段事件中的父子峰值内存；并行峰值按父进程峰值 + 子进程累计峰值估算。
- `sc001_pass`：并行墙钟是否 ≤ 串行基线 50%。
- `stages[]`：每个阶段的 `mode` / `reason` / `workers` / `pending_units` / `matched_bytes` /
  `wall_ms` / `slowest_unit_ms`，用于确认直通（`units<3`、`matched_bytes<8MB`）与并行度。

参照量级（4 逻辑核以上机器、默认参数、16 文件约 88MB）：

- 串行规则阶段约 10~20s，4 并行约 4~7s，`speedup ≥ 2.0`。
- 并行度提高到 10 后墙钟不再下降（最慢单条规则构成下限），峰值内存却明显上升，因此固定 4 为本版产品决策。

## 机器前提

- 至少 4 个逻辑核；低于 4 核时并行收益不具代表性。
- 建议内存 ≥ 8GB：并行阶段峰值内存约为串行基线的 2~3 倍。
- 磁盘剩余空间：默认参数下单次运行约需 1GB（数据包 + 解压现场 + 任务输出）。
- 并行度、阈值与直通条件不可通过 CLI/环境变量配置，只由 `ParallelPolicy` 默认值决定。
