---
spec: 032-api-contract-governance
branch: feature/032-api-contract-governance（已 fast-forward 合入 main）
worktree: .worktrees/feature-032-api-contract-governance（合入验证通过后清理）
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

## 五、CI 偶发失败（已知风险，本回合未闭环）

| 运行 | 提交 | 结果 | 失败步骤耗时 |
| --- | --- | --- | --- |
| `37972053466` | `a88ddc1` | frontend 失败 | 前端单测 35s |
| `37972601601` | `a9736b5` | backend 失败 | 后端测试 68s |
| `37973143973` | `8c3edf9` | 两 job 全绿 | 后端 6 步全过、前端 30s |

- 三次运行的被测代码树相同（仅 `ci.yml` 变化），说明与环境相关而非代码回归。
- 本回合本地复现 1 次：`tests/test_api.py::test_upload_list_system_rules_report_logs_delete`（`1 failed, 580 passed`），当时输出被 `tail` 截断未留 traceback；随后 12 次全量重跑（6 次 `pytest`、6 次 `build.py test`）与 1 次双进程并发重跑全部通过，未复现。
- 处置：不做无证据的「修复」；失败诊断钩子已就位。下次失败时先取注解定位用例，再按证据收敛（必要时隔离重负载用例或调整超时）。

## 六、残留与洁净度

- 未提交残留（与本批次无关，不提交）：`web/.tmp-show-detail.mjs`、`web/.tmp-show-updates.mjs`、`web/e2e/screenshots/`。
- 环境残留进程（截图/调试会话遗留，未清理）：`uvicorn:8000` + `vite:5173`（run_online）、`uvicorn:8011` + `vite:5174`。
- 本回合未改契约、客户端、后端与测试代码；`git status` 中无本批次未跟踪产物。
- 并发会话产物（同样不提交）：`web/src/components/MeasurementTrendChart.tsx`、`web/src/components/MeasurementTrendChart.test.tsx`、`web/e2e/kpi-measurement-single-point.spec.ts`、`web/e2e/seed_kpi_measurement_history.py`。

## 七、T034 CI 记录

（运行链接在推送后补录，见本文件下一次提交。）
