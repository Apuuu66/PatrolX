# 实现计划：指标绑定批量确认

**分支**：`feature/020-batch-confirm-bindings` | **日期**：2026-09-22 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/020-batch-confirm-bindings/spec.md` 的功能规格

## 摘要

在测量单元绑定关系列表中新增多选与批量确认能力。后端通过一次请求接收去重后的绑定 ID 列表，逐项判断是否存在、是否可确认以及是否违反跨测量单元同指标冲突保护；成功项更新为已确认，失败项保留原状态并返回明确原因。前端提供表格多选、批量确认入口和结果摘要展示。

## 技术上下文

**语言/版本**：Python 3.11+

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、React + TypeScript + Ant Design

**存储**：SQLite，复用既有 `kpi_measurement_bindings` 表；不新增数据表或迁移

**测试**：pytest；契约一致性使用 `python build.py contract`；前端使用 `npm run build`

**目标平台**：本地/在线共用的单节点离线巡检系统

**项目类型**：FastAPI 后端 + React 前端

**性能目标**：一次请求最多确认 200 条绑定，沿用现有管理接口的轻量事务模型

**约束条件**：离线优先、契约驱动、部分成功可观察、不隐式修改未选中绑定

**规模/范围**：仅扩展指标绑定确认能力，不扩展指标资源绑定、注册、忽略或导出能力

## 宪法检查

- **离线优先**：符合；只修改本地任务发现并导入的绑定关系，不连接被检系统。
- **契约驱动**：先同步 `docs/api/openapi.yaml`，再实现 Pydantic/FastAPI，并重新生成前端客户端。
- **模式同构**：批量确认服务在 API 与本地模式读取同一 SQLite 数据模型，不改变任务隔离模型。
- **插件架构**：不修改规则调度器，不新增业务规则；确认后的绑定继续按现有 KPI 巡检逻辑消费。
- **幂等与可追溯**：重复确认不改变已确认绑定；更新只针对明确请求 ID，并保留任务来源信息。
- **轻量默认**：复用现有绑定表和统一错误类型，不新增外部依赖。
- **数据分页默认**：列表分页保持不变；批量请求上限与现有管理接口最大分页一致，取 200。
- **容错**：单条失败不影响其他独立成功项，失败原因逐项返回。

## 项目结构

### 文档（本功能）

```text
specs/020-batch-confirm-bindings/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py
├── models/schemas.py
└── services/kpi_measurement_units.py
docs/api/openapi.yaml
tests/
├── test_kpi_measurement_api.py
└── test_kpi_measurement_binding.py
web/src/
├── api/http.ts
└── pages/MeasurementUnitsPage.tsx
```

**结构决策**：复用测量单元领域的服务、v5 API 路由、绑定 Schema 和测量单元页面；不新建模块，不引入新存储实体。

## 实现要点

1. 请求契约：
   - 新增 `POST /api/v5/kpi/measurement-bindings/batch-confirm`。
   - 请求体 `binding_ids` 非空、元素唯一去重由服务层保证、列表长度上限 200。
   - 使用 admin 权限，与现有单条状态更新一致。
2. 响应契约：
   - 返回 `total`、`succeeded`、`failed` 和 `items`。
   - 每个结果包含 `binding_id`、`outcome`、成功时的 `binding`、失败时的 `error_code` 和 `message`。
   - `outcome` 使用 `confirmed`、`already_confirmed`、`failed`；`succeeded` 包含幂等成功。
   - 结果按请求中首次出现的绑定 ID 排序；重复 ID 只处理一次。
3. 状态规则：
   - `candidate` 且 `metric_resource_id` 非空可确认。
   - `confirmed` 重复确认返回 `already_confirmed`，不更新 `updated_at`。
   - 缺少指标资源、不存在、`conflict` 或 `ignored` 均为失败，不修改记录。
   - 不提供批量取消确认；`candidate` 继续是失败后的安全回退状态。
4. 冲突保护：
   - 请求前先聚合本次可确认绑定和数据库中同 ME 指标、不同测量单元、状态为已确认的绑定。
   - 同一 ME 指标在本次批量请求中出现多个不同测量单元时，所有相关候选项失败。
   - 已确认绑定本身的重复提交不受冲突聚合影响，继续返回幂等成功。
   - 同一测量单元内重复绑定同一指标不视为跨单元冲突。
5. 事务边界：
   - 一次请求内完成校验和更新；成功项提交，失败项不更新。
   - 部分成功返回 HTTP 200；空列表、超上限等请求结构问题由 Pydantic 校验返回 422。
6. 前端：
   - 绑定关系表格增加 row selection。
   - 批量确认入口仅管理员可见；无选择时禁用。
   - 提交后展示成功、幂等成功和失败摘要；存在失败时用警告提示，并逐项显示可定位原因。
   - 成功后刷新当前页，并清理已不存在或多状态不再可选的选中项。
7. 日志：
   - 服务层记录请求去重数量、成功数和失败数；不记录完整原始查询数据。

## 复杂度跟踪

无宪法违规；不填写例外说明。
