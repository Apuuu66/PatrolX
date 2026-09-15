# 实现计划：KPI 指标字典与分组展示

**分支**：`010-kpi-metric-catalog` | **日期**：2026-09-16 | **规格**：[spec.md](./spec.md)

**输入**：来自 `specs/010-kpi-metric-catalog/spec.md` 的功能规格。

## 摘要

为 KPI 巡检建立版本化、按领域拆分的指标配置：`deploy/config/kpi/` 下由 `common.yaml` 承载公共配置，`call.yaml`、`api.yaml`、`media.yaml` 分别承载本领域指标定义、别名、公式、阈值和容量语义。规则执行时加载并校验配置，把源数据列名归一到稳定 `metric key`，按声明公式计算派生指标，按指标类型聚合主值，并把指标目录、指标结果、溯源信息和未分类指标写入 `RuleResult.metadata`。

前端继续通过既有规则详情接口获得 `RuleResult`，用新增的 KPI 元数据渲染重点卡片、语义分组目录和详情抽屉；原始记录改为通过新增分页接口按需查询。公共契约只做兼容新增，不修改既有 `RuleResult`、`Metric`、`Finding` 字段语义。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript + React 18。

**主要依赖**：FastAPI、Pydantic v2、PyYAML、SQLAlchemy、structlog；Ant Design 5、ECharts 5、Vite、openapi-typescript。

**存储**：静态配置存放在 `deploy/config/kpi/`；任务结果继续写入 `output/<task_id>/rules/<rule_code>.json`；任务索引继续使用 SQLite。不新增数据库表，不提供在线配置编辑。

**测试**：后端 `pytest`；质量门禁 `ruff`；前端 `npm run build`；契约校验与生成使用 `python build.py contract`、`python build.py gen-web-api`。

**目标平台**：单节点离线巡检服务与桌面优先 Web 页面；本地 CLI 与在线 API 共用执行器。

**性能目标**：在既有资源预算内支持 50+ 指标、多文件、多周期解析；详情首屏只渲染摘要和指标目录，不渲染全部原始记录。记录分页接口默认页大小 50。

**约束条件**：
- 不连接被检系统，不引入在线采集。
- 一个压缩包、一个任务、一个输出目录。
- 配置只支持新增指标和追加别名，不迁移历史结果。
- 普通规则不消费其他普通规则结果；派生公式只允许同一 KPI 领域内引用。
- 既有 `RuleResult`、`Metric`、`Finding`、状态和字段语义保持兼容。
- UTC 存储；时间字段继续使用 `*_at` 命名。

**规模/范围**：当前覆盖 `kpi.api`、`kpi.media`、`kpi.call` 三个规则领域；第一版不做指标修改、删除、合并、重命名、废弃或在线维护界面。

## 宪法检查

*阶段 0 前检查：通过。*

- 离线优先：仅解析任务包内文件和静态配置，无外部连接。
- 一个包、一个任务：不改变 `task_id` 和输出目录隔离。
- 契约驱动：新增记录查询接口和 `exclude_records` 查询参数必须先更新 `docs/api/openapi.yaml`；`metadata` 内的 KPI 结构以兼容新增方式写入。
- 模式同构：CLI 与 API 继续共用同一规则、配置加载器、聚合器和结果结构。
- 巡检器插件架构：KPI 逻辑收敛在 `app/inspectors/kpi/` 共享 helper，不在调度器硬编码业务规则。
- 规则隔离：公式输入和输出必须位于同一领域；不建立规则间依赖。
- 安全与容错：单文件解析失败继续返回行级/文件级错误；未分类指标不改变规则状态。
- 历史现场：不修改已有 `output/<task_id>/` 结果；单规则重跑按新配置生成新结果。

*阶段 1 后复查：通过。*

- 公共 API 采用兼容新增：新增 KPI 记录查询端点、`exclude_records` 可选参数和 OpenAPI 元数据 schema 说明。
- KPI 领域配置从单一混合文件迁移到分类目录，属于部署配置演进；历史结果不迁移。
- 无需要记录的宪法豁免。

## 项目结构

### 文档（本功能）

```text
specs/010-kpi-metric-catalog/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── kpi-config.md
│   ├── api-rule-metadata.md
│   └── kpi-records-api.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── inspectors/kpi/
│   ├── catalog.py          # 新增：配置模型、加载、校验、归一化、聚合、溯源 helper
│   ├── common.py           # 调整：保留 CSV 解析并接入目录化配置
│   ├── call.py             # 调整：生成 KPI 结果元数据
│   ├── api.py              # 调整：生成 KPI 结果元数据
│   └── media.py            # 调整：生成 KPI 结果元数据
├── models/schemas.py       # 如契约实现需要，新增 KPI 元数据辅助模型；不修改既有字段语义
├── services/
│   ├── tasks.py            # 调整：可选排除 KPI 原始记录
│   └── kpi_records.py      # 新增：从规则结果投影分页原始记录
└── api/routes.py           # 调整：新增 KPI 记录查询路由和 exclude_records 参数

deploy/config/kpi/
├── common.yaml
├── call.yaml
├── api.yaml
└── media.yaml

web/src/
├── pages/RuleDetailPage.tsx
└── components/
    ├── KpiInspectionPanel.tsx
    ├── KpiMetricCard.tsx
    ├── KpiMetricCatalog.tsx
    ├── KpiMetricDrawer.tsx
    ├── KpiMetricTrend.tsx
    └── KpiDetailTable.tsx

tests/
├── test_kpi_catalog_config.py
├── test_kpi_catalog_aggregation.py
├── test_kpi_csv_rules.py
├── test_kpi_records_api.py
├── test_kpi_single_rule.py
└── test_contract.py
```

**结构决策**：KPI 配置模型与解析器放在规则领域内，避免污染通用调度器；配置文件按领域拆分，公共设置单独维护。前端新增一组 KPI 展示组件，`RuleDetailPage` 负责路由、接口调用和组件编排。

## 设计方案

### 配置组织

```text
deploy/config/kpi/
├── common.yaml
├── call.yaml
├── api.yaml
└── media.yaml
```

- `common.yaml`：`version`、`input_timezone`、解析预算。
- `<domain>.yaml`：`domain`、`metrics[]`、`thresholds`、`capacity_metrics`。
- 领域配置必须与文件名和 `domain` 一致；加载器拒绝未知领域文件。
- 新增指标或别名只修改目标领域文件；KPI 无关的 `deploy/config/*.yaml` 不迁移、不修改语义。
- 删除 `deploy/config/kpi_rules.yaml`，代码和测试统一切换到新目录；已有任务输出不改写。

### 指标字典与解析

- 每个指标使用稳定 `key`，规则内唯一；中文名、英文名、单位、类型、分组、展示角色、来源类型和聚合方式随指标登记。
- 别名按 `NFKC`、去除首尾空白、压缩连续空白、`casefold` 归一化后精确匹配；不做模糊和语义推测。
- 同一领域内归一化别名冲突、稳定 key 重复、阈值引用未知指标、公式输入缺失或循环依赖都必须导致配置加载失败，规则返回 `error`。
- 源数据列保持原始名作为证据；映射后的计算使用稳定 key。
- 未登记列进入 `unclassified_metrics`，保留原始列名、来源文件、记录数和样例值；不参与已登记指标聚合，也不改变规则状态。

### 派生指标

- 第一版公式使用声明式 `ratio`：`numerator`、`denominator`、可选 `denominator_fallback`。
- 可选兜底分母使用声明式求和，例如 `call_success_count + call_failure_count`；不执行动态表达式。
- 配置公式存在时优先计算派生值；同名列只进入 `provenance.direct_cross_reference`。
- 公式必要输入缺失、分母为零或类型不可用时输出 `unavailable` 与原因；不使用直接同语义值兜底，不产生业务失败结论。
- 公式输入和输出必须属于同一领域；依赖图用于校验循环依赖。

### 主值聚合

- 比率类：先跨文件、跨周期汇总分子和分母，再计算比率。
- 计数类：求和。
- 容量类：取最大值。
- 时延类：取最大值或配置分位。
- 其他统计类使用配置声明的聚合方式；结果必须携带实际聚合方式。
- 派生比率不在记录级先平均。

### 规则结果与公共契约

- `RuleResult` 顶层 `metrics` 保持既有执行统计指标；KPI 业务指标结果写入 `metadata.kpi_results`。
- `metadata` 新增：
  - `metric_catalog[]`：展示名、别名、类型、分组、角色、单位、来源类型、公式。
  - `kpi_results[]`：主值、可用性、状态、阈值、越限数量、序列、来源文件、聚合方式和溯源。
  - `unclassified_metrics[]`：未登记列信息。
  - `kpi_files[]`：保留文件摘要；兼容既有结构。
- 新任务 KPI 元数据 `version=2`；历史结果保持原值并继续按旧表展示。
- `getRuleResult` 增加可选 `exclude_records=true`，用于详情首屏不返回 KPI 原始记录；默认行为不变。
- 新增 `GET /api/v2/tasks/{task_id}/rules/{rule_code}/kpi/records`，按来源文件、周期、指标和异常状态分页查询。
- `rule_version` 随 KPI 逻辑变化升级；本地 CLI 和在线 API 输出结构一致。

### 前端展示

- `RuleDetailPage` 对 `metadata.version=2` 的 KPI 结果使用 `exclude_records=true` 和新的 KPI 面板。
- 首屏：规则状态、关键摘要、重点指标卡片、越限和不可用数量。
- 目录：按质量、业务量、容量、时延和其他分组；支持状态筛选与中英文/稳定 key 搜索。
- 卡片：展示主值、单位、阈值方向、状态或中性标识；无阈值不显示通过/失败。
- 抽屉：展示定义、公式、输入值、直接来源交叉参考、缺失原因、序列和来源文件。
- 原始记录：抽屉内按需调用分页接口；不在首屏渲染 `metadata.kpi_files[].records`。
- 历史结果没有 `metadata.version=2` 时继续使用现有明细表，不伪造目录。

### 配套更新

- `docs/api/openapi.yaml`：新增 KPI 记录查询契约、`exclude_records` 参数、KPI 元数据 component schema 和示例。
- 前端 API 客户端：只通过 OpenAPI 生成代码更新。
- 报告 HTML：保持既有规则摘要；本版不要求完整渲染目录式 KPI 页面。
- 文档：同步架构和配置机制中 KPI 配置路径。

## 复杂度跟踪

无宪法豁免或复杂度违规。
