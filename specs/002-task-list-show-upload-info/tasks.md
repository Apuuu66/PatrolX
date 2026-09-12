# 任务：任务列表展示上传时选择的信息

**前置条件**：plan.md

## 阶段 1：契约先行

- [ ] T001 更新 `docs/api/openapi.yaml`：`createTask` 新增 `product` 表单参数；`TaskSummary` 新增 `customer_province`、`customer_operator`、`customer_product`、`customer_version`
- [ ] T002 更新 `app/models/schemas.py`：`TaskSummary` 新增同名字段

## 阶段 2：后端

- [ ] T003 更新 `app/services/tasks.py`：`reserve()` 接收 `product` 并存入 `customer`；`list_tasks()` 和 `get()` 从 DB 填充新字段
- [ ] T004 更新 `app/api/router.py`：`create_task()` 新增 `product: str | None = Form(None)` 并传入 `reserve()`

## 阶段 3：前端

- [ ] T005 运行 `make gen-web-api` 重新生成前端 API 客户端类型
- [ ] T006 更新 `web/src/pages/TaskListPage.tsx`：上传表单新增产品形态下拉框；任务卡片新增客户上下文标签展示

## 阶段 4：验证

- [ ] T007 运行 `make contract` 确认契约与实现一致
- [ ] T008 运行 `make lint` 确认代码规范
- [ ] T009 运行 `make test` 确认既有测试通过
- [ ] T010 运行 `make web-build` 确认前端构建通过
