# 研究决策：界面新增动态派生指标

## 1. 配置存储与既有动态口径关系

**Decision**：新增独立 `KpiDerivedMetric` SQLite 表，不放宽既有 `/api/v4/kpi/config/metric-rules/{metric_key}` 只能修改基础指标 key 的行为。

**Rationale**：既有接口用于覆盖离线基础指标的展示/聚合口径；在线派生指标还需要中英文名、业务域、启用状态和公式，语义不同。独立资源可以避免破坏既有请求/响应含义，也便于实施“只删除未被引用”的保护。

**Alternatives considered**：
- 复用 metric-rules 并允许任意 key：实现最快，但会改变既有 404 行为，并把基础资源 key 与在线 key 混在一起。
- 只在离线 YAML 中维护：与“界面新增”目标冲突。

## 2. API 边界

**Decision**：在 `/api/v4` 下新增向后兼容资源 `/kpi/config/derived-metrics`；创建使用 POST，读取/更新/删除使用 `/kpi/config/derived-metrics/{metric_key}`。删除使用现有删除结果结构；审计类型新增 `derived_metric`。

**Rationale**：新增资源和枚举值属于向后兼容扩展，不改变 `/api/v1` 或既有 `/api/v4` 字段含义。操作人取登录会话，不要求前端传入可伪造的 `operator` 字段。

**Alternatives considered**：
- 升级 `/api/v5`：不需要，因为无需重定义既有资源。
- PUT upsert 兼做创建：无法清晰区分创建冲突与更新，且响应语义不够明确。

## 3. 受控公式模型

**Decision**：第一期公式类型固定为 `ratio` 和 `inverse_ratio`，统一表示为 `分子 / 分母 × scale` 或 `(1 - 分子 / 分母) × scale`。输入只能选择同业务域 raw 指标，不支持派生指标嵌套。

**Rationale**：反向比率可以覆盖只有失败次数/总量时计算成功率的场景；受控枚举避免引入表达式解析器和任意算术能力。反向公式继续使用同一“先聚合输入、再计算比率”的口径。

**Alternatives considered**：
- 支持 `1 - expression`：会引入复合表达式边界。
- 用分母/分子互换表达反向：语义不正确，不能从失败次数推导成功率。

## 4. 任务快照策略

**Decision**：快照 schema 升级为 3，并新增 `derived_metrics` 数组；新快照原子写入，旧 schema 1/2 快照继续按“无在线派生指标”读取。派生指标变更只影响之后生成的新快照。

**Rationale**：已有任务快照不可变；版本化字段能兼容旧任务，同时避免把在线派生指标伪造成基础 CSV 资源。

**Alternatives considered**：
- 把派生指标放进 `metrics`：会让任务快照把派生指标当作原始资源。
- 运行时读取最新配置：破坏任务级快照不可变语义。

## 5. 执行与展示

**Decision**：任务构建 KPI 配置时把快照中的启用派生指标注入对应业务域；执行器复用现有 KPI 聚合器计算公式并输出 provenance。缺失输入、分母为零时沿用 `unavailable` 状态。

**Rationale**：这保证派生指标与基础指标在 KPI 结果、报告和前端表格中同一展示结构，同时保留输入来源和不可用原因。

**Alternatives considered**：
- 在前端重新计算：会绕过任务契约且无法进入报告。
- 为每个派生指标新增巡检规则：违反规则私有匹配/插件边界，且派生口径属于目录配置而非独立文件规则。
