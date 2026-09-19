# 实现计划：KPI 按需分类与动态口径配置

**分支**：`015-kpi-dynamic-config` | **日期**：2026-09-19 | **规格**：[spec.md](spec.md)

**输入**：来自 `/specs/015-kpi-dynamic-config/spec.md` 的功能规格

## 摘要

将 KPI 资源全集与业务口径分离：基础资源继续通过离线 CSV 工具写入 Git JSON；分类之外的指标规则、公式、阈值、容量规则、展示规则和公共配置全部迁入数据库，并在前台维护。任务执行时组合基础资源、分类和动态规则生成不可变任务快照。任务详情提供按需分类线索，只处理当前数据包真实遇到的列。配置变更全部审计并递增 `rule_config_version`。不迁移现有 `rules/*.json`，功能完成时运行时退役这些文件。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript + React 18。

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、Vite、Ant Design、openapi-typescript。

**存储**：`deploy/data/kpi/base/` 保存基础资源和预留单位；SQLite 保存任务元数据、KPI 分类和 KPI 动态配置；`output/<task_id>/kpi/kpi_catalog_snapshot.json` 保存任务快照。

**测试**：pytest、Node.js built-in test、OpenAPI 契约校验、前端构建和本地全流程验证。

**目标平台**：桌面优先的本地/在线 Web 服务。

**项目类型**：FastAPI Web 服务 + React 单页前端 + 本地 CLI/执行器。

**性能目标**：任务线索列表加载不超过 2 秒；600+ 基础指标的分页查询保持现有页面响应体验。

**约束条件**：离线巡检、一个包一个任务、任务快照不可变、OpenAPI 唯一契约源、本地/在线模式同构、时间字段 UTC。

**规模/范围**：600+ 基础指标；单任务可能产生最多数百条线索；KPI 配置中心 8 类管理视图。

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 原则 | 结论 | 说明 |
| --- | --- | --- |
| 离线优先 | 通过 | 只处理已上传数据包；在线能力只维护配置，不采集被检系统数据。 |
| 一个包、一个任务 | 通过 | 配置按全局口径存储；任务结果和快照仍只按 `task_id` 隔离。 |
| 契约驱动 | 通过 | 新增 `/api/v4` 契约；先更新 `docs/api/openapi.yaml`，再更新 Pydantic 和生成客户端。 |
| 模式同构 | 通过 | CLI 与 API 使用同一配置服务和任务快照；本地模式不引入 Git 规则回退。 |
| 巡检器插件架构 | 通过 | 修改共享 KPI 配置加载，不硬编码业务指标或在调度器中引入规则依赖。 |
| 源文件显式匹配 | 通过 | 不改变 KPI 规则的 `source_patterns` 匹配方式。 |
| 增量重跑 | 通过 | 单规则重跑复用快照；全量重建才生成新快照。 |
| 解压先行 | 通过 | 保持 `EXTRACT → PREPARE → INSPECT`；快照仍在解压后生成。 |
| 规则私有预处理 | 通过 | 不新增跨规则 prepare 或规则间依赖。 |
| 幂等与可追溯 | 通过 | 配置保存写审计；快照原子写入；离线基础数据替换保持原子性。 |
| 轻量默认 | 通过 | 继续使用 SQLite 与文件输出，不引入外部数据库或规则引擎。 |
| 容错 | 通过 | 单文件解析失败不中断任务；线索解析单条失败不中断列表。 |
| 安全解压 | 通过 | 不修改解压实现和安全边界。 |

*设计后复查：通过。动态配置数据库是运行时状态，不改变离线巡检和任务隔离模型。*

## 项目结构

### 文档（本功能）

```text
specs/015-kpi-dynamic-config/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── kpi-dynamic-config.yaml
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── api/
│   └── router.py                        # 新增 /api/v4 配置与线索路由
├── core/
│   └── config.py                        # 只保留 base 路径；规则文件路径退役
├── inspectors/
│   └── kpi/
│       ├── catalog.py                   # 基础资源加载与有效配置构建校验
│       └── common.py                    # 继续消费任务快照；线索元数据保持兼容
├── models/
│   ├── db.py                            # KPI 动态配置、版本和审计表
│   └── schemas.py                       # v4 请求/响应与快照 v2 模型
├── services/
│   ├── kpi_catalog.py                   # 组合 Git 基础数据、DB 分类和 DB 规则；维护快照
│   ├── kpi_classification_clues.py      # 任务线索解析服务
│   ├── kpi_config.py                    # 动态配置校验、保存、审计服务
│   └── kpi_resources.py                 # 分类查询与引用保护
└── tools/
    └── kpi_catalog.py                   # 离线 CSV 只更新 base；执行 DB 引用保护

web/src/
├── api/
│   ├── client.ts                        # OpenAPI 生成
│   └── http.ts                          # 生成类型的轻量封装
├── components/
│   ├── KpiClassificationClues.tsx       # 任务详情线索列表
│   ├── KpiConfigAuditTable.tsx
│   ├── KpiFormulaEditor.tsx
│   ├── KpiThresholdEditor.tsx
│   └── kpiConfigModel.ts
└── pages/
    ├── KpiResourcesPage.tsx             # 升级为 KPI 配置中心入口
    └── TaskDetailPage.tsx               # 按需分类线索入口

deploy/data/kpi/
└── base/
    ├── metrics.json
    └── units.json

tests/
├── test_kpi_classification_clues.py
├── test_kpi_classification_db.py
├── test_kpi_config_api_v4.py
├── test_kpi_config_db.py
├── test_kpi_catalog_composition.py
├── test_kpi_offline_import_guard.py
├── test_kpi_snapshot_v2.py
├── test_kpi_task_snapshot.py
└── web/src/components/*.test.ts

docs/
├── api/openapi.yaml
├── architecture.md
└── data-model.md
```

**结构决策**：沿用现有分层，不新增独立应用或规则引擎。配置 CRUD 收敛到 `kpi_config.py`，快照组合仍由 `kpi_catalog.py` 负责，避免 API 层直接访问数据库。

## 实现策略

1. **数据来源切换**
   - 只加载 `base/metrics.json` 和 `base/units.json`；不再读取 `rules/*.json`。
   - 动态规则配置从 SQLite 读取；空表表示没有任何业务规则，公共配置使用数据库单行默认值。
   - 不实现规则 JSON 导入命令。

2. **快照 v2**
   - 快照包含完整基础资源 `base_metrics`、按分类生成的有效 `metrics`、全部有效规则和 `rule_config_version`。
   - 快照原子写入；已有快照不可变。
   - 单规则重跑复用快照；全量重建删除后生成新快照。
   - 旧版快照继续兼容读取，但不自动升级文件。

3. **配置服务**
   - `kpi_config.py` 提供聚合/公式、阈值、容量、展示和公共配置的查询、保存、删除与审计。
   - 所有写操作在数据库事务中完成；成功后写审计并递增全局规则配置修订。
   - 校验失败返回统一业务错误码，不写部分数据。

4. **引用保护**
   - 分类变更前检查公式、阈值、容量和展示规则引用。
   - 公式输入必须存在且不得循环。
   - 离线基础数据替换前检查数据库引用，任何被引用指标缺失时整体失败。

5. **按需线索**
   - 优先从任务规则结果和任务快照的 `base_metrics` 解析；不依赖最新基础数据。
   - 匹配状态分为 `unclassified`、`classified`、`unregistered`、`ambiguous`。
   - 单条线索解析失败不影响其他线索。

6. **前端配置中心**
   - 以“基础指标”页面为基础扩展为 KPI 配置中心。
   - 任务详情线索卡提供分类入口。
   - 所有 API 调用使用生成的客户端类型。

7. **契约与文档**
   - 先在规格契约中固化 `/api/v4` 设计，再合并到 `docs/api/openapi.yaml`。
   - 同步更新 Pydantic、生成客户端、架构和数据模型文档。

## 验证计划

实现完成后至少执行：

```bash
python build.py lint
python build.py test
```

本功能改变配置加载、任务快照、离线导入保护、API 契约和前端交互，另执行：

```bash
python build.py contract
python build.py gen-web-api
python build.py verify
cd web && npm run build
```

关键验证场景：

- 动态配置为空时可生成合法 v2 快照。
- 旧 v1 快照可读取并单规则重跑。
- 修改配置后新任务使用新配置，旧任务单规则重跑不变。
- 分类、公式、阈值、容量和展示引用保护完整。
- 线索能区分未分类、已分类待重跑、未登记和匹配不明确。
- 离线工具不能移除仍被数据库引用的指标。
- 数据库不可用时新任务失败且不回退规则 JSON。
- OpenAPI、Pydantic 和前端客户端一致。
