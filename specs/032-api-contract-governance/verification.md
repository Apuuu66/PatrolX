---
spec: 032-api-contract-governance
branch: feature/032-api-contract-governance（已 fast-forward 合入 main）
worktree: .worktrees/feature-032-api-contract-governance（2026-10-10 已清理）
verified_at: 2026-10-10
---

# 实现回合验证记录：API 契约治理与持续集成门禁（批次 A）

## 一、前置检查

```text
$ git worktree list
/Users/yigui/code/PatrolX                                                 8c3edf9 [main]
/Users/yigui/code/PatrolX/.worktrees/feature-032-api-contract-governance   a88ddc1 [feature/032-api-contract-governance]
/Users/yigui/code/PatrolX/.worktrees/feature/030-alarm-flapping            3a41dfa [feature/030-alarm-flapping]
/Users/yigui/code/PatrolX/.worktrees/feature/033-ui-refinement             893e120 [feature/033-ui-refinement]

$ git branch --show-current
main
```

- 实现分支 `feature/032-api-contract-governance` 的全部提交均为 `main` 祖先（`git merge-base --is-ancestor a88ddc1 main` 成立），合入为 fast-forward，合入后被测代码树与验证时一致，按宪法不重复跑全量验证。
- 本回合在 `main` 只做收尾物：`tasks.md` 勾选、`verification.md` 记录、`.github/workflows/ci.yml` 与 `contracts/ci-gate.md` 的退出码/失败诊断修正；未改 `app/`、`tests/`、`docs/api/openapi.yaml`、`web/src/**`。
- 校验期间主工作区存在**另一会话的未提交改动**（`web/src/components/MeasurementTrendChart.tsx`、`web/e2e/seed_kpi_measurement_history.py` 及两个新增文件），不属本批次、未纳入本次提交；第四节的门禁命令在该工作区状态下执行，因此 e2e 计数为 35（含其新增用例）。

## 二、交付提交

| 提交 | 主题 |
| --- | --- |
| `d597ac9` | 收敛任务创建入口到 v3 并同步契约客户端 |
| `ae5f09b` | 契约治理守卫与创建入口用例迁移 |
| `87424d3` | 增加后端与前端最小门禁（`.github/workflows/ci.yml`） |
| `a88ddc1` | 同步规格状态与当前 KPI 测量单元文档 |
| `a9736b5`、`8c3edf9` | 测试失败时回显日志摘要（诊断钩子） |
| 本回合 | 修复 CI 管道退出码、保留失败诊断并记录合入验证 |

## 三、合入验证（T033，主工作区 `main`）

| 命令 | 结果 |
| --- | --- |
| `python3.12 build.py lint` | `All checks passed!` + `181 files already formatted` |
| `python3.12 build.py test` | `581 passed, 3 warnings in 39.39s`（总耗时 39.9s，上限 120s） |
| `python3.12 build.py contract` | `契约与实现一致: OK` |
| `python3.12 build.py web-build` | `tsc -b && vite build` 成功（`✓ built in 4.66s`） |
| `python3.12 build.py e2e` | `35 passed (27.2s)` |

- 首轮 `e2e` 曾失败：并发会话的 e2e 服务占用了 8010/5183（先命中陈旧后端、后 `address already in use`），端口释放后复跑全绿。属环境竞争，非产品缺陷。
- 上一回合在主工作区 `main`（`8c3edf9`）已跑过同一组门禁：`lint` 181 files、`test` 581 passed、`web-build` OK、`e2e` 34 passed；本回合仅在其上叠加 `ci.yml` 与规格文档修正。
- quickstart 场景 1–4 已在实现回合（T030）复现并修正场景 2 的误判断言；本回合只复跑门禁命令。

## 四、CI 门禁的退出码与失败诊断（本回合修正）

1. **真实缺陷**：诊断钩子写成 `cmd 2>&1 | tee /tmp/x.log`。GitHub Actions 未指定 `shell` 时按 `bash -e {0}` 运行（无 `pipefail`），管道退出码取 `tee`，测试失败会被吞掉并静默通过 —— 违反 FR-020「任一检查失败必须使门禁失败，且不得静默跳过检查」。
2. **修正**：测试与单测步骤显式 `set -o pipefail`；失败诊断步骤保留并明确为只读回显（`grep -m5` 失败用例名 + `tail -n 30` 日志末尾，逐行 `::error::`）。
3. **本地复现与验证**（用 `ci.yml` 中真实步骤脚本 + 假失败命令，在 runner 同款 `bash -e` 下执行）：

| 场景 | 旧写法 | 新写法 |
| --- | --- | --- |
| 测试命令退出 1 | 步骤退出码 0（失败被吞） | 步骤退出码 1（门禁变红） |
| 失败诊断步骤 | 无 | 退出码 0；输出 19 行（后端）/16 行（前端）`::error::`，前 3 行为失败用例名与断言 |
| 日志文件缺失 | — | 退出码 1（暴露缺失，不静默跳过） |

4. **可诊断性**：`::error::` 回显在 check-run 上形成注解，注解可通过公开 API 读取（已验证本仓库 `GET /repos/Apuuu66/PatrolX/check-runs/{id}/annotations` 无凭据可读），因此下次 CI 失败可直接定位失败用例，无需 Actions 日志权限。
5. **契约同步**：`contracts/ci-gate.md` 增补每个 job 的「失败诊断」步骤行与「退出码与失败诊断」小节，保持 quickstart 场景 5「步骤与契约一致」成立。

## 五、CI 偶发失败（2026-10-10 已闭环）

| 运行 | 提交 | 结果 | 失败步骤耗时 |
| --- | --- | --- | --- |
| `37972053466` | `a88ddc1` | frontend 失败 | 前端单测 35s |
| `37972601601` | `a9736b5` | backend 失败 | 后端测试 68s |
| `37973143973` | `8c3edf9` | 两 job 全绿 | 后端 6 步全过、前端 30s |

- 三次运行的被测代码树相同（仅 `ci.yml` 变化），说明与环境相关而非代码回归。
- 本回合本地复现 1 次：`tests/test_api.py::test_upload_list_system_rules_report_logs_delete`（`1 failed, 580 passed`），当时输出被 `tail` 截断未留 traceback；随后 12 次全量重跑（6 次 `pytest`、6 次 `build.py test`）与 1 次双进程并发重跑全部通过，未复现。
### 闭环记录（2026-10-10）

- **再次红跑与精确定位**：补录 CI 证据的文档提交推送后，[run 37976522302](https://github.com/Apuuu66/PatrolX/actions/runs/37976522302) 的 backend job 失败。借助失败诊断钩子的 `::error::` 注解（`GET /repos/Apuuu66/PatrolX/check-runs/113976112331/annotations`，无凭据可读）精确定位 3 个失败用例：
  - `tests/test_delete_race.py::test_completed_task_without_task_json_falls_back_to_record` —— 断言 `"running" == "completed"`；
  - `tests/test_delete_race.py::test_delete_failure_keeps_task_and_restores_meta` —— 断言 `409 == 500`；
  - `tests/test_observability.py::test_task_lifecycle_logs` —— 缺少「任务完成」日志。
- **根因（确定性，非猜测）**：`app/cli.py:run_task` 在收尾步骤（设备台账归档 → 报告渲染 → 「任务完成」日志）**之前**就写了终态 `task.json`；`TaskService._execute` 又要等其返回后才把 SQLite 记录更新为 completed。慢速 runner 放大该窗口，读方（`GET /tasks`、删除竞态、文件缺失兜底列表）可能命中「文件已 completed / 记录仍 running」的不一致状态；本地机器快，12+ 次全量重跑从未复现，与「环境相关」的表象吻合。
- **修复**（`3667c80`）：终态 `task.json` 改为任务现场**最后一次写入**（`_publish_terminal` 发布器，`app/cli.py`）；在线模式发布顺序固定为「SQLite 先收敛 → 再写文件」（`app/services/tasks.py`），普通执行、全量重建、增量重建、重跑与异常路径统一走同一顺序。
- **确定性回归测试**：新增 `tests/test_task_terminal_publication.py` 两个不变量——阻塞 `render_report` 时任务对外不得暴露终态；写终态 `task.json` 前 SQLite 记录必须已 completed。RED 阶段正确失败，修复后 GREEN。
- **本地证据**：`lint`（182 files）、`test` 583 passed、`contract` OK、`verify` exit 0、`e2e` 35 passed；定向用例（新增 2 例 + delete_race + observability + baseline_rerun + rule_state_tasks）20 passed。

修复提交推送后自动触发 [run 37977867312](https://github.com/Apuuu66/PatrolX/actions/runs/37977867312)，两个 job 全部通过：

| Job | 结果 | 耗时 |
| --- | --- | --- |
| backend（lint / test / contract） | success | 91s |
| frontend（客户端零漂移 / 构建 / 单测） | success | 50s |

- 至此第五节从「已知风险」转为「已闭环」：偶发失败由终态发布时序缺陷导致，已用确定性测试锁定，不再依赖「重跑碰运气」。
- 本闭环记录所在提交（`149aeb4`）为纯文档变更，同一 workflow 再次触发复核并同样全绿（[run 37978312071](https://github.com/Apuuu66/PatrolX/actions/runs/37978312071)：backend 97s、frontend 53s），确认闭环记录本身不破坏门禁；该次复核的结果即本记录的终点，不再为记录自身追加提交。

### 第二阶段闭环（2026-10-10，另有多条独立根因）

前条记录完成后，纯文档复核红跑暴露出与终态发布时序无关的独立根因，同日分别用确定性用例锁定并修复：

- **前端 jsdom 伪元素样式查询**：[run 37978615903](https://github.com/Apuuu66/PatrolX/actions/runs/37978615903) 的 frontend job 在 `InventoryPage`/`InventoryDevicePage` 用例偶发报 `Not implemented: window.getComputedStyle(elt, pseudoElt)`（`rc-util/getScrollBarSize.js` 以 `::-webkit-scrollbar` 调用），jsdomError 会挂到当前正在执行的用例上。修复（`63b6e3c`）：`web/src/test/setup.ts` 包装原生 `getComputedStyle` 并丢弃伪元素参数；新增 `web/src/test/setup.test.tsx` 覆盖 antd Table + scroll 触发路径，RED → GREEN。
- **同进程并发落盘临时文件名冲突**：同次红跑的 backend job 在 `test_concurrent_rerun_requests_complete_consistently` 报 `FileNotFoundError: .task.json.2428.tmp -> task.json`。根因：`app/services/store.py:write_json_atomic` 的临时名只含 pid，同进程两个并发写者共享同一临时文件，先完成者 `os.replace` 搬走后另一方失败。修复（`89f812d`）：临时名追加 `uuid4().hex`；新增 `tests/test_baseline_storage.py::test_concurrent_json_write_uses_unique_temp_files`，用 `os.replace` gate 阻塞第一个写者，RED 阶段复现同款 `FileNotFoundError`。
- **前端单测 5s 超时误报**：jsdom 垫片提交后 [run 37980168841](https://github.com/Apuuu66/PatrolX/actions/runs/37980168841) 的 frontend job 仍红，失败仍集中在这两个用例且注解中无 `Not implemented`。本地以 16 路 CPU 抢占复现 `Error: Test timed out in 5000ms`（与 CI 报的用例一致），确认为慢速/高负载环境的超时误报。修复（`57b8013`）：`web/vitest.config.ts` 增 `testTimeout: 15000`；并增强失败摘要（`e792ead`）：红跑时额外 grep `Error:|Not implemented|Timed out` 上下文各 2 处（前后 2/10 行），日志尾部保留 20 行，契约 `contracts/ci-gate.md` 同步更新。

修复推送后自动触发 [run 37980872923](https://github.com/Apuuu66/PatrolX/actions/runs/37980872923)，两个 job 全部通过：

| Job | 结果 | 耗时 |
| --- | --- | --- |
| backend（lint / test / contract） | success | 101s |
| frontend（客户端零漂移 / 构建 / 单测） | success | 41s |

- **本地证据**：`lint` 182 files；`test` 584 passed（含新增并发用例）；`contract` OK；`verify` exit 0；web `npm test` 33 passed（16 路负载下复跑全绿）、`npm run build` OK；`build.py e2e` 35 passed（24.9s；首次失败的单例 `kpi-measurement-version-compare` 单跑 1.3s 通过，判断为并发会话负载下的偶发）。
- 至此第五节四类根因（终态发布时序、并发临时文件名、jsdom 伪元素查询、慢速环境超时）全部闭环；`37980872923` 的绿跑已包含全部修复与增强后的失败摘要，本记录为第五节终点，不再为记录追加额外复核提交。

### 第三阶段闭环（2026-10-10，发布窗口兜底与前端慢例）

第二阶段终点后的红跑再次暴露两个独立根因，同日用确定性用例锁定并修复：

- **终态发布窗口内的兜底读取缺字段**：[run 38017946035](https://github.com/Apuuu66/PatrolX/actions/runs/38017946035)（`8772583`）的 backend job 在 `tests/test_inventory_api.py` 报 `package_kind` 为 `None`、`inventory`/`task` 缺失。根因：`3667c80` 的「SQLite 记录先收敛为 `completed` → 再发布 `task.json`」顺序制造发布窗口，读方在窗口内走 `TaskService` 兜底分支，而兜底构造 `InspectionTask`/`TaskSummary` 时未传 `package_kind` 与 `inventory`。修复（`d8fc645`）：`app/services/tasks.py` 新增 `_record_package_kind()`（非法历史值降级 `inspection`）与 `_fallback_inventory()`（由 `InventoryParseResult.snapshot` 重建，坏快照降级 `None`），`get()`/`list_tasks()` 兜底分支同步补齐；新增 RED → GREEN 用例 `tests/test_task_terminal_publication.py::test_terminal_fallback_read_carries_inventory_and_package_kind`（在发布窗口内触发兜底读）。该修复在 [run 38018393037](https://github.com/Apuuu66/PatrolX/actions/runs/38018393037) 的 backend job 复核通过（后端测试 72s）。
- **前端时区硬编码与慢例超时误报**：同次 `38018393037` 的 frontend job 有三例失败。`ConclusionHero.test.tsx` 断言硬编码 `2026-10-10 08:00`（本地 Asia/Shanghai），CI UTC 下实际渲染 `00:00` —— 修复（`716588e`）改为按 `dayjs("2026-10-10T00:00:00Z").format("YYYY-MM-DD HH:mm")` 计算期望值。`TaskListPage.test.tsx` 两例注解中只有 `FAIL` 行、无 `file=` 注解，与「断言失败必产出 `::error file=`、超时失败不产出」的本地对照实验结论比对后判定为 15s 超时；本地实测 9.2s–15.1s，按 CI 约 1.65 倍慢计算正好越过上限 —— 修复（`716588e`）将三条重页面用例超时提升至 60s。
- **本地证据**：web `npm test` 96 passed（默认时区）、`TZ=UTC` 定向 17 passed、`npm run build` OK；`lint` 182 files、`test` 585 passed。
- 复核 [run 38019407028](https://github.com/Apuuu66/PatrolX/actions/runs/38019407028)（`716588e`）两个 job 全部通过：

| Job | 结果 | 耗时 | 关键步骤 |
| --- | --- | --- | --- |
| backend（lint / test / contract） | success | 99s | 静态检查、后端测试 76s、契约一致性 |
| frontend（客户端零漂移 / 构建 / 单测） | success | 152s | 生产构建 14s、前端单测 124s |

- 至此第五节五类根因（终态发布时序、并发临时文件名、jsdom 伪元素查询、慢速环境超时、发布窗口兜底缺字段）全部闭环；本记录所在提交为纯文档变更，会再次触发同一 workflow 复核，按前例以该次结果为准，不再为记录自身追加提交。

## 六、残留与洁净度

- 未提交残留（与本批次无关，不提交）：`web/.tmp-show-detail.mjs`、`web/.tmp-show-updates.mjs`、`web/e2e/screenshots/`。
- 环境残留进程（截图/调试会话遗留，未清理）：`uvicorn:8000` + `vite:5173`（run_online）、`uvicorn:8011` + `vite:5174`。
- 本回合未改契约、客户端、后端与测试代码；`git status` 中无本批次未跟踪产物。
- 分支与 worktree 已清理：`git worktree remove .worktrees/feature-032-api-contract-governance` + `git branch -d feature/032-api-contract-governance`（删除前确认工作区洁净且 `a88ddc1` 为 `main` 祖先）；`git worktree list` 仅剩 030 / 033 两个非本批次 worktree。
- 并发会话产物（同样不提交）：`web/src/components/MeasurementTrendChart.tsx`、`web/src/components/MeasurementTrendChart.test.tsx`、`web/e2e/kpi-measurement-single-point.spec.ts`、`web/e2e/seed_kpi_measurement_history.py`。

## 七、T034 CI 记录

推送 `main`（`8c3edf9..f0f6cdd`）后自动触发 [run 37975950153](https://github.com/Apuuu66/PatrolX/actions/runs/37975950153)，两个 job 均通过：

| Job | 结果 | 耗时 | 关键步骤 |
| --- | --- | --- | --- |
| backend（lint / test / contract） | success | 89s | 静态检查 1s、后端测试 69s、契约 2s；「后端测试失败摘要」`skipped` |
| frontend（客户端零漂移 / 构建 / 单测） | success | 43s | 客户端零漂移、生产构建 10s、前端单测 22s；「前端单测失败摘要」`skipped` |

- 绿跑时失败诊断步骤为 `skipped`，不改变门禁结论；红跑时其 `::error::` 注解即为失败用例定位入口。
- 本文件所在提交为纯文档变更，同一 workflow 再次触发复核。

该文档提交推送后自动触发 [run 37976223400](https://github.com/Apuuu66/PatrolX/actions/runs/37976223400)（`f0f6cdd..e3b076d`），两个 job 同样全部通过，确认「纯文档变更」不破坏门禁：

| Job | 结果 | 耗时 | 关键步骤 |
| --- | --- | --- | --- |
| backend（lint / test / contract） | success | 84s | 静态检查、后端测试、契约一致性全过；「后端测试失败摘要」`skipped` |
| frontend（客户端零漂移 / 构建 / 单测） | success | 60s | 客户端零漂移、生产构建、前端单测全过；「前端单测失败摘要」`skipped` |

- 至此 `main` 上连续两次 CI（`37975950153`、`37976223400`）双 job 全绿，T034 完成。
- 历史对照：`37972053466`（frontend 失败）、`37972601601`（backend 失败）、`37973143973`（全绿）——见第五节。
