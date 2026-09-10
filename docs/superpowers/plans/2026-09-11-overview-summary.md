# Overview Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增全局巡检概览接口，并在任务列表页区分任务数、注册规则数、规则结果数与发现问题数。

**Architecture:** 后端新增 `GET /api/v1/overview`，从 `output/` 的任务契约文件汇总任务数、规则结果数、发现数与状态分布，并从规则注册表读取注册规则数；契约同步 OpenAPI 并重新生成前端客户端；前端任务列表页改为消费该全局接口。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、pytest、OpenAPI 3、React + TypeScript + Vite。

**Spec:** 本计划实现当前会话已确认的 Bounded 设计：全局概览包含任务数、注册规则数、规则结果数、发现问题数与状态结果统计。

## Global Constraints

- 任务、规则结果与发现均按既有契约模型语义统计。
- `registered_rule_count` 必须包含 hidden 内部规则。
- `finding_count` 按 `Finding` 记录条数统计，不去重。
- 契约变更必须同步 `docs/api/openapi.yaml` 与生成的前端 client。
- 提交前运行 `make lint`、`make test`；前端改动运行 `npm run build`。

---

### Task 1: Overview API

**Files:**

- Modify: `app/models/schemas.py`
- Modify: `app/api/router.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `web/src/api/client.ts`
- Test: `tests/test_overview.py`

**Interfaces:**

- Produces: `GET /api/v1/overview` 返回 `OverviewSummary`。
- Produces: 前端 `api.getOverview()`。

- [ ] **Step 1: 写失败测试**

测试构造两个任务 JSON、一个含 findings 的 system，断言 task count、registered rule count、rule result count、finding count 与状态统计。

- [ ] **Step 2: 运行测试确认失败**

```bash
make test
```

预期：新用例因接口不存在失败。

- [ ] **Step 3: 最小实现**

新增 Pydantic 模型与 router endpoint，聚合 output 与 registry。

- [ ] **Step 4: 更新契约与 client**

运行：

```bash
make contract
make gen-web-api
```

- [ ] **Step 5: 验证并提交**

```bash
make lint
make test
git commit
```

### Task 2: Task List Overview Cards

**Files:**

- Modify: `web/src/api/http.ts`
- Modify: `web/src/components/SummaryCards.tsx`
- Modify: `web/src/pages/TaskListPage.tsx`

**Interfaces:**

- Consumes: `api.getOverview()`。
- Produces: 首页全局概览卡与状态结果卡。

- [ ] **Step 1: 更新前端消费与展示**

新增 overview API 方法，调整 SummaryCards 支持两组统计，任务列表页移除按当前页累加的伪全局统计。

- [ ] **Step 2: 构建验证**

```bash
cd web && npm run build
```

- [ ] **Step 3: 全量验证并提交**

```bash
make lint
make test
git commit
```
