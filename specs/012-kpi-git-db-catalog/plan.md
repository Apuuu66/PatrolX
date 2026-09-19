# 实现计划：KPI 基础数据入库与分类状态存储

**分支**：`feature/kpi-git-db-catalog` | **日期**：2026-09-19 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/012-kpi-git-db-catalog/spec.md` 的功能规格与全部澄清结论。

## 摘要

把 KPI 权威基础指标、预留单位字典和公式、阈值、容量、展示规则统一保存在单一 Git JSON 文件中；数据库只保存可变业务域分类状态和审计。离线工具负责从资源 CSV 生成确定性的基础数据，并保留人工维护的规则定义。运行时组合 Git 基础数据与数据库分类状态，形成有效 KPI 指标目录；任务启动时写入完整配置快照，保证历史结果自解释。前端「基础指标配置」只提供查询和分类能力，移除在线 CSV 导入；同时通过路由懒加载与 vendor chunk 拆分修复 Vite 大包告警。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript + React 18。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、pytest、React Router、Ant Design、Vite。

**存储**：

- Git：`deploy/data/kpi_catalog.json` 保存指标、单位预留和规则定义。
- SQLite：分类状态、分类修订、分类审计。
- 输出现场：`output/<task_id>/kpi/kpi_catalog_snapshot.json` 保存任务配置快照。

**测试**：pytest 覆盖生成器、目录组合、数据库事务、审计、引用保护、API 契约、CLI/API 一致性与任务快照；前端执行 TypeScript build 和关键单测。

**目标平台**：本地 CLI 与在线 FastAPI/Web 共用同一套巡检逻辑；桌面浏览器优先。

**项目类型**：离线巡检系统 + 本地 Web 管理界面。

**性能目标**：

- 1000 行以内基础全集加载与分页展示满足 2 分钟内可用。
- 一次最多 100 个指标的批量分类在事务内 1 分钟内完成。
- KPI 目录解析在单任务内缓存一次，避免每条规则重复读取。

**约束条件**：

- 离线优先，不连接被检系统，不做在线采集。
- 本地与在线共用目录组合、规则执行和结果契约。
- 数据库不可用或校验失败时任务失败，不回退旧 YAML。
- 单位能力只预留，不运行时消费 `ME_*` 到 `UNIT_*` 的映射。
- 破坏性 KPI 资源 API 变更进入 `/api/v3`。

**规模/范围**：首版支持 1000 行以内资源全集、四个分类值（未分类 + 三个业务域）、最多 100 个指标的批量分类。

## 宪法检查

*门禁：阶段 0 研究后通过；阶段 1 设计后复核通过。*

| 原则 | 结论 | 依据 |
| --- | --- | --- |
| 离线优先 | 通过 | 只新增离线资源 CSV 生成工具，不新增被检系统连接或在线采集。 |
| 单包 / 单任务 / 单输出目录 | 通过 | 快照写入当前任务目录；分类状态是全局治理数据，不改变任务隔离模型。 |
| 本地与在线同构 | 通过 | 两个模式调用同一 KPI 目录服务并读取同一 SQLite 分类状态；数据库不可用都失败。 |
| OpenAPI 唯一契约源 | 通过 | 先更新 `docs/api/openapi.yaml`，再实现 `/api/v3` 并生成前端客户端。 |
| 契约兼容 | 通过 | 不修改既有字段语义；KPI 资源 API 的破坏性变更进入 `/api/v3`。 |
| 规则独立 | 通过 | 三条 KPI 领域规则继续声明自己的 `source_patterns`，共享目录服务不是普通规则消费普通规则数据。 |
| 不硬编码业务规则 | 通过 | 公式、阈值、容量和展示规则由 Git JSON 提供；调度器不写 KPI 语义。 |
| 单点解析失败隔离 | 通过 | 数据文件解析失败会让目录加载显式失败；KPI CSV 内单行错误仍按既有规则隔离。 |
| 原始包只读 | 通过 | 生成器只读仓库外用户提供的资源 CSV，不处理巡检任务原始包。 |
| UTC 与 `*_at` | 通过 | 审计、修订和快照时间使用 UTC，字段使用 `created_at` / `updated_at` / `captured_at`。 |
| 历史可追溯 | 通过 | 任务快照保存完整有效指标与完整规则定义，单规则重跑优先复用快照。 |

阶段 1 复核结论：设计未引入外部数据库、在线采集或第二套构建入口；快照只属于任务输出现场，不作为配置回退源。宪法检查保持通过。

## 项目结构

### 文档（本功能）

```text
specs/012-kpi-git-db-catalog/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── kpi-catalog-json.md
│   ├── kpi-resource-api.md
│   └── task-catalog-snapshot-api.md
└── tasks.md
```

### 源代码

```text
app/
├── api/
│   └── router.py                         # KPI 资源 v3 API、任务快照 API
├── core/
│   └── config.py                         # 增加 Git KPI 目录路径配置
├── inspectors/
│   └── kpi/
│       ├── call.py                       # 改读任务快照目录
│       ├── api.py                        # 改读任务快照目录
│       ├── media.py                      # 改读任务快照目录
│       ├── catalog.py                    # JSON 规则模型、校验与组合
│       └── common.py                     # 解析、聚合、metadata 版本信息
├── models/
│   ├── db.py                             # 分类、修订、审计表
│   └── schemas.py                        # 资源、分类、快照契约模型
├── services/
│   ├── kpi_catalog.py                    # Git + DB 组合与任务快照服务
│   ├── kpi_resources.py                  # 改为数据库分类服务，移除 YAML 读写
│   └── tasks.py                          # 执行前确保 KPI 配置快照
└── tools/
    └── kpi_catalog.py                    # 离线 CSV -> Git JSON 生成器

deploy/
└── data/
    └── kpi_catalog.json                  # 单一权威基础与规则文件

web/src/
├── layouts/MainLayout.tsx                # 「基础指标」导航
├── pages/KpiResourcesPage.tsx            # 查询与分类，无导入
└── App.tsx                               # 路由级懒加载

tests/
├── test_kpi_catalog_generator.py
├── test_kpi_catalog_composition.py
├── test_kpi_classification_db.py
├── test_kpi_resource_api_v3.py
├── test_kpi_task_snapshot.py
└── test_kpi_single_rule.py
```

**结构决策**：沿用现有 `api → services → inspectors/models` 分层。`app/tools/` 只承载离线维护命令，不进入 API 或巡检器执行路径。`deploy/data/` 用于版本化基础数据，避免和可部署运行配置混淆。

## 技术设计

### 1. Git JSON

权威文件是 `deploy/data/kpi_catalog.json`，schema version 为 1：

```json
{
  "schema_version": 1,
  "source_csv_sha256": "64 位十六进制",
  "metrics": [
    {
      "resource_id": "ME_21002",
      "key": "me_21002",
      "name_zh": "创建媒体资源请求次数",
      "name_en": "Create Media Resource Request Count",
      "unit_key": null
    }
  ],
  "units": [
    {
      "resource_id": "UNIT_1001",
      "key": "unit_1001",
      "name_zh": "次",
      "name_en": "count"
    }
  ],
  "rules": {
    "common": {
      "input_timezone": "Asia/Shanghai",
      "budgets": {
        "max_files": 2000,
        "max_records": 500000
      }
    },
    "metric_rules": [
      {
        "key": "me_21002",
        "metric_type": "count",
        "semantic_group": "traffic",
        "display_role": "context",
        "unit": "次",
        "source_type": "raw",
        "aggregation": {"kind": "sum"}
      }
    ],
    "thresholds": [
      {
        "domain": "call",
        "metric_key": "me_21003",
        "label": "呼叫成功率",
        "direction": "min",
        "default": 99.0,
        "periods": {"5": 99.0, "15": 99.0, "30": 99.0, "60": 99.0}
      }
    ],
    "capacity_rules": [
      {
        "source_name": "最大并发",
        "metric_key": "me_21004",
        "semantics": "concurrency",
        "status": "confirmed"
      }
    ],
    "display_rules": [
      {"domain": "call", "metric_key": "me_21003", "role": "highlight"}
    ]
  }
}
```

校验规则：

- 顶层和 `rules` 只允许声明字段，未知字段失败。
- `metrics` / `units` / `metric_rules` / `thresholds` / `capacity_rules` / `display_rules` 内 key 唯一。
- `resource_id` 必须以 `ME_` 或 `UNIT_` 开头；稳定 key 是小写资源 ID，由生成器派生。
- `ME_` 与 `UNIT_` 资源 ID 全局唯一，不得跨前缀复用。
- 中文名必填且保留原文；英文名必填；名称不做括号拆分或语义推断。
- `metrics[].unit_key` 当前必须为 `null`；可以指向 `units[].key` 的解析能力留待后续版本。
- `metric_rules[].key`、阈值 / 容量 / 展示规则引用的 `metric_key` 必须存在于 `metrics`。
- 公式输入必须存在于基础 `metrics`，且无循环依赖。
- 展示规则不能与 `metric_rules[].display_role` 对同一指标和领域声明冲突。
- 版本不写入文件；加载器对文件字节计算 `base_data_version`。

### 2. 资源 CSV 生成器

输入表头固定为 `资源id,中文描述,英文描述`，UTF-8 优先；错误必须带行号和资源 ID。生成器：

- 逐行解析并立即收集所有错误，全部错误一次性报告。
- 校验空名称、非法资源 ID、重复 ID、重复稳定 key。
- `ME_*` 生成基础指标，`UNIT_*` 生成预留单位；其他前缀失败。
- 稳定 key 使用小写资源 ID，不引入别名。
- `metrics[].unit_key` 固定为 `null`；不做缺失单位补默认值。
- 输出 `source_csv_sha256`，不输出时间、用户、类型推断或业务归属。
- 读取既有输出 `rules` 并原样保留；输出前重新校验规则引用。
- 通过临时文件原子替换输出，写入失败时不破坏旧文件。

### 3. 数据库模型

```text
kpi_classifications
- metric_key TEXT PRIMARY KEY
- domain TEXT NULL                 -- call/api/media；NULL 表示未分类
- created_at TIMESTAMP WITH TIME ZONE
- updated_at TIMESTAMP WITH TIME ZONE

kpi_classification_revisions
- id INTEGER PRIMARY KEY CHECK (id = 1)
- revision INTEGER NOT NULL DEFAULT 0
- updated_at TIMESTAMP WITH TIME ZONE

kpi_classification_audits
- id INTEGER PRIMARY KEY AUTOINCREMENT
- metric_key TEXT NOT NULL
- operation TEXT NOT NULL          -- classify / unclassify
- operator TEXT NOT NULL
- previous_domain TEXT NULL
- next_domain TEXT NULL
- result TEXT NOT NULL             -- success
- detail JSON NULL
- operated_at TIMESTAMP WITH TIME ZONE
```

服务行为：

- `GET` 资源列表把 Git 基础数据与数据库当前状态组合成分页结果。
- `PUT` 分类使用 `unclassified / call / api / media`；内部把 `unclassified` 写成 `NULL`。
- 单条和批量分类共用一个事务；不存在指标、目标域非法、跨域引用保护失败都会回滚。
- 已被公式、阈值或容量规则引用且已有分类的指标，不能改为其他域或未分类；从未分类到首次分类允许。
- 每个成功目标指标写一条审计；批量请求只递增一次全局修订号。
- API 显式传 `operator`；本地治理入口固定传 `cli`。
- 基础数据移除指标后，分类行保留但标记为失效；恢复同名基础指标后复用状态。

### 4. 有效目录与任务快照

`app/services/kpi_catalog.py` 负责加载和组合：

1. 读取并校验 Git JSON，计算 `base_data_version`。
2. 打开数据库读取分类修订与分类状态；数据库不可用时抛出任务级错误。
3. 组装有效指标：基础数据存在且 `domain` 为 `call/api/media`。
4. 按领域构建规则执行所需的 metric definitions、thresholds 和 capacity rules。
5. 构建任务快照并原子写入 `output/<task_id>/kpi/kpi_catalog_snapshot.json`。
6. 同一任务执行期间复用同一快照，三条领域规则不再分别读取 Git 或数据库。
7. 单规则重跑发现既有快照时直接读取，保证历史任务配置不变。
8. 快照缺失时加载当前配置并补写；快照损坏或校验失败时任务失败。

快照不提供手动刷新开关。修改分类或 Git 后，新任务使用新配置；旧任务必须继续使用旧快照。

### 5. KPI 巡检器改造

- `kpi.call`、`kpi.api`、`kpi.media` 从任务快照读取对应领域目录。
- 规则的 `source_patterns`、优先级、状态语义和现有结果契约保持不变。
- 源列匹配只使用基础 `name_zh` / `name_en` 的规范化文本；不引入新的别名机制。
- `metric_catalog`、`kpi_results`、`unclassified_metrics` 和 `kpi_files` 契约保持既有含义。
- `KpiMetadata` 增加 `base_data_version` 与 `classification_version`，用于结果级追溯。
- 旧 YAML 不被读取、更新或作为回退；`deploy/config/kpi/*.yaml` 在新模型启用后移除。
- 配置缺失导致的领域无匹配文件仍然返回 `skip`；目录校验失败返回 `error`，任务级数据库/快照错误则任务失败。

### 6. API 契约

新增 `/api/v3`：

- `GET /api/v3/kpi/resource-metrics`
  - 查询参数：`search`、`domain`、`include_missing`、`page`、`page_size`。
  - 响应：分页 items、统计、`base_data_version`、`classification_version`。
  - item 字段：`key`、`resource_id`、`name_zh`、`name_en`、`domain`、`missing_from_base`、`created_at`、`updated_at`。
- `PUT /api/v3/kpi/resource-metrics/classification`
  - 请求：`metric_keys[]`、`domain`（含 `unclassified`）、`operator`。
  - 不包含 `expected_revision`。
  - 响应：`classification_version`、`domain`、`metric_keys[]`、`audited_count`。
- `GET /api/v3/kpi/resource-metrics/classification-audits`
  - 查询参数：`metric_key`、`operator`、`domain`、`page`、`page_size`。
  - 按 `operated_at` 倒序返回审计分页；CLI 的 `operator` 固定为 `cli`。
- `GET /api/v3/tasks/{task_id}/kpi/catalog-snapshot`
  - 返回完整任务配置快照；任务不存在返回 404，快照缺失或损坏返回 409/500 错误码。

移除：

- `/api/v2/kpi/resource-metrics` 的 `POST` 在线 CSV 导入。
- `/api/v2` KPI 资源查询与分类端点，由 `/api/v3` 取代。
- 前端资源 CSV 上传入口和 `importKpiResourceMetrics` 客户端方法。

### 7. 前端改造

- 导航显示「基础指标」，页面标题显示「基础指标配置」，修复 `/kpi-resources` 高亮。
- 表格字段改为基础指标四字段加业务域和时间。
- 搜索支持资源 ID、中文名、英文名；筛选支持未分类与三个业务域。
- 批量分类支持改回未分类；请求带 `operator`，不带 `expected_revision`。
- 提供分类审计分页查看，支持指标、操作人和目标域过滤。
- 顶部展示基础数据版本缩略值与分类修订号。
- 移除 `Upload` / CSV 导入按钮和相关状态。
- 使用 OpenAPI 生成的 v3 类型与方法。
- `App.tsx` 对页面组件使用 `React.lazy` + `Suspense`。
- Vite 配置 `manualChunks` 拆分 `react`、`antd`、`echarts`；构建不应再出现 500 kB 主包告警。

### 8. 错误与可观测性

- 生成器错误码：`invalid_csv_header`、`invalid_resource_id`、`missing_name`、`duplicate_resource_id`、`duplicate_metric_key`、`unknown_resource_prefix`、`rule_reference_missing`。
- 目录错误码：`kpi_catalog_file_missing`、`kpi_catalog_invalid`、`kpi_classification_db_unavailable`、`kpi_snapshot_missing`、`kpi_snapshot_invalid`。
- API 错误沿用 `{code, message, detail}`。
- 结构化日志记录 `task_id`、`base_data_version`、`classification_version`、规则代码和失败原因；不记录完整大 JSON。
- KPI 规则结果 metadata 记录两个配置版本。

## 实施阶段

### 阶段 A：契约与模型

1. 更新 OpenAPI `/api/v3` 资源、分类、快照契约，并移除旧资源导入。
2. 更新 Pydantic 契约模型与数据库表模型。
3. 运行 `python build.py contract` 与 `python build.py gen-web-api`。

### 阶段 B：离线生成器

1. 实现资源 CSV 解析、校验、稳定 key 排序与确定性 JSON 输出。
2. 保留既有规则并校验引用。
3. 建立重复执行字节一致与非法输入失败测试。

### 阶段 C：数据库分类

1. 实现分类状态、修订与审计表。
2. 实现原子批量分类、引用保护与失效记录保留。
3. 覆盖 API operator、CLI `cli` operator、回滚和最后成功写入生效场景。

### 阶段 D：目录组合与快照

1. 实现 Git JSON 加载、版本计算和引用校验。
2. 实现数据库分类组合与按领域目录构建。
3. 实现任务快照写入、复用和损坏失败行为。

### 阶段 E：巡检器与旧配置退役

1. 三条 KPI 规则改读任务快照。
2. metadata 增加配置版本。
3. 删除旧 KPI YAML 和 YAML 资源库逻辑，确保无运行时回退。

### 阶段 F：前端

1. 接入 v3 资源与分类 API。
2. 移除 CSV 导入并展示配置版本。
3. 支持未分类回退和批量分类。
4. 懒加载路由并拆分 vendor chunks。

### 阶段 G：验证

1. 后端：lint、pytest、契约校验、前端客户端生成。
2. 全流程：`python build.py verify`。
3. 前端：`python build.py web-build` 且无 chunk 大小告警。
4. 审查任务快照、历史结果和单规则重跑行为。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 大量旧测试假设 YAML 事实来源 | 按契约重写测试，不保留 YAML 回退路径。 |
| 分类变更影响正在执行的任务 | 任务启动时固化快照，执行期间复用。 |
| 单规则重跑读取新配置污染历史 | 强制优先读取既有任务快照。 |
| 规则引用的基础指标被 CSV 更新移除 | 生成器输出前校验引用并失败。 |
| 单位预留被误当可用能力 | 模型、API、有效目录和 UI 均不映射或展示单位。 |
| API 破坏性变更影响外部调用方 | 契约更新为 `/api/v3`，前端同步迁移，文档标明移除的 v2 资源接口。 |

## 复杂度跟踪

无宪法违规，无需记录额外豁免。
