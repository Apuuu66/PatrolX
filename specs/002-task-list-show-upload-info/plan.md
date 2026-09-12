# 实现计划：任务列表展示上传时选择的信息

**分支**：`002-task-list-show-upload-info` | **日期**：2026-09-12 | **规格**：[spec.md](spec.md)

## 摘要

任务列表 API 和前端卡片新增上传时选择的客户上下文信息（省份、运营商、产品形态、版本）。后端在 `TaskSummary` 中新增四个可选字段，从 SQLite `customer` JSON 列和 `version` 列读取。前端上传表单补齐产品形态下拉框，列表卡片以标签展示。

## 技术上下文

**语言/版本**：Python 3.11+ / TypeScript
**主要依赖**：FastAPI、Pydantic v2、React 18+、Ant Design
**存储**：SQLite（既有 `customer` JSON 列 + `version` 列，无变更）
**测试**：pytest、Ruff、`make contract`、`make web-build`

## 宪法检查

| 原则 | 状态 | 说明 |
| --- | --- | --- |
| 契约驱动 | PASS | 先更新 OpenAPI，再同步 Pydantic 和前端生成客户端。 |
| 模式同构 | PASS | CLI 产出不受影响，`task.json` 不新增字段。 |
| 轻量默认 | PASS | 无新依赖，无存储模型变更。 |
| 离线优先 | PASS | 不涉及采集能力。 |

## 变更清单

### 1. OpenAPI 契约（`docs/api/openapi.yaml`）

- `createTask` 的 multipart schema 新增 `product: string` 可选字段。
- `TaskSummary` 新增 `customer_province`、`customer_operator`、`customer_product`、`customer_version`（均 `type: string`，非 required）。

### 2. 后端 Pydantic（`app/models/schemas.py`）

- `TaskSummary` 新增四个可选 `str` 字段，与 OpenAPI 同名。

### 3. 后端服务（`app/services/tasks.py`）

- `reserve()` 新增 `product: str | None` 参数，存入 `customer["product"]`。
- `list_tasks()` 从 `TaskRecord.customer` 和 `TaskRecord.version` 读取，填充 `TaskSummary` 新字段。
- `get()` 同理填充。

### 4. 后端 API（`app/api/router.py`）

- `create_task()` 新增 `product: str | None = Form(None)` 参数，传入 `reserve()`。

### 5. 前端上传表单（`web/src/pages/TaskListPage.tsx`）

- 上传 Modal 中新增产品形态 `<Select>`，选项来自 `dicts?.product`。
- `submitUpload` 将 `product` 追加到 FormData。

### 6. 前端任务列表（`web/src/pages/TaskListPage.tsx`）

- 任务卡片在名称行下方展示标签：省份、运营商、产品形态、版本。
- 有值才渲染，无值跳过。

### 7. 生成客户端 + 契约验证

- `make contract` 确保契约与实现一致。
- `make gen-web-api` 重新生成前端 API 类型。
- `make web-build` 验证前端构建。
- `make test` + `make lint` 通过。

## 不变更项

- 存储模型（`TaskRecord`）不变。
- `task.json` / `system.json` 契约不变。
- CLI 流程不变。
- 本地模式 `main.py` 不变。
