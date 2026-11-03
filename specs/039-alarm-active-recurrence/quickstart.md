# 快速验证：未清除告警与反复上报巡检

## 前置条件

- 在实现分支 worktree `.worktrees/feature-039-alarm-active-recurrence` 内执行。
- 已运行 `python build.py install`，或使用仓库现有 `.venv/bin/python`。
- 合成包只使用 `tests/fixtures/make_real_package.py` 生成；真实告警 CSV 只读。

实现前置检查：

```bash
git worktree list
git branch --show-current
pwd
```

预期：当前目录是 039 worktree，分支为 `feature/039-alarm-active-recurrence`，且 039 规划产物已在 `main` 提交。

## 1. 聚焦单元测试

```bash
.venv/bin/python -m pytest -q \
  tests/test_alarm_common.py \
  tests/test_alarm_active_state.py \
  tests/test_alarm_recurrence.py \
  tests/test_alarm_recurrence_report.py \
  tests/test_scan_config_registry.py \
  tests/test_kpi_only_rule_library.py \
  tests/test_real_package.py
```

重点确认：

- 纯英文、纯中文、混合同任务等价归一化；
- 未知状态/严重级/表头进入质量统计，不猜测活动状态；
- `Not Cleared` 活动筛选、严重级/重复/持续排序；
- `Repeat Times=0` 多生命周期仍触发 `multi_lifecycle`；
- 单条高 `Repeat Times` 触发 `repeat_reporting`；
- 60 分钟 3 次触发 `rapid_recurrence`，300 秒内清除触发 `short_alarm`；
- `Reset Cleared` 只计数，不宣称为稳定恢复；
- 跨文件重复去重、单文件失败隔离、预算降级和截断不改变汇总；
- 每条 Finding 有稳定 id、来源文件和行号。

## 2. 注册与扫描范围

```bash
.venv/bin/python -m pytest -q tests/test_scan_config_registry.py tests/test_scan_refs.py
```

预期：

- 活动普通规则为 `kpi.measurement_units`、`alarm.active_state`、`alarm.recurrence`；
- `alarm_all` 仅匹配 `^alarm/[^/]+\.csv$`；
- 两条告警规则均声明 `source_refs=["alarm_all"]`，且不互相依赖；
- 隐藏规则仍只有两个 `pkg.extract.*` 单元。

## 3. 代表性合成包

```bash
.venv/bin/python tests/fixtures/make_real_package.py /tmp/patrolx-039-fixture
```

使用固定时间戳重复生成同一个包并计算 SHA-256，连续两次应一致。样例至少包含英文、中文、混合同任务、活动 Critical/Major、零重复多次发生、短告警、快速复发、单条高重复、`Reset Cleared`、对象缺失、重复行、坏记录和坏文件。

执行全流程：

```bash
.venv/bin/python build.py verify
```

预期任务完成，两条告警规则均被调度且主要结果可在 `rules/*.json` 与报告/页面查看。KPI 规则行为保持不变。

## 4. 单规则重跑同构

```bash
.venv/bin/python build.py verify-one --rule alarm.active_state
.venv/bin/python build.py verify-one --rule alarm.recurrence
```

预期：

- 全量执行与分别单规则重跑的核心 `status`、metrics、findings 语义和 metadata 一致（`executed_at`、`duration_ms` 除外）；
- 单规则重跑只替换目标规则 JSON；
- 两条规则互不读取对方结果，也不产生 prepared 数据。

## 5. 页面与报告展示

```bash
.venv/bin/python build.py run
```

在规则详情页验证：

- `alarm.active_state` 首屏出现“未清除告警”面板，能区分活动记录/分组、最高严重级、状态分布、原始重复合计、估算上报总数；
- 明细可看到严重级、应用、告警、对象、首次上报、持续时长、原始 `Repeat Times`、估算次数和来源行；
- `alarm.recurrence` 首屏出现“告警反复上报”面板，能同时看到生命周期次数、两种累计上报口径、最大单条重复、首次/最近时间、间隔和五类证据标记；
- 展开对象明细后可定位各对象；类型汇总不因对象拆分丢失计数；
- `Reset Cleared` 文案不出现“稳定恢复”结论；
- 每类展示超过 100 条时有明确截断提示，汇总数字不被截断。

HTML 报告必须显示活动告警数、未清除最高严重级、原始重复次数合计、估算上报总数和优先处置建议。

## 6. 真实告警文件只读验收

已知输入（不得复制、移动、修改或提交）：

```text
output/task-all_20261031173253/alarm/alarm_history_20261031173253717.csv
sha256=37684ebd5e352a2c44548974ca8e5680443c05c0d362377d64e6b613b9e350d5
bytes=711968

output/task-all_20261031173253/alarm/alarm_history_20261031173255511.csv
sha256=655617889ed349f7fdd290c99e8410e2a7d01a55f3c42214dde361cd277cfdc2
bytes=57627
```

验收前后分别执行 `shasum -a 256 <file>`，并核对大小不变。只读执行两条规则后确认：

- 有效生命周期 2,209、告警类型 44、应用 2；
- 状态：Not Cleared 16、Normal Cleared 2,179、Reset Cleared 14；
- 严重级：CRITICAL 79、HIGH 2,060、MEDIUM 70；
- `Repeat Times > 0` 584 条、全部原始重复合计 43,762、估算上报总数 45,971；
- 活动原始重复合计 41,776、活动估算上报总数 41,792、活动最大单条重复 41,695；
- `137611`：1,581 条生命周期、重复合计 1,218、单条最大 193；
- `135203`：28 条生命周期、重复合计 0；
- 覆盖末刻为 `2026-10-31 17:15:23 +08:00`；
- 失败文件数为 0，且源文件 SHA-256、大小、mtime 不变。

不得把真实任务目录、告警 CSV、规则 JSON、报告、截图或临时验收输出加入 Git。

## 7. 完整质量门禁

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py verify
.venv/bin/python build.py web-build
```

前端交互还须执行：

```bash
cd web && npm test
cd web && npx playwright test e2e/alarm-active-recurrence.spec.ts
```

本功能不修改 OpenAPI；如实现阶段需要新增 HTTP/Schema 字段，必须先更新 `docs/api/openapi.yaml`，再实现并执行 `contract` 与 `gen-web-api`。

## 8. 提交前检查

```bash
git status --short
git diff --check
git diff --cached --name-status
```

暂存候选不得包含 `uploads/`、`output/`、`DataCollect/`、数据库、日志、报告、截图、临时目录、真实包或派生数据。不得使用 `git add -A`。
