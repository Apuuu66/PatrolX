# 实现计划：KPI 资源全集登记与在线分类

**分支**：`011-kpi-resource-classification` | **日期**：2026-09-18 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/011-kpi-resource-classification/spec.md` 的功能规格

## 摘要

建立独立于 `call`、`api`、`media` 域配置的 KPI 资源指标库。资源 CSV 导入只生成基础指标信息，所有指标初始为未分类；在线配置页面提供搜索、状态筛选、单条和批量分类。分类结果写入目标域配置并同步资源库状态，但不自动生成阈值、公式或告警。已引用指标禁止换域，配置写入使用锁与失败回滚保护。

## 技术上下文

**语言/版本**：Python 3.11+；前端 TypeScript + React 18。

**主要依赖**：FastAPI、Pydantic v2、pandas/pyarrow 可选、PyYAML、React、Ant Design、ECharts。

**存储**：继续使用文件配置。新增 `deploy/config/kpi/resource_metrics.yaml` 保存资源指标库和分类状态；新增 `deploy/config/kpi/resource_metrics_audit.jsonl` 保存导入/分类审计。不引入外部数据库。

**测试**：后端 pytest；前端 Node 内置测试；契约通过 `python build.py contract` 校验，前端客户端通过 `python build.py gen-web-api` 生成。

**目标平台**：桌面优先的本地/在线管理服务，Linux/macOS 运行。

**性能目标**：1000 行资源 CSV 导入和保存在 2 秒内完成；100 个指标的批量分类在 2 秒内返回。

**约束条件**：不得连接被检系统；不得在线采集；一个包一个任务模型不改变；OpenAPI 变更先于实现；既有 `/api/v2` 字段语义保持兼容。

**规模/范围**：资源全集按数千指标内设计；首版只支持 `call`、`api`、`media` 三个域。

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

- **离线优先**：通过。资源 CSV 是用户提供的离线快照；在线分类仅管理本地配置，不采集被检系统数据。
- **契约驱动**：通过。先扩展 `docs/api/openapi.yaml`，再实现 Pydantic/FastAPI 接口并重新生成前端客户端。
- **模式同构**：通过。资源导入工具与在线导入共享同一解析和登记服务；KPI 巡检器继续读取既有域配置。
- **插件架构**：通过。不修改调度器，不新增硬编码业务巡检规则。
- **源文件显式匹配**：不适用。本功能不新增普通巡检规则。
- **文件与安全**：通过。只写入受控配置目录；CSV 读取有编码、行数和字段校验；YAML 写入使用临时文件与锁。
- **时间与日志**：通过。持久化时间使用 UTC 和 `*_at` 字段；操作审计结构化保存。
- **语言策略**：通过。规划产物、注释和文档为中文，标识符与接口字段为英文。

## 项目结构

### 文档（本功能）

```text
specs/011-kpi-resource-classification/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── kpi-resource-metrics.yaml
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/services/kpi_resources.py
app/api/router.py
app/models/schemas.py
tools/generate_kpi_config.py
tests/test_kpi_resource_metrics.py
tests/test_kpi_resource_api.py
docs/api/openapi.yaml
docs/architecture.md
docs/design/entrypoints.md
web/src/api/client.ts
web/src/App.tsx
web/src/layouts/MainLayout.tsx
web/src/pages/KpiResourcesPage.tsx
web/src/components/KpiResourceTable.tsx
web/src/components/kpiResourceModel.ts
web/src/components/KpiResourceTable.test.ts
```

**结构决策**：复用现有 FastAPI + React 单仓库分层。资源库解析、校验、持久化和分类服务放在 `app/services/kpi_resources.py`，API 层只做请求转换和错误映射；CLI 工具复用同一服务，避免本地与在线行为分叉。

## 复杂度跟踪

> **仅在宪法检查存在需要说明的违规时填写**

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
|--------|-----------|---------------------------|
| 无 | 无 | 无 |
