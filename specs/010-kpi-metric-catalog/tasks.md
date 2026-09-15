# 任务：KPI 指标字典与分组展示

**输入**：来自 `specs/010-kpi-metric-catalog/` 的设计文档。

**前置条件**：`plan.md`、`spec.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`。

**测试约定**：每个实现任务先写可失败测试，再实现；公共契约变更必须先同步 `docs/api/openapi.yaml`，再更新实现与生成客户端。

## 格式

- `[P]`：可并行执行（不同文件且无依赖）。
- `[US1]` 到 `[US6]`：对应规格中的用户故事。
- 所有路径相对仓库根目录。

---

## 阶段 1：设置

**目的**：准备实现分支、契约基线和任务验证入口。

- [x] T001 在 `feature/010-kpi-metric-catalog` 实现分支/worktree 中确认 `spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md` 已提交。
- [x] T002 运行 `python build.py test` 记录当前 KPI 相关失败基线；先提交新增失败测试，不提交未验证实现。
- [x] T003 [P] 在 `tests/test_kpi_catalog_config.py` 中添加配置目录、版本、必需领域文件和旧路径不再加载的失败测试。
- [x] T004 [P] 在 `tests/test_contract.py` 中添加 KPI 记录分页接口、`exclude_records=true` 和 KPI metadata schema 的失败契约测试。

**检查点**：任务清单和失败测试可作为实现起点。

---

## 阶段 2：基础层（阻塞所有故事）

**目的**：建立 KPI 配置模型、加载校验、结果契约和记录查询接口。

- [x] T005 在 `deploy/config/kpi/` 创建 `common.yaml`、`call.yaml`、`api.yaml`、`media.yaml`，并移除 `deploy/config/kpi_rules.yaml`。
- [x] T006 在 `app/inspectors/kpi/catalog.py` 实现 `KpiCommonConfig`、`KpiMetricDefinition`、`KpiAggregation`、`KpiRatioFormula`、`KpiThreshold` 等配置模型。
- [x] T007 实现 `load_kpi_config()`：读取目录化配置，校验版本、时区、预算、领域、未知文件、必需指标/阈值、别名冲突、公式输入、循环依赖和容量引用。
- [x] T008 实现名称归一化精确匹配 helper，处理 Unicode `NFKC`、首尾空白、连续空白和 `casefold()`；禁止模糊匹配。
- [x] T009 在 `app/inspectors/kpi/common.py` 接入目录化配置，保留 CSV 单文件解析失败不中断行为，并把未登记列记入解析结果。
- [x] T010 在 `app/models/schemas.py` 新增 KPI 目录、指标结果、溯源、未分类指标和记录分页辅助模型；不得修改既有字段语义。
- [x] T011 先同步 `docs/api/openapi.yaml`：新增 `GET /api/v2/tasks/{task_id}/rules/{rule_code}/kpi/records`、`exclude_records=true`、KPI metadata schema、分页 schema 和错误响应。
- [x] T012 运行 `python build.py contract` 和 `python build.py gen-web-api`，确保生成客户端包含新契约；随后运行 `cd web && npm run build`。
- [x] T013 在 `app/services/kpi_records.py` 实现记录过滤、排序、状态解释和分页投影。
- [x] T014 在 `app/services/tasks.py` 支持 `exclude_records=true`：只清空 KPI `metadata.kpi_files[].records`，默认行为不变。
- [x] T015 在 `app/api/routes.py` 注册分页记录查询接口，并把 `exclude_records` 接入规则结果查询。
- [x] T016 在 `tests/test_kpi_records_api.py` 中验证默认兼容、排除记录、按指标/文件/周期/状态过滤、分页、非 KPI 空结果和统一错误。
- [x] T017 运行 `python build.py lint && python build.py test && python build.py contract`，修复基础层失败。

**检查点**：配置与公共契约基础可用；用户故事可以开始。

---

## 阶段 3：US1 - 快速识别 KPI 巡检重点（P1）

**目标**：规则详情首屏呈现关键状态、重点指标、越限和不可用汇总。

**独立测试**：给定呼叫成功率越限样例，打开 KPI 详情即可看到状态、主值、阈值方向、越限数量和趋势入口；无阈值指标为中性展示。

### US1 测试

- [x] T018 [P] [US1] 在 `tests/test_kpi_catalog_aggregation.py` 中编写重点指标、阈值状态、无阈值中性状态和越限数量失败测试。
- [x] T019 [P] [US1] 在 `tests/test_kpi_csv_rules.py` 中补充 KPI 结果 `metadata.version=2`、`kpi_results` 和整体规则状态兼容失败测试。

### US1 实现

- [x] T020 [US1] 在 `app/inspectors/kpi/catalog.py` 实现主值聚合：计数求和、容量取最大、时延取最大/分位、比率先汇总输入再计算，并携带实际汇总方式。
- [x] T021 [US1] 在 `app/inspectors/kpi/catalog.py` 实现阈值评估和 `display_status`：`pass/warn/fail/neutral/unavailable`。
- [x] T022 [US1] 在 `app/inspectors/kpi/call.py`、`app/inspectors/kpi/api.py`、`app/inspectors/kpi/media.py` 生成 `metric_catalog`、`kpi_results`、`unclassified_metrics` 和文件摘要；升级相关 `rule_version`。
- [x] T023 [US1] 保持既有 `RuleResult.status` 语义：解析失败/阈值越限为 `fail`，一致性异常为 `warn`，配置错误为 `error`，仅未分类指标不改变状态。
- [x] T024 [US1] 运行 KPI 后端测试，确认重点指标、中性指标和规则状态兼容通过。

**检查点**：服务端可输出可判定优先级和状态的 KPI 元数据。

---

## 阶段 4：US2 - 按语义分组浏览大量指标（P1）

**目标**：前端通过重点卡片、分组目录、搜索和筛选定位 50+ 指标。

**独立测试**：给定 50 个指标，3 次内通过分组、搜索或筛选定位指定指标，并可确认类型与展示角色。

### US2 测试

- [x] T025 [P] [US2] 在 `web/src/components/KpiMetricCatalog.test.ts` 添加分组、状态筛选、阈值可用性筛选、中英文/稳定 key 搜索和无阈值中性展示测试。
- [x] T026 [P] [US2] 在 `web/src/components/KpiMetricCard.test.ts` 添加主值、单位、阈值方向、状态色、不可用与中性标识测试。

### US2 实现

- [x] T027 [US2] 在 `web/src/components/KpiInspectionPanel.tsx` 编排 `RuleResult.metadata` 的 KPI 面板、汇总卡和分区；旧结果回退到 `KpiDetailTable`。
- [x] T028 [US2] 在 `web/src/components/KpiMetricCard.tsx` 实现重点/上下文/诊断/目录指标卡片与克制状态样式。
- [x] T029 [US2] 在 `web/src/components/KpiMetricCatalog.tsx` 实现语义分组、状态筛选、搜索和空态。
- [x] T030 [US2] 在 `web/src/pages/RuleDetailPage.tsx` 对新 KPI 结果使用 `exclude_records=true`，并渲染 KPI 面板。
- [x] T031 [US2] 运行 `cd web && npm run test -- KpiMetricCatalog.test.ts KpiMetricCard.test.ts && npm run build`。

**检查点**：大量 KPI 可按分组和筛选快速定位。

---

## 阶段 5：US3 - 理解派生指标来源（P1）

**目标**：成功率等派生指标展示公式、输入、直接列交叉参考和不可用原因。

**独立测试**：给定直接成功率、完整输入、分母为零或输入缺失样例，详情抽屉能解释来源和口径。

### US3 测试

- [x] T032 [P] [US3] 在 `tests/test_kpi_catalog_aggregation.py` 添加公式优先、声明式分母兜底、输入缺失、分母为零和直接列仅交叉参考失败测试。
- [x] T033 [P] [US3] 在 `web/src/components/KpiMetricDrawer.test.ts` 添加定义、公式、输入、交叉参考、不可用原因和阈值信息测试。

### US3 实现

- [x] T034 [US3] 在 `app/inspectors/kpi/catalog.py` 实现声明式 `ratio` 公式、缩放、依赖校验和 provenance。
- [x] T035 [US3] 在 `app/inspectors/kpi/common.py` 将直接成功率/失败率列保留为证据，不得覆盖公式主值。
- [x] T036 [US3] 在 `web/src/components/KpiMetricDrawer.tsx` 实现指标详情、公式解释、序列、来源文件和原始记录入口。
- [x] T037 [US3] 在 `web/src/components/KpiMetricTrend.tsx` 用 ECharts 渲染统计周期序列，不可用序列显示原因。
- [x] T038 [US3] 运行 KPI 后端测试和前端组件测试。

**检查点**：派生指标结果可审计。

---

## 阶段 6：US4 - 统一维护中英文指标名和别名（P2）

**目标**：维护者按领域新增指标或别名，只改目标配置文件即可通过校验。

**独立测试**：新增同义中英文别名后重跑规则，两个列名归一到同一稳定 key；近似名保持未分类。

### US4 测试

- [x] T039 [P] [US4] 在 `tests/test_kpi_catalog_config.py` 添加新增指标、追加别名、中英文归一化、别名冲突、key 重复和跨领域公式拒绝测试。
- [x] T040 [P] [US4] 在 `tests/test_kpi_csv_rules.py` 添加同义列归一、未登记近似名保持未分类的规则级失败测试。

### US4 实现

- [x] T041 [US4] 完善 `deploy/config/kpi/*.yaml` 当前 call 指标、别名、阈值和容量配置；`api.yaml`、`media.yaml` 提供合法空领域模板。
- [x] T042 [US4] 实现新增指标只影响目标领域文件，并保证配置来源显示 `deploy/config/kpi`。
- [x] T043 [US4] 运行配置和规则测试，验证只改目标领域文件可通过校验。

**检查点**：配置维护路径清晰且无别名歧义。

---

## 阶段 7：US5 - 发现未识别指标（P2）

**目标**：未登记指标保留原始信息并进入未分类展示，不破坏规则状态。

**独立测试**：包含未登记列的 KPI 文件仍能输出已登记指标，未登记列出现在未分类区域。

### US5 测试

- [x] T044 [P] [US5] 在 `tests/test_kpi_csv_rules.py` 添加未分类指标、样例值、来源文件、记录数和不改变规则状态失败测试。
- [x] T045 [P] [US5] 在 `web/src/components/KpiUnclassifiedList.test.ts` 添加未分类列表、空态和搜索测试。

### US5 实现

- [x] T046 [US5] 在 `app/inspectors/kpi/catalog.py` 聚合未登记列为 `unclassified_metrics`，保留原始列名、来源文件、记录数和样例值。
- [x] T047 [US5] 在 `web/src/components/KpiUnclassifiedList.tsx` 展示未分类指标和维护提示。
- [x] T048 [US5] 运行规则测试和前端组件测试。

**检查点**：未知指标不丢失且不误导判定。

---

## 阶段 8：US6 - 按需检查原始记录（P3）

**目标**：用户从指标详情按需获取分页原始记录，首屏不加载全部记录。

**独立测试**：多文件多周期结果首屏不渲染全部记录，抽屉可按指标、文件、周期和异常状态定位记录。

### US6 测试

- [x] T049 [P] [US6] 在 `tests/test_kpi_records_api.py` 添加异常状态、来源文件、周期、指标过滤和分页边界测试。
- [x] T050 [P] [US6] 在 `web/src/components/KpiMetricDrawer.test.ts` 添加记录分页、加载态、筛选和空态测试。

### US6 实现

- [x] T051 [US6] 在 `web/src/components/KpiMetricDrawer.tsx` 集成生成客户端的 KPI 记录查询。
- [x] T052 [US6] 在 `web/src/components/KpiRecordTable.tsx` 实现分页表格、筛选、UTC 时间和错误展示。
- [x] T053 [US6] 确认 `RuleDetailPage` 和 `KpiInspectionPanel` 首屏不渲染 `metadata.kpi_files[].records`。
- [x] T054 [US6] 运行记录 API 测试和前端构建。

**检查点**：原始记录可审计且首屏性能可控。

---

## 阶段 9：收尾与横切关注点

**目的**：补齐兼容性、文档、报告和全流程验证。

- [x] T055 验证历史 `metadata.version=1` 结果前端回退旧表，且不迁移或重算。
- [x] T056 [P] 更新 `docs/architecture.md`、`docs/design/mechanisms.md` 或既有 KPI 文档中的配置路径和展示机制。
- [x] T057 [P] 检查 HTML 报告对新增 metadata 不报错；保持既有规则摘要。
- [x] T058 运行本地 CLI/API/单规则重跑一致性测试。
- [x] T059 运行 `python build.py lint && python build.py test && python build.py verify`。
- [x] T060 运行 `python build.py contract && python build.py gen-web-api && cd web && npm run build`。
- [x] T061 按 `quickstart.md` 完成手工页面验证，更新 `tasks.md` 复选框和完成记录。

---

## 依赖与执行顺序

### 阶段依赖

- 阶段 1：无依赖。
- 阶段 2：依赖阶段 1；阻塞所有用户故事。
- US1（阶段 3）：依赖阶段 2。
- US2（阶段 4）：依赖 US1 输出的 metadata。
- US3（阶段 5）：依赖阶段 2；与 US2 集成。
- US4（阶段 6）：依赖阶段 2。
- US5（阶段 7）：依赖阶段 2。
- US6（阶段 8）：依赖阶段 2 和 US3/US2 的抽屉结构。
- 收尾（阶段 9）：依赖全部用户故事完成。

### 建议顺序

```text
T001-T017 → T018-T024 → T025-T031 → T032-T038 → T039-T048 → T049-T054 → T055-T061
```

### 并行机会

- 配置测试、契约测试可并行。
- 后端聚合测试与前端组件测试可并行。
- US4、US5 在基础层完成后可并行。
- 记录 API 与前端抽屉集成可由接口契约先行约定后并行。

---

## 实现策略

1. 完成阶段 1 和阶段 2，保证契约、配置和接口基线稳定。
2. 按 P1 顺序交付 US1 → US2 → US3，形成最小可用分组展示。
3. 交付 US4/US5/US6，完善维护、未知指标和记录审计。
4. 每个阶段完成后运行对应测试和检查点；未通过不得进入下一阶段。
5. 收尾必须执行 lint、test、verify、contract、gen-web-api 和前端构建。
