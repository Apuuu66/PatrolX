# 实现计划：界面新增动态派生指标

**分支**：`016-ui-derived-metrics` | **日期**：2026-09-21 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/016-ui-derived-metrics/spec.md` 的功能规格

## 摘要

在 KPI 配置中心新增“在线派生指标”独立维护能力。第一期只支持受控正向比率和受控反向比率，分子与分母必须来自已登记、已分类且同业务域的原始指标。在线派生指标通过新接口保存到 SQLite，并进入新任务的 KPI 配置快照；已有任务快照保持不可变。任务执行器按快照中的受控公式计算派生值，结果展示沿用现有 KPI 结果结构。前端通过 OpenAPI 生成客户端维护列表、公式、启用状态和删除保护。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript + Vite。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、Ant Design。

**存储**：SQLite（配置权威数据）+ `output/<task_id>/kpi/kpi_catalog_snapshot.json`（任务级不可变快照）。

**测试**：pytest、前端构建/关键组件测试；`python build.py contract` 与 `python build.py gen-web-api` 同步契约。

**目标平台**：桌面浏览器访问的本地/在线 FastAPI 服务。

**项目类型**：FastAPI Web 服务 + React 前端。

**性能目标**：配置中心列表分页响应保持现有交互性能；新任务快照创建不显著增加耗时。

**约束条件**：离线巡检、单包单任务、OpenAPI 契约先行、历史任务不可变、不新增被检系统连接。

**规模/范围**：第一期支持受控比率派生指标配置、任务快照计算与展示；不支持任意表达式和派生指标嵌套。

## 宪法检查

*门禁：阶段 0 前通过；阶段 1 设计后复检通过。*

- 离线优先：通过；只读取任务包内已有 CSV，不新增采集。
- 一个包、一个任务：通过；派生指标只进入任务快照，不改变 `task_id` 目录模型。
- 契约驱动：通过；新增 API 先写入 `docs/api/openapi.yaml`，再实现并重新生成前端客户端。
- 模式同构：通过；本地 CLI 与在线 API 都通过 `load_task_kpi_config` 使用同一快照与配置构建逻辑。
- 巡检器插件架构：通过；不硬编码具体成功率，只扩展受控公式解释能力。
- 源文件显式匹配：通过；派生指标不声明 `source_patterns`，复用 KPI 规则已匹配文件。
- 幂等与可追溯：通过；配置写入审计，快照原子写入且历史任务不重算。
- 轻量默认：通过；继续使用 SQLite 和文件快照，不引入外部数据库或队列。
- 容错：通过；输入缺失或分母为零时派生结果标记不可用，不静默伪造成功。

## 项目结构

### 文档（本功能）

```text
specs/016-ui-derived-metrics/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── openapi-contract.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py                         # 新增 v4 派生指标路由和错误转换
├── inspectors/kpi/catalog.py             # 支持受控反向比率与快照配置构建
├── inspectors/kpi/common.py              # 复用现有 KPI 聚合与状态计算
├── models/db.py                          # 新增在线派生指标持久化模型
├── models/schemas.py                     # 新增/扩展契约模型与快照模型
├── services/kpi_config.py                # 新增派生指标 CRUD 与校验/审计
└── services/kpi_catalog.py               # 快照包含在线派生指标并还原执行配置

web/src/
├── api/client.ts                         # 由 OpenAPI 生成，不手写路径
├── components/KpiDerivedMetricEditor.tsx # 派生指标列表、新增/编辑/删除表单
└── pages/KpiResourcesPage.tsx            # 在配置中心挂载派生指标 Tab

tests/
├── test_kpi_config_derived_metrics.py    # CRUD、校验、审计、删除保护
├── test_kpi_task_snapshot.py             # 快照包含/排除与历史快照兼容
└── test_kpi_single_rule.py               # 正向/反向比率和缺失输入任务计算
```

**结构决策**：沿用现有分层 `api → services → inspectors/models` 和 `web/src` 前端结构；新增独立服务函数与数据库模型，避免放宽既有基础指标规则接口的语义。

## 复杂度跟踪

无需豁免。
