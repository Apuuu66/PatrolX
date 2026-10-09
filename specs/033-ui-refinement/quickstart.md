# 快速验证：界面降噪与一致性精修

## 前置条件

- 已完成 `python build.py install`（本机无 `python` 时使用 `.venv/bin/python`）。
- 前端依赖已安装：`cd web && npm install`（或既有 node_modules）。

## 1. 单元测试与构建

```bash
cd web && npx vitest run
cd web && npm run build
```

预期：全部通过；新增测试覆盖状态排序 / 弱化色、Tooltip 文案、零值与空元数据、证据解析、密度偏好、task_id 预览、对比度与严重度轻量标签。

## 2. 端到端验证

```bash
cd web && npx playwright test
```

重点场景：

- 任务列表：异常优先排序、概览条弱化色与 Tooltip、时间列层级、行操作收敛、密度切换记忆。
- 任务详情：结论句无 0 值、空元数据不渲染、重点关注与全部规则去重及"显示全部"。
- 规则详情：源文件匹配一行、发现证据结构化与折叠、复制反馈、严重度轻量表达。
- 规则管理：相对时间 + 完整时间 Tooltip、排序、开关失败回滚、编码等宽。
- 上传弹窗：任务 ID 预览、非法文件禁用、同名冲突提示。
- 布局回归：1280 / 1440 / 1920 无页面级横向滚动（复用 `theme.spec.ts`）。

## 3. 走查与截图

```bash
cd web && npx playwright test e2e/<spec>.spec.ts
```

按 1440×900 留存 5 张截图到 `web/e2e/screenshots/`（本地证据，不提交）：

1. 任务列表（概览条 + 行操作）
2. 任务详情（结论 + 去重后的全部规则）
3. 规则详情（结构化发现 + 一行源文件匹配）
4. 规则管理（相对时间 + 密度）
5. 上传弹窗（任务 ID 预览）

## 4. 对照检查

- 后端任务 ID 派生：用同一文件名对照 `app/cli.py::clean_task_id` 输出与前端预览一致。
- 术语：界面文案与 `docs/design/DESIGN.md` 术语表一致。
- 对比度：状态文字色 ≥ 4.5:1，"异常"具备颜色以外冗余标识。

## 5. 质量门禁

```bash
.venv/bin/python build.py lint
.venv/bin/python build.py test
.venv/bin/python build.py web-build
```

前端改动不涉及后端执行链路，全流程 `build.py verify` 可选；若实现期间改动了后端文件（预期不改），必须补跑。
