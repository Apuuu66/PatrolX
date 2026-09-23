# 实现计划：KPI 同设备版本对比

**分支**：`026-kpi-device-version-compare` | **日期**：2026-09-24 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/026-kpi-device-version-compare/spec.md` 的功能规格

## 摘要

在既有单指标跨任务趋势之上，增加“同设备、不同系统版本”的显式对比模式。系统从任务元数据中读取设备 ID 和版本，按同设备已完成任务生成版本候选；用户选择一个不同版本后，服务端选择该版本下完成时间最新的任务作为基线任务，并按当前维度流式读取任务私有 `kpi/history/index.jsonl`，返回两条可追溯曲线和均值摘要。该能力不重建任务、不合并任务、不加载任务级大结果。

## 技术上下文

**语言/版本**：Python 3.11+；Node.js / TypeScript（现有 web 工具链）

**主要依赖**：FastAPI、Pydantic v2、React、Ant Design、ECharts

**存储**：文件系统任务目录；`task.json` 元数据；`kpi/history/index.jsonl` 点位索引

**测试**：pytest、FastAPI TestClient、Vitest、npm build

**目标平台**：本地桌面浏览器 + 单节点 FastAPI / CLI 共享服务层

**项目类型**：Web 应用（后端 API + 前端 SPA）

**性能目标**：600+ 指标任务下只加载单测量单元、单指标、单对象、单周期点位，不加载任务级结果

**约束条件**：离线优先；UTC 存储；契约先行；索引坏行不阻断；版本缺失明确降级

**规模/范围**：单指标趋势弹窗内的版本候选选择与版本对比展示

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

- **离线优先**：通过：只读取本地任务目录和索引。
- **一个包、一个任务**：通过：版本对比引用任务，不合并或重建任务目录。
- **契约驱动**：通过：先新增 OpenAPI path/schema，再生成客户端和实现。
- **模式同构**：通过：版本候选与对比逻辑放在共享 service，不放在 API 层。
- **轻量默认**：通过：无新增数据库或后台服务。
- **按需加载**：通过：候选只读元数据；对比按任务流式读取索引并过滤当前维度。
- **新功能验证与展示效果**：通过：计划包含服务、API、前端测试和可展示 fixture。

## 项目结构

### 文档（本功能）

```text
specs/026-kpi-device-version-compare/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py
├── models/schemas.py
└── services/kpi_history.py
docs/api/openapi.yaml
web/src/
├── components/MeasurementTrendChart.tsx
├── utils/measurementHistory.ts
tests/
├── test_kpi_device_version_compare.py
└── test_kpi_version_compare_api.py
web/src/utils/measurementVersionCompare.test.ts
```

**结构决策**：沿用现有 app 服务层 + FastAPI 路由 + React 组件的 Web 应用结构。版本对比是历史趋势域的扩展，不新增顶层模块。

## 阶段 0 研究结论

见 [research.md](research.md)。

## 阶段 1 设计

- 数据模型见 [data-model.md](data-model.md)。
- API 契约见 [contracts/version-compare.md](contracts/version-compare.md)。
- 展示与验证见 [quickstart.md](quickstart.md)。

## 技术方案

### API 设计

选择“新增两个只读接口”的方案：

1. `GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/version-candidates`
   - 返回同设备已完成任务的版本分组和每组最新任务。
2. `GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/version-compare?baseline_task_id=...`
   - `object_key`、`period_minutes` 必传或允许 null；返回当前/基线两条曲线、摘要和降级原因。

选择理由：历史趋势响应中的 `history_series`、`baseline_points` 表达的是“多历史任务同时刻基线”，与版本对比需要保留的单任务曲线和任务来源不同。新增契约可以避免字段含义混杂，也符合契约驱动和可维护性要求。

### 服务设计

在 `app/services/kpi_history.py` 中扩展历史域共享函数：

- `_task_version` 读取 `TaskSummary.customer_version`。
- `_list_device_version_candidates` 扫描任务目录元数据，过滤同设备已完成任务并按版本分组；同一版本选完成时间最新任务。
- `get_version_candidates` 组装候选响应。
- `get_version_compare` 读取当前/基线任务，校验设备、状态、版本和维度；分别流式读取并过滤索引；使用平均值生成摘要；输出稳定 `reason_code`。

### 前端设计

在趋势 Tab 中增加“版本对比”模式：

- 保留现有对象和周期选择，保证维度一致。
- 打开模式后加载版本候选，Select 显示“版本未知”时保留空值标签。
- 选择基线任务后调用对比接口。
- 展示当前版本/基线版本、基线任务 ID 和完成时间。
- ECharts 展示“当前版本”和“基线版本”两条独立曲线。
- 摘要显示绝对差值、变化比例和方向解释；降级时显示具体原因。

## 宪法检查（阶段 1 后）

- OpenAPI 将作为实现前置任务更新，并由 contract 校验和生成客户端。
- 服务函数保持共享，CLI/API 可复用；本功能不需要 CLI 参数，也不改变巡检器输出。
- 只读元数据候选可能扫描任务目录，但只读取每个任务的 `task.json`；点位仍按需加载。
- 不自动重建、不重解压、不合并任务。

## 复杂度跟踪

无需豁免。
