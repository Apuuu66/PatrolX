# 快速验证：告警生命周期与闪断检测

**功能**：030-alarm-flapping ｜ **日期**：2026-10-09 ｜ **参考**：[data-model.md](data-model.md)、[contracts/alarm-flapping-result.md](contracts/alarm-flapping-result.md)

本指南用于在实现完成后端到端复现本功能，覆盖正常路径、边界路径与展示效果。所有命令在仓库根目录执行。

## 1. 前置条件

```bash
python build.py install          # 首次执行，创建 .venv 并安装依赖
python build.py lint
python build.py test
```

## 2. 生成代表性样例包并跑全量任务

样例包生成器新增 CLI 入口（同时保留 `build_real_package()` 供测试调用）：

```bash
.venv/bin/python tests/fixtures/make_real_package.py uploads
python build.py verify            # 等价于 .venv/bin/python -m app.cli run
```

**预期**：任务状态 `completed`；规则计划里包含 `alarm.flapping` 且状态为 `fail`；不再出现"告警文件被静默跳过"。

## 3. 核对结果 JSON

```bash
TASK=$(ls -t output | head -1)
.venv/bin/python - <<'PY'
import json, os
task = os.environ["TASK"]
data = json.load(open(f"output/{task}/rules/alarm.flapping.json", encoding="utf-8"))
meta = data["metadata"]["alarm_flapping"]
print("status:", data["status"], "| metrics:", {m["key"]: m["value"] for m in data["metrics"]})
print("coverage:", meta["coverage"])
print("state_counts:", meta["state_counts"])
for group in meta["groups"]:
    print(group["alarm_code"], group["object"], group["state"], group["occurrence_count"])
PY
```

**必须看到**（对应 SC-001、SC-002、SC-007、SC-008）：

| 分组 | 期望 |
| --- | --- |
| `SCTP_LINK_DOWN / umf-node-01`（alarm_id 1002） | `cleared_short`，`observation_gap_sec = 93900`（观察充足），不出现"稳定" |
| `1051 / pod-umf-9` | `uncleared_repeated`，`unrecovered_after_window = true`，Finding 为 CRITICAL |
| `1052 / pod-umf-9` | `cleared_repeated`（3 次出现、跨度 3000 秒），`min_repeat_gap_sec = 600`，`observation_insufficient = true`（清除距覆盖末端仅 330 秒），Finding 为 HIGH |
| `1050 / pod-umf-9` | `cleared_stable`；`out_of_window_occurrences >= 1` 且 `out_of_window_reappear = true`，主状态不因操作窗降级 |
| `1053 / pod-umf-9` | `observation_insufficient`，持续 330 秒、`observation_gap_sec = 0`，不出 Finding |
| `AUTH_FAILURE_BURST / umf-node-01`、`SERVICE_UNAVAILABLE / csp-node-01` | 已清除且观察窗充足，不出 Finding |
| `CONTAINER_RESTART / pod-csp-1`（alarm_id 1009） | `cleared_stable`，`observation_gap_sec = 92480`，零 Finding |

指标核对：`alarm_groups == 17`、`flapping_groups == 2`、`uncleared_repeated_groups == 1`、`short_alarm_groups == 1`、`stable_groups == 5`、`observation_insufficient_groups == 11`、`out_of_window_groups == 1`、`unrecovered_after_window_groups == 1`、`excluded_rows == 0`、`duplicate_rows == 0`、`failed_files == 0`；Finding 共 3 条（CRITICAL / HIGH / MEDIUM 各一）。`stable_groups` 计主状态为 `cleared_stable` 的分组；`observation_insufficient_groups` 计携带观察窗不足标记的分组（含 9 个未清除分组 + 1052 + 1053，共 11 个），两者口径不同。

## 4. 单规则重跑一致性（SC-006）

```bash
python build.py verify-one --rule alarm.flapping
```

**预期**：`output/$TASK/rules/alarm.flapping.json` 的 `status`、`metrics`、`findings`、`metadata.alarm_flapping` 与第 3 步逐字段一致（`executed_at`、`duration_ms` 除外）；`alarm.stat.json` 与其他规则结果时间戳不变。

## 5. 阈值变更后重跑（US4）

临时把 `flapping.py` 中的复发次数阈值默认值（`FlappingPolicy` 的 `min_repeat_count`）改为 `4`，执行：

```bash
python build.py verify-one --rule alarm.flapping
```

**预期**：`1051`、`1052` 都只有 3 次出现，低于新阈值 4：`1051` 从 `uncleared_repeated` 变为 `uncleared_single`，`1052` 从 `cleared_repeated` 变为 `observation_insufficient`（清除距覆盖末端仅 330 秒）；规则状态从 `fail` 降为 `warn`，CRITICAL 与 HIGH Finding 消失，Finding 数从 3 降到 1（仅剩 `SCTP_LINK_DOWN / umf-node-01` 的 MEDIUM）。恢复默认值（`3`）后重跑必须回到第 3 步结果。

> 本版阈值通过规则参数表声明、无运行时配置面；验证方式就是改默认值后单规则重跑，结论可解释、可追溯。

## 6. 数据不足与容错

用内联 fixture（`tests/test_alarm_flapping.py`）覆盖并断言：

| 场景 | 期望 |
| --- | --- |
| 无告警文件 | `skip` + 非空 `skip_reason` |
| 全部行时间不可解析 | `skip` + `skip_reason` 说明被排除行数 |
| 部分行时间坏 / 时钟倒挂 | `excluded_rows > 0`，其余分组正常判定，任务不失败 |
| 同一去重键重复行 | `duplicate_rows > 0` 且只计一次 |
| 单个 CSV 解析失败 | `failed_files > 0`，其他文件结果不受影响 |
| `object` 缺失 | 归入空对象分组并保留记录 |
| TXT 与 CSV 混合 | 合并排序后统一判定 |
| 多日数据跨操作窗 | 按记录所在自然日分别归属窗口内/外 |

## 7. 展示效果核对（SC-005、SC-008）

```bash
python build.py run
```

- 规则详情页：`/tasks/$TASK/rules/alarm.flapping`，新增"告警生命周期分组"面板，30 秒内可区分"反复闪断 / 单次短告警 / 仍未恢复 / 稳定恢复"四类；顶部 Finding 列表能看到 CRITICAL/HIGH/MEDIUM 三条证据。
- HTML 报告：`output/$TASK/report/report.html`（或任务详情"报告"页）能直接看到闪断 Finding 与阈值证据。
- 前端回归：`python build.py web-build` 与对应 E2E（`web/e2e/` 中断言分组面板可见）。

## 8. 交付验证

```bash
python build.py lint
python build.py test
python build.py verify
python build.py web-build
```

**预期**：全部通过；`alarm.stat` 的既有断言（总量、未处理、严重级分布，按新增样例调整后的数值）保持一致语义，仅数值随样例包扩充更新。本功能不改 `docs/api/openapi.yaml`，无需执行 `python build.py contract` / `gen-web-api`；若实现阶段需要新增对外字段，必须先补契约再实现。
