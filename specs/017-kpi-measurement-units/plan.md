# 实现计划：基于测量单元的 KPI 巡检

**分支**：`017-kpi-measurement-units` | **日期**：2026-09-22 | **规格**：[spec.md](spec.md)

**输入**：以 `MU_*` 为管理主体，重做资源导入、任务文件归属、指标绑定、可读性巡检、行对象明细和成功率派生指标；完全删除旧业务域 KPI 模型。

## 摘要

新版 KPI 使用一张资源目录和一组轻量绑定配置。资源导入按资源 ID upsert `MU`、`ME`、`UNIT`；测量单元英文名转下划线片段后大小写敏感匹配任务文件。任务解析扫描 `周期(分钟)` 之后的指标列，按基础列名匹配 `ME`，生成候选绑定；只有 `confirmed + enabled` 绑定参与巡检。巡检聚合维度为任务、测量单元、周期、文件时间戳和行对象，MVP 默认 100% 可读性期望，不做业务阈值。成功率派生指标只支持分子/分母模板。

## 技术上下文

**语言/版本**：Python 3.11+
**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、pandas、React + TypeScript + Ant Design
**存储**：SQLite 保存资源、绑定、派生定义；任务结果写入 `output/<task_id>/`
**测试**：pytest、Vitest、OpenAPI 契约测试、本地全流程验证
**目标平台**：桌面浏览器 + Linux 后端
**项目类型**：FastAPI + React 离线巡检系统
**性能目标**：MVP 单任务文件数与记录数受现有任务预算约束
**约束条件**：不连接被检系统；一个包 = 一个任务 = 一个输出目录；失败隔离
**规模/范围**：资源目录、绑定维护、新 KPI 巡检和结果页；不做旧任务迁移

## 宪法检查

- 离线边界：仅读取已解压任务包，不新增采集能力。通过。
- 任务隔离：新模型只读取当前任务输出目录，结果不跨任务聚合。通过。
- 单文件失败隔离：文件/行错误写入状态与原因，不中断任务。通过。
- 规则契约：新规则声明完整元数据、版本和 `source_patterns`。通过。
- 契约先行：实现前更新 OpenAPI、Pydantic Schema、测试和生成客户端。通过。
- UTC：新增时间字段使用 UTC `*_at`。通过。
- 破坏性变更：删除旧 KPI 属于独立新模型，不改变既有字段语义之外的旧路径；旧路径/页面随本功能删除。通过。

## 项目结构

```text
app/
├── api/router.py
├── inspectors/kpi/measurement.py
├── models/db.py
├── models/schemas.py
└── services/kpi_measurement_units.py
web/src/
├── components/KpiMeasurementUnitsPanel.tsx
└── pages/KpiMeasurementUnitsPage.tsx
tests/
├── test_kpi_measurement_resources.py
├── test_kpi_measurement_matching.py
└── test_kpi_measurement_inspector.py
```

**结构决策**：沿用现有分层。资源与绑定服务在 `services`，巡检规则在 `inspectors/kpi`，管理 API 在路由层；前端用独立页面替代旧 KPI 页面。

## 复杂度跟踪

无宪法违规。
