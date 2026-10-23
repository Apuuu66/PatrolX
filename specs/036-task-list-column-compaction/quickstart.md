# 快速验证：任务列表列宽压缩

## 前置条件

- 已完成依赖安装：`python build.py install`（本机无 `python` 时使用 `.venv/bin/python`）。
- 前端依赖已就绪：`cd web && npm install`（或复用既有 `node_modules`）。
- 后端与前端由既有测试脚手架启动（`web/playwright.config.ts` 的 webServer 逻辑），无需手工起服务。

## 1. 单元测试与构建

```bash
cd web && npx vitest run
cd web && npm run build
```

预期：

- `TaskListPage.test.tsx` 断言时间三列合并为单个 `task-time` 单元格，且 `task-duration` / `task-last-run` / `task-created-at` 三段仍在同一单元格内。
- 运行中任务只显示"运行中"、从不运行任务显示 `-` 的既有覆盖保持通过。
- 元数据平铺 3 项 + "更多元数据（N）"Popover 的行为覆盖通过。
- 构建无类型错误。

## 2. 端到端验证

```bash
cd web && npx playwright test
```

重点场景：

- 任务列表（`task-home.spec.ts`）：1440×900 下 `.task-table` 不出现内部横向滚动（`table.scrollWidth <= table.clientWidth`）；6 个列头顺序正确；无"创建时间 / 最后运行 / 任务时长"独立列头。
- 时间列：失败任务显示"10 秒"；悬浮最后运行时间出现完整时间戳；单元格内不出现完整时间戳文本。
- 操作列：横向滚动后仍贴右可见；详情 / 失败日志 / 重建 / 删除平铺；无"重跑"、无 `⋯` 菜单。
- 元数据：平铺不超过 3 项；`更多元数据` 面板可见剩余字段。
- 布局回归（`theme.spec.ts`）：1280 / 1920 页面级横向滚动为 0，1920 内容宽度 ≤ 1600。

## 3. 走查与截图

```bash
cd web && npx playwright test e2e/task-home.spec.ts
```

`task-home.spec.ts` 的 1440 与 1280 用例各自留存 1 张全页截图到 `web/e2e/.tmp/`（已在 `.gitignore` 中；注意 `web/test-results/` 会被每次 Playwright 运行清空，不能存放证据）：

1. `036-task-list-1440.png`：全部 6 列一屏可见，无内部滚动条。
2. `036-task-list-1280.png`：出现表格内部滚动条（已滚到底），操作列仍固定右下，页面本身无横向滚动。

## 4. 对照检查

- 打开任一任务的"更多元数据"，确认标签与完整值可复制，点击外部可关闭。
- 确认任务行内不再出现"创建时间 / 最后运行 / 任务时长"三个独立列头。
- 确认详情页 Hero 的元数据平铺上限仍为 4 项（本功能只改任务列表）。
- 确认任务列表不存在任务级"重跑"入口。

## 5. 质量门禁

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py web-build
.venv/bin/python build.py e2e
```
