# Quickstart：验证 KPI 当前判定与昨日趋势

**功能：** `040-kpi-daily-health`  
**适用场景：** 本地开发、契约检查、合成样例验收、真实只读任务展示

## 1. 前置条件

```bash
cd /Users/yigui/code/PatrolX/.worktrees/feature-040-kpi-daily-health
git worktree list
git branch --show-current
.venv/bin/python --version
node --version
```

- 当前目录必须是实现 worktree。
- 当前分支必须是 `feature/040-kpi-daily-health`。
- 不在真实 `data/patrolx.db` 上执行写操作。

## 2. 后端测试

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
```

专项：

```bash
.venv/bin/python -m pytest tests/test_kpi_daily_health.py -q
.venv/bin/python -m pytest tests/test_kpi_daily_health_api.py -q
.venv/bin/python -m pytest tests/test_kpi_maintenance_config.py -q
.venv/bin/python -m pytest tests/test_kpi_measurement_scenarios.py -q
```

## 3. 契约与生成客户端

```bash
.venv/bin/python build.py contract
.venv/bin/python build.py gen-web-api
```

确认：

- `docs/api/openapi.yaml` 包含所有新增路径与 Schema。
- `web/src/api/client.ts` 是可重复生成的，不手工修改。
- `web/src/api/http.ts` 只做薄封装和类型别名。

## 4. 前端验证

```bash
.venv/bin/python build.py web-build
cd web && npm test
cd web && npx playwright test e2e/kpi-daily-health.spec.ts
cd ..
```

E2E 必须从任务详情入口进入 KPI 结果，验证：

1. 首屏同时出现“当前判定”和“较昨日”。
2. 数据日期、最新有效测量时间和范围可见。
3. 状态统计与指标表各行逐项相加一致。
4. 失败/预警/恶化指标进入重点关注。
5. 四个名称相近的成功率各自独立展示。
6. 点击聚合成功率可看到分子、分母、公式和 7 日趋势。
7. 旧任务缺少 `daily_health` 时显示降级提示且不崩溃。

## 5. 本地全流程

```bash
.venv/bin/python build.py verify
```

若该命令会写默认数据库，使用测试配置或隔离临时目录，不触碰现场数据库：

```bash
PATROLX_SQLITE_PATH=/tmp/patrolx-daily-health/patrolx.db \
PATROLX_OUTPUT_DIR=/tmp/patrolx-daily-health/output \
.venv/bin/python build.py verify
```

运行前后记录真实输入 SHA-256；本功能的合成 fixture 不使用真实包。

## 6. 合成样例包

修改 `tests/fixtures/make_real_package.py` 后重新生成固定样例：

```bash
.venv/bin/python tests/fixtures/make_real_package.py
```

必须覆盖：

- 正常基础百分比指标；
- 成功率分子/分母波动且分母不同；
- 分母为零；
- 全零未确认；
- 无阈值/待配置；
- 无昨日基线；
- 停用测量单元范围外文件；
- 旧任务无 `daily_health` 的读取降级；
- 至少 20 个指标以便首屏定位验收。

生成物必须幂等、固定时间戳；不得提交生成的 zip 或解压内容。

## 7. 启动页面并向用户展示

优先使用已有真实任务作为只读展示，不修改其数据库：

```bash
.venv/bin/python build.py run
```

在浏览器打开对应任务详情和 KPI 规则结果，确认：

- 首屏直接显示当前判定与较昨日；
- 当前现场 4 个启用测量单元、77 个指标范围可解释；
- 无数据和全零不会被显示为正常；
- 成功率详情可下钻；
- 维护配置入口可打开。

展示截图只保存到 `/tmp/patrolx-daily-health/`，不得加入 Git。

## 8. 常见问题

### 页面显示“旧任务无日健康结论”

旧任务没有新 metadata。重新执行 KPI 规则生成本功能结果，或使用本功能上线后生成的新任务；不要修改历史结果文件。

### 成功率显示“不适用”

当日分母为 0。这是正确状态，不应显示 0% 或正常。

### 成功率显示“待配置”

该指标未绑定独立分子/分母，或缺少方向、阈值、日聚合/零值语义。到维护配置中补齐，不要按名称自动猜测。

### 全零指标显示“待配置”

全零尚未确认业务含义。配置 `expected_zero` 或 `business_not_triggered` 后再生成结论。

### 首屏打开慢

检查是否误用了 `list_kpi_points(task_id)`；首屏只能读取 `metadata.daily_health`，详情才查询单指标 7 日窗口。
