# 实现计划：CSV KPI 离线巡检

**分支**：`006-csv-kpi-inspection` | **日期**：2026-09-14 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/006-csv-kpi-inspection/spec.md` 的功能规格

## 摘要

为离线包中的 KPI CSV 建立三条互相隔离的普通巡检规则：`kpi.api`、`kpi.media`、`kpi.call`。规则按文件名模板 `kpi-<domain>-<period>.csv` 匹配自己的数据，支持 `5`、`15`、`30`、`60` 分钟周期；每个 CSV 第 1 行是测量集名称，第 2 行是测量对象，第 3 行开始是数据行，前 3 列为测量周期、开始时间、结束时间，第 4 列起与测量对象一一对应。

共享一个纯解析/校验工具，不建立规则依赖；三个领域分别解析、聚合并产出自己的 `RuleResult`。呼叫领域根据呼叫请求、请求成功、请求失败计算并检查成功率和失败率；统计峰值、最大并发等容量型指标只展示，不派生成功/失败率。阈值从 `deploy/config/kpi_rules.yaml` 读取，结论保留阈值来源、输入时区和来源文件证据。旧通用规则 `kpi.threshold` 与新格式冲突，计划下线并由三条领域规则替代。

## 技术上下文

**语言/版本**：Python 3.11+；当前开发与验证使用 Python 3.12

**主要依赖**：FastAPI、Pydantic v2、structlog、pytest、Ruff；CSV 解析使用 Python 标准库 `csv`，不新增依赖

**存储**：SQLite 保存任务元数据；任务现场、规则 JSON、日志和报告保存在 `output/<task_id>/` 文件系统

**测试**：`pytest` 覆盖解析、阈值、隔离、单规则重跑和契约一致性；`ruff` 做 lint/format

**目标平台**：单节点 Linux/macOS 服务；本地 CLI 与在线 API 共用执行器

**项目类型**：FastAPI 后端 + React/Vite 前端 + 离线 CLI

**性能目标**：代表性离线包在单节点顺序执行中完成；解析器有显式行数、列数、文件大小和文件数预算

**约束条件**：完全离线；一个包、一个任务、一个输出目录；不修改原始上传包；时间持久化为 UTC；普通规则不得互相消费结果

**规模/范围**：第一版覆盖 `api`、`media`、`call` 三个领域和四个统计周期；只对呼叫成功率和失败率做业务阈值告警

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结论 | 说明 |
| --- | --- | --- |
| 离线优先 | 通过 | 只读取解压后的任务现场 CSV，不连接被检系统 |
| 一个包、一个任务 | 通过 | 结果仍按 `task_id` 输出，不新增任务目录维度 |
| 契约驱动 | 通过 | 继续使用既有 `RuleResult` / `Metric` / `Finding`；`metadata` 与 `series` 承载明细，不破坏既有字段 |
| 模式同构 | 通过 | 解析器和三条规则由 CLI/API 共用执行器加载 |
| 巡检器插件架构 | 通过 | 新增普通规则注册，不修改核心调度器业务逻辑 |
| 源文件显式匹配 | 通过 | 每条规则声明领域专属 `source_patterns`，不消费其他规则结果 |
| 增量重跑 | 通过 | 新规则无需 prepare，`run_rule_with_deps()` 可直接重跑；单文件异常在规则结果内隔离 |
| 容错 | 通过 | 无匹配文件跳过；坏文件/坏行记录结构化失败，不中断同领域其他文件或其他领域 |
| 幂等与可追溯 | 通过 | 确定性解析、确定性 finding id；结果保留来源路径、行号、原始值和阈值 |
| 轻量默认 | 通过 | 使用标准库 `csv`，不引入外部服务、数据库或消息代理 |
| 安全解压与资源预算 | 通过 | 复用解压安全边界，解析阶段增加 KPI 输入预算 |

**阶段 1 复查结论**：设计未引入新外部服务、公共 prepared 数据或跨规则依赖；无宪法违规。

## 项目结构

### 文档（本功能）

```text
specs/006-csv-kpi-inspection/
├── plan.md              # 本文件（$speckit-plan 命令输出）
├── research.md          # 阶段 0 输出
├── data-model.md        # 阶段 1 输出
├── quickstart.md        # 阶段 1 输出
├── contracts/           # 阶段 1 输出
│   ├── kpi-csv-input.md
│   ├── kpi-rules.md
│   └── kpi-thresholds.md
└── tasks.md             # 阶段 2 输出（后续 $speckit-tasks 创建）
```

### 源代码（仓库根目录）

```text
app/
├── inspectors/
│   └── kpi/
│       ├── common.py        # 共享 CSV 读取、时间规范化、结果聚合 helper
│       ├── api.py           # kpi.api 规则
│       ├── media.py         # kpi.media 规则
│       └── call.py          # kpi.call 规则
├── models/
│   └── schemas.py           # 仅复用既有 RuleResult / Metric / Finding 契约
└── services/
    └── executor.py          # 不修改业务编排，仅沿用现有匹配、异常隔离和校验

deploy/
└── config/
    └── kpi_rules.yaml       # 领域、指标映射、周期阈值、输入时区和解析预算

tests/
├── test_kpi_csv_rules.py    # 解析、阈值、容量指标、错误隔离
├── test_kpi_single_rule.py  # 单规则匹配、重跑和 skip
└── test_baseline_pipeline.py# 更新规则计数与样例包，避免旧规则断言残留

web/
└── src/
    ├── api/client.ts        # 仅在 OpenAPI 变化时重新生成；本计划默认不修改接口契约
    └── components/KpiDetailTable.tsx  # 按需展示 metadata 中的文件/记录明细（实现阶段可合并到规则详情页）

docs/
└── architecture.md          # 更新 KPI 规则说明与旧 kpi.threshold 下线说明
```

**结构决策**：沿用现有 `app/inspectors/**` 自动注册架构。三条领域规则是普通规则；共享 helper 只是可复用函数库，不是规则，也不产生跨规则输入。第一版不引入规则私有 prepare：输入文件量可控、解析逻辑是规则执行的一部分，直接解析可避免 prepared 缓存只感知 owner 文件变化而漏检共享 helper/config 变化的问题。

## 复杂度跟踪

> **仅在宪法检查存在需要说明的违规时填写**

无需填写：设计未发现需要豁免的宪法违规。
