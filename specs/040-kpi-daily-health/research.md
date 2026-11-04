# 阶段 0 研究：KPI 当前判定与昨日趋势

**日期：** 2026-11-05  
**输入：** `spec.md`、`plan.md`、现有 KPI 巡检代码与真实只读任务结构观察

## 决策 1：日健康在巡检器内生成，页面不做判定

**Decision:** 新增纯业务模块 `app/services/kpi_daily_health.py`，由 `inspect_measurement_files()` 在已有 `time_series`、资源阈值和派生配置上调用，生成指标级 `metadata.daily_health`。

**Rationale:** 本地 CLI 与在线 API 必须共享结论；页面只负责展示和筛选，避免前端复制阈值逻辑。已有巡检器已在内存中持有时间序列，首屏生成不需要重新扫描 189 万点。

**Alternatives rejected:**
- 首屏 API 查询 `TaskKpiPoint` 全表后在浏览器聚合：慢且重复扫描。
- 仅前端根据 `trend_points` 推导：采样点会丢失日聚合证据，且 CLI 与报告无法一致。

## 决策 2：首屏只保留指标级结论，详情按需读取

**Decision:** `daily_health.metrics[]` 约等于启用指标数（当前现场 77 项），每个指标保存状态、摘要值、对象/周期计数与首要原因。对象/周期组和 7 日序列由单指标详情接口返回。

**Rationale:** 当前现场对象周期组约 1466 个；全部放入首屏会使摘要膨胀。维护人员首先需要指标级答案，再按异常下钻。

**Alternatives rejected:**
- 首屏返回全部 1466 组：摘要过大、渲染慢。
- 只显示聚合总数：违反 FR-015/033/034 的可追溯性。

## 决策 3：UTC+8 日界，UTC 存储

**Decision:** 以当前任务所有启用指标有效点的最大 `measured_at` 为锚点，转换为 `Asia/Shanghai` 自然日；昨日为前一日。底层点保持 UTC。

**Rationale:** 与现场口径和规格一致，避免任务上传/完成时间覆盖数据时间。

**Edge handling:** 当前任务完全无有效点时使用任务完成时间的 UTC+8 日期作为 `data_date`，但所有指标为无法判定；不得伪造点。

## 决策 4：日聚合采用显式配置，默认安全兜底

**Decision:** 基础指标支持 `latest/mean/sum/max/min`，未配置默认 `latest`。聚合成功率忽略基础聚合方式，固定使用当日分子总和 ÷ 当日分母总和 × 100；反向模板为 `100 - rate`。

**Rationale:** 请求数等累计值不能按名称猜测；成功率不能平均分钟值。默认 `latest` 是低假设兜底，但配置缺失和阈值缺失仍会导致待配置。

**Evidence:** 每个日值保存有效点数、起止时刻、公式/聚合方式、对象、周期、分子、分母和来源文件。

## 决策 5：阈值与配置来源

**Decision:** 复用现有 `KpiMeasurementResource.direction/warning_threshold/critical_threshold` 作为当前阈值来源；新增维护表保存角色、日聚合、变化阈值、百分比语义、零值语义、一致性容差和对象匹配口径。维护 API 在同一事务中写资源阈值与扩展配置并记录审计。

**Rationale:** 避免迁移已有资源字段语义；现有资源编辑仍可用。扩展字段从维护配置读取，缺失时安全降级。

**Alternatives rejected:**
- 把所有字段复制到新表并作为唯一真相：与现有 API/UI 冲突，存在双写漂移。
- 扩展现有资源表：CSV 导入和资源同步容易覆盖维护字段。

## 决策 6：当前判定优先级

**Decision:** 单个对象/周期先判定，再按
`fail > warn > unable_to_judge > pending_config > not_applicable > normal`
汇总到指标。任何对象不可判定都不能被其他对象的正常掩盖。

**Rationale:** 符合“失败优先”和“无依据不得正常”的原则；详情提供另一种对象/周期结果。

**Special cases:**
- `value is None` 或因服务无法读取：`unable_to_judge`
- 分母为零：`not_applicable`
- 无方向/阈值：`pending_config`
- 全零且零值语义 `unknown`：`pending_config`，原因 `all_zero_unconfirmed`
- 全零且 `expected_zero`：进入正常阈值判定路径
- 全零且 `business_not_triggered`：`not_applicable`

## 决策 7：昨日趋势与容差

**Decision:** 使用同对象、同周期、同指标今日/昨日日值。百分比指标比较 `pp`，默认 `0.2pp`；其他指标比较相对变化，默认 `5%`。方向中性超容差只显示 `observe`。无昨日基线为 `no_baseline`。

**Rationale:** 避免百分比变化写成百分比，避免中性方向被臆测为改善/恶化。

**Aggregation:** 指标级任一对象恶化 -> 指标恶化；无恶化时优先改善/观察，否则稳定/无基线。

## 决策 8：成功率依赖与一致性

**Decision:** 每个 `KpiMeasurementDerived` 的 `metric_resource_id` 是独立指标；分子/分母按对象+周期匹配后分别求和。若找不到同一对象+周期的分母则为无法判定，不得跨对象补位。原始成功率列存在时，按当日分母加权与其比较；超过容差标记一致性问题并使当前判定不能无提示为正常。

**Rationale:** 防止四个名称相近成功率被合并；保留现有受控模板，不引入自由公式。

**Legacy behavior:** 现有派生指标 `avg_value` 的分钟均值算法保留给旧 `derived_metrics` 展示，但新的 `daily_health` 必须使用日分子/分母重算；零分母从 `pass` 改为 `not_applicable` 语义。

## 决策 9：增量数据库迁移与唯一约束

**Decision:** 新增 `kpi_metric_maintenance_configs`、`kpi_metric_maintenance_audits` 表；对旧 `kpi_measurement_derived` 先按 `(measurement_unit_id, metric_resource_id)` 保留最新 `id` 并删除重复行，再创建唯一索引。迁移在 `init_db()` 内幂等执行，并对旧库无重复行为做回归测试。

**Rationale:** SQLite `create_all()` 不会给既有表添加唯一约束；重复派生配置会产生多套结论。

**Safety:** 去重只处理同一测量单元同一指标配置，不删除其他派生定义；操作幂等。

## 决策 10：单指标 7 日详情查询

**Decision:** 详情服务以 `task_id + measurement_unit_id + metric_resource_id` 过滤 `TaskKpiPoint`，并用 `measured_at` 限定 7 日窗口；派生指标再按依赖资源 ID 查询同一对象/周期。服务不得调用 `list_kpi_points(task_id)`。

**Rationale:** 当前表约 189 万行，按任务和指标过滤能显著减少内存与序列化成本。若生产库仍慢，可后续增加复合索引，但本期不以大表索引迁移阻塞功能。

**Fallback:** 当前任务无昨日点时，仅当任务 `customer.device_id` 存在时查询同设备最近已完成任务的匹配窗口；否则 `no_baseline`。真实任务没有设备 ID，因此现场主要依赖任务内连续多日数据。

## 决策 11：范围外文件

**Decision:** `match_measurement_files()` 的 `disabled` 和未确认绑定覆盖的文件归入 `out_of_scope`，不计入 `unmatched_files`。范围摘要记录 `out_of_scope_file_count` 与原因计数。

**Rationale:** 用户只启用 4 个测量单元；停用单元文件不应制造维护噪音。范围外文件仍可从证据接口查看。

## 决策 12：旧任务降级

**Decision:** `daily_health` 缺失、schema 版本未知或类型异常时显示“旧任务无日健康结论”提示；保留原测量单元、趋势和发现展示。不尝试在浏览器内凭空重算。

**Rationale:** 旧任务缺少必要配置和历史点，重算可能产生虚假结论；规格允许明确提示无法生成。

## 决策 13：HTML 报告范围

**Decision:** 现有仓库只有 `report.html` 模板和 API；本功能只扩展 HTML 报告，页面与报告均读取同一 `metadata.daily_health`。不新增 Markdown 文件、下载路由或虚构模板。

**Rationale:** 遵循现有产品范围，避免为此功能引入无消费者的第二套报告格式。FR-037 已在规格中明确为 HTML。

## 决策 14：前端信息架构

**Decision:** 首屏在测量单元选择器之前展示：
1. 数据日期/最新有效测量时间/范围；
2. 当前判定与较昨日两组统计；
3. 重点关注表；
4. 可筛选的全部指标表。

指标行点击打开快捷详情抽屉或展开区，显示对象/周期和 7 日日聚合；维护人员使用“配置口径”入口更新配置。四个相近成功率以完整指标名和资源 ID 独立显示。

**Rationale:** 首屏直接回答问题，同时保留下钻；避免继续以健康分和单测量单元选择器作为首屏主路径。

## 性能与测试策略

- 纯函数单测不依赖数据库，覆盖不同对象、分母、全零、阈值、容差和旧 schema。
- 集成测试用合成任务验证 metadata、范围、CLI/API 同构和 7 日查询参数。
- 契约测试保证 OpenAPI/Pydantic 一致。
- 前端组件测试验证统计与表格总和一致、筛选和降级。
- Playwright 走完整任务详情入口到重点指标详情，样例不少于 20 个指标。
- `tests/fixtures/make_real_package.py` 新增固定时间戳的日健康场景；不提交生成的真实数据。

## 未决项

无。实现中如需改变判定优先级、配置字段或 API 形状，必须回到计划和契约评审后再实施。
