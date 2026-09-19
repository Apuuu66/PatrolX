# 实现计划：KPI 基础数据管理

**分支**：`feature/013-kpi-base-data-management` | **日期**：2026-09-19 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/013-kpi-base-data-management/spec.md` 的功能规格与全部澄清结论。

## 摘要

把当前单一 `deploy/data/kpi_catalog.json` 一次性迁移为按类型拆分的 KPI 配置目录。基础指标与预留单位保存在 `base/`，通用规则、指标规则、阈值、容量规则和展示规则保存在 `rules/`。Git 继续作为这些文件的权威来源；SQLite 继续保存业务域分类状态、修订单和审计。

离线资源 CSV 导入只完整替换 `base/metrics.json` 和 `base/units.json`，不会改写规则文件。目录聚合时执行严格校验，阻止重复资源、缺失引用、公式循环和无效规则进入任务。任务快照路径和契约保持不变，快照继续是历史结果追溯的唯一来源；不新增用户维护的配置版本。单位只预留，不在本迭代解析、换算或配置。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript + React 18。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、pytest、React Router、Ant Design、Vite。

**存储**：

- Git：
  - `deploy/data/kpi/base/metrics.json`
  - `deploy/data/kpi/base/units.json`
  - `deploy/data/kpi/rules/common.json`
  - `deploy/data/kpi/rules/metric-rules.json`
  - `deploy/data/kpi/rules/thresholds.json`
  - `deploy/data/kpi/rules/capacity-rules.json`
  - `deploy/data/kpi/rules/display-rules.json`
- SQLite：`KpiClassification`、`KpiClassificationRevision`、`KpiClassificationAudit`。
- 输出现场：`output/<task_id>/kpi/kpi_catalog_snapshot.json`。

**测试**：pytest 覆盖拆分文件加载、目录聚合校验、CSV 完整替换、规则引用保护、确定性重跑、缺失/损坏快照边界、分类状态与审计兼容、API/CLI 结果一致性与现有快照兼容。

**目标平台**：本地 CLI 与在线 FastAPI/Web 共用同一套 KPI 目录服务和巡检逻辑；桌面浏览器优先。

**性能目标**：当前基础指标全集在 1000 行以内；目录每个任务只加载一次，拆分文件读取不引入每条规则重复 IO。

**约束条件**：

- 离线优先，不连接被检系统，不做在线采集。
- 一个包、一个任务、一个输出目录。
- 旧单文件迁移后不再是权威配置，运行时不回退。
- 不引入独立 `catalog_version`、基础数据版本、规则版本或界面配置版本。
- 单位能力只预留，`unit_key` 当前保持 `null`。
- OpenAPI 不因本功能扩展业务接口；若实现需要新增错误响应字段，先同步契约再实现。

## 宪法检查

*门禁：阶段 0 研究后通过；阶段 1 设计后复核通过。*

| 原则 | 结论 | 依据 |
| --- | --- | --- |
| 离线优先 | 通过 | 资源 CSV 只能通过离线命令导入，不新增运行时上传或在线采集。 |
| 一个包、一个任务 | 通过 | 任务快照仍写入该任务唯一输出目录；全局配置不进入任务隔离边界。 |
| 契约驱动 | 通过 | API 与快照契约不扩展业务字段；`base_data_version` 保留既有字段语义并收敛为内容指纹。 |
| 模式同构 | 通过 | CLI 和 API 通过同一 `load_kpi_catalog()` 与任务 KPI 配置服务读取拆分配置。 |
| 巡检器插件架构 | 通过 | 只调整 KPI 配置加载与基础数据组织，不把 KPI 语义硬编码进调度器。 |
| 源文件显式匹配 | 通过 | 不改变 KPI 巡检器的 `source_patterns` 和匹配方式。 |
| 增量重跑 | 通过 | 已有有效快照复用；指定规则重跑缺快照时失败，不伪装历史配置。 |
| 解压先行 | 通过 | 不改变 `EXTRACT → PREPARE → INSPECT` 顺序。 |
| 规则私有预处理 | 通过 | 不改变 KPI 私有 prepare 边界和缓存语义。 |
| 幂等与可追溯 | 通过 | 配置文件和快照使用确定性 JSON；快照记录任务执行时完整配置。 |
| 轻量默认 | 通过 | 使用固定七个 JSON 文件和标准库 JSON 解析，不新增数据库、服务或版本管理系统。 |
| 容错 | 通过 | 单个配置文件错误显式失败；不回退旧文件继续执行新任务。 |
| 安全解压 | 通过 | 不处理巡检任务包内配置，不影响解压安全防护。 |

阶段 1 复核结论：设计未引入在线导入、第二套构建入口、独立版本表或跨任务共享状态；快照仍在任务目录内且只读。宪法检查保持通过。

## 项目结构

### 文档（本功能）

```text
specs/013-kpi-base-data-management/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── kpi-split-config.md
└── tasks.md              # 阶段 2 由 $speckit-tasks 生成
```

### 源代码（仓库根目录）

```text
app/
├── core/
│   └── config.py                        # 替换单文件设置为 KPI 配置目录及固定文件路径
├── inspectors/
│   └── kpi/
│       └── catalog.py                   # 拆分文件加载、目录聚合和严格校验
├── services/
│   ├── kpi_catalog.py                   # 组合拆分配置与 SQLite 分类，维护快照边界
│   └── kpi_resources.py                 # 基础资源查询和分类引用保护
└── tools/
    └── kpi_catalog.py                   # 离线 CSV 只写 base/，不写 rules/

deploy/
└── data/
    └── kpi/
        ├── base/
        │   ├── metrics.json
        │   └── units.json
        └── rules/
            ├── common.json
            ├── metric-rules.json
            ├── thresholds.json
            ├── capacity-rules.json
            └── display-rules.json

tests/
├── test_kpi_catalog_composition.py
├── test_kpi_catalog_split_config.py     # 新增：拆分契约、聚合校验和内容指纹
├── test_kpi_catalog_tool.py             # 扩展：CSV 导入边界
├── test_kpi_classification_db.py        # 扩展：分类状态、审计和重导入兼容
├── test_kpi_deterministic_rerun.py      # 新增：相同输入和快照的确定性结果
├── test_kpi_resource_api_v3.py          # 扩展：分类 API 与禁止运行时导入
├── test_kpi_resource_metrics.py
├── test_kpi_task_snapshot.py
└── test_kpi_task_snapshot_missing.py    # 新增：指定规则重跑缺快照

docs/
├── architecture.md
├── data-model.md
└── design/
    ├── entrypoints.md
    └── task-rerun.md
```

**结构决策**：沿用现有 Python 后端 + 少量前端消费结构，不新增独立模块。前端 API 客户端不需要重新生成，除非契约校验发现必须补齐错误字段；即便如此也先修改 OpenAPI。

## 实现策略

1. **配置迁移**
   - 从现有单文件内容生成七个拆分 JSON。
   - 提交拆分文件并删除旧 `deploy/data/kpi_catalog.json`。
   - 不实现运行时旧文件迁移或回退。

2. **目录加载**
   - 将 `settings.kpi_catalog_path` 调整为 KPI 配置目录，并暴露固定子路径。
   - `load_kpi_catalog()` 逐个读取固定文件，使用严格 JSON 解析和现有规则校验函数。
   - 聚合后的内存对象继续是 `KpiGitCatalog`，降低下游改动范围。
   - 派生 `base_data_version` 时按固定相对路径顺序和文件字节计算 SHA-256。

3. **校验增强**
   - 保留基础资源、公式、阈值、容量、展示规则校验。
   - 增加跨文件重复检查和错误上下文，错误消息带相对文件路径。
   - 公式循环检测继续覆盖 numerator、denominator 和 fallback inputs。
   - `unit_key` 只允许 `null`；不新增单位解析或换算逻辑。

4. **离线导入**
   - 修改工具 CLI 为 `--data-dir deploy/data/kpi`。
   - 生成器只写 `metrics.json` 和 `units.json`。
   - 写入前先聚合既有规则文件做完整校验；任一校验失败则不替换目标文件。
   - CSV 完整替换基础指标；缺失旧指标在规则引用时导致失败。

5. **快照与重跑**
   - 新任务逻辑不变：首次需要 KPI 配置时生成快照。
   - 已有有效快照复用，不因配置变化刷新。
   - 指定规则重跑入口在读取 KPI 配置前检查已有任务的快照缺失场景，显式失败。
   - 全量重跑保持“不覆盖有效快照”的现有语义。
   - 不新增任务输出清理重建能力；该需求留在路线图。

6. **文档同步**
   - 更新架构、数据模型、入口命令和任务重跑文档中的旧单文件描述。
   - 确认路线图保留“任务重建重跑”后续项。

## 验证计划

实现完成后至少执行：

```bash
python build.py lint
python build.py test
```

本功能改变 KPI 配置加载、任务快照和离线导入流程，另执行：

```bash
python build.py verify
```

如果实现过程中需要修改 OpenAPI 或 Pydantic 输出契约，先执行：

```bash
python build.py contract
python build.py gen-web-api
```

关键验证场景：

- 拆分目录完整时可创建新任务快照。
- 任意文件缺失、损坏或引用错误时任务不创建新快照且不回退。
- 资源 CSV 刷新只改基础文件。
- 删除被规则引用的基础指标时导入或加载失败。
- 修改规则后旧任务快照不变，新任务快照包含新规则。
- 指定规则重跑在快照缺失时失败。
- 相同输入包与相同配置快照产生一致 KPI 结果。
