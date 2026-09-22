# 实现计划：KPI 自动目录与进阶巡检（021-024 统一实现）

**分支**：`feature/kpi-inspection-advanced` | **日期**：2026-09-23 | **规格**：[021](spec.md)、[022](../022-kpi-threshold-policy/spec.md)、[023](../023-kpi-single-task-trend/spec.md)、[024](../024-kpi-risk-overview/spec.md)

## 摘要

在现有测量单元模型上演进为“自动目录 + 固定指标清单”的主流程：

1. 021：任务 CSV 中发现的指标自动入库、归属测量单元、默认启用；预制目录只做增量补充，不删除已有资源；不再要求人工确认绑定。
2. 022：为指标增加静态阈值策略，结合方向输出预警/失败，并保留数据可读性结论。
3. 023：在单任务内解析时间序列，输出趋势标签、迷你趋势和完整趋势证据。
4. 024：输出任务级 KPI 总览、测量单元健康分、风险排序和重点指标视图。

## 技术上下文

- 语言：Python 3.11+
- 后端：FastAPI + Pydantic v2 + SQLAlchemy + SQLite
- 前端：React + TypeScript + Vite + Ant Design + ECharts
- 测试：pytest、前端构建、OpenAPI 契约一致性
- 存储：SQLite + 任务输出 JSON/报告
- 约束：离线包、单任务隔离、规则私有数据、UTC 时间、契约同步

## 宪法检查

- 保持一个包一个任务一个输出目录。
- 不引入在线采集。
- 普通规则仍通过 `kpi.measurement_units` 处理，不新增规则间依赖。
- 契约变更需同步 OpenAPI、Pydantic、前端客户端、测试。
- 规则逻辑变化需升级 `rule_version`。
- UTC 存储，字段以 `*_at` 命名。

## 项目结构

```text
app/
├── models/db.py
├── models/schemas.py
├── services/kpi_measurement_units.py
├── inspectors/kpi/measurement.py
└── api/router.py
web/src/
├── api/http.ts
└── pages/MeasurementUnitsPage.tsx
tests/
├── test_kpi_measurement_*.py
└── test_kpi_single_rule.py
docs/api/openapi.yaml
```

## 复杂度跟踪

无新增架构违规；沿用现有 KPI 测量单元服务和规则结果契约，通过扩展字段和新增辅助表实现。

## 实现顺序

1. 扩展目录模型：指标方向、重要级别、分组、显示顺序、来源证据，并为增量发现/导入资源初始化完整默认值。
2. 自动入库与预制目录合并。
3. 阈值策略模型与计算。
4. 单任务趋势计算与输出。
5. 健康分、总览和前端展示。
6. 契约同步、测试、构建和全流程验证。
