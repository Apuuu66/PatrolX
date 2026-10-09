# 快速验证指南：主界面信息层级重构（巡检控制台方向）

**功能**：031-ui-information-hierarchy | **日期**：2026-10-10

本指南用于实现完成后的验证与展示效果复现。所有命令在仓库根目录执行。

## 前置条件

```bash
python build.py install          # 已创建 .venv 并精确安装依赖
cd web && npm ci && cd ..        # 前端依赖已安装
```

## 一、自动化质量门禁（必须全绿）

```bash
python build.py web-build        # 类型检查 + 前端构建
python build.py lint             # ruff check + format check
python build.py test             # pytest（含契约一致性）
python build.py e2e              # Playwright：自动起后端(8010) + 前端(5183)
```

- E2E 配置：`web/playwright.config.ts`，`baseURL = http://127.0.0.1:5183`，自动运行 `web/e2e/start-backend.sh` 并加载种子任务。
- 本轮不涉及契约变更，因此 `python build.py contract` 与 `python build.py gen-web-api` **不应产生 diff**；如产生，说明越界修改了接口，需回退。

## 二、四个用户故事的独立验证

### US1 任务列表异常置顶（P1）

```bash
cd web && npx playwright test e2e/task-home.spec.ts
```

人工检查：打开 `http://127.0.0.1:5183/`，确认

1. 失败种子任务（`task-home-failed`）位于第一行，行内直接可见失败原因摘要；
2. 正常任务行的状态摘要只显示非零计数，不出现彩色 0 值；
3. 失败任务行点击"失败日志" ≤2 次点击到达日志页；
4. 重跑 / 增量重建 / 全量重建 / 删除收进 `⋯` 菜单，删除仍需二次确认。

### US2 任务详情首屏结论（P1）

```bash
cd web && npx playwright test e2e/task-detail.spec.ts e2e/task-detail-states.spec.ts
```

人工检查：进入含失败与告警的任务详情，1440×900 首屏内可见结论标签、一句话结论、状态计数、主操作与关键元数据；全通过任务显示"全部通过"且不使用失败红；解压失败任务显示原因与阶段并可跳失败日志。

### US3 规则详情"结论 → 证据 → 建议"（P2）

```bash
cd web && npx playwright test e2e/alarm-flapping-rule-detail.spec.ts e2e/task-detail-rule-browser.spec.ts
```

人工检查：规则详情首屏看到状态、结论摘要与建议；`skip` 显示 `skip_reason`；"显示全部列"可切换且默认精简；重跑按钮进行中状态可见。

### US4 其余页面统一基线（P3）

```bash
cd web && npx playwright test e2e/inventory.spec.ts e2e/page-states.spec.ts e2e/navigation-icons.spec.ts
```

人工走查：设备台账、设备详情、基础指标、规则管理、数据字典、报告、日志、用户管理逐页对照 `contracts/ui-baseline.md` 第 1、2、3、5、6 节；确认设备台账与设备详情默认每页 10 条；空 / 加载 / 错误态文案与重试入口一致。

## 三、单元测试（Vitest）

```bash
cd web && npm run test
```

覆盖重点：

- `deriveTaskConclusion` 全部分支（失败 / 排队 / 执行中 / 含 fail+error / 仅 warn / 全通过）；
- `StatusDistribution` 0 值不渲染、五态全 0 时不渲染空条；
- 任务列表默认排序（异常置顶 + 同状态创建时间倒序）；
- 任务详情结论 Hero 渲染；
- 规则详情顺序与 skip 原因；
- `InventoryPage` / `InventoryDevicePage` 默认分页 10。

## 四、展示效果证据（SC-007）

1. E2E 全绿后，从 `web/e2e/screenshots/` 取 1440×900 截图：任务列表 / 任务详情 / 规则详情 / 1 个基线页面（设备台账或基础指标）。
2. 用真实样例包复现：

```bash
python build.py verify                                     # 全流程：解压 → prepare → inspect → 报告
python build.py verify-one --rule kpi.measurement_units    # 如需单规则复现
```

   解压产物位于 `output/<task_id>/`；随后启动界面（`python build.py run`，或 `cd web && npm run dev`）打开该任务，确认界面结论与报告一致。

3. 记录走查结果：逐页对照 `contracts/ui-baseline.md`，把通过项与例外项写入实现分支的验证报告。

## 五、通过判据

- `python build.py web-build`、`lint`、`test`、`e2e` 全部通过；
- SC-001 ~ SC-007 均可复现（首屏可见性、异常置顶、点击次数、无重复表达、基线走查、截图证据）；
- `docs/design/DESIGN.md` 已按 `contracts/ui-baseline.md` 回写；
- 未改动 `docs/api/openapi.yaml`，未新增依赖，未新增路由。
