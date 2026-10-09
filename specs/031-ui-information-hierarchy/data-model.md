# 数据模型：主界面信息层级重构（展示层）

**功能**：031-ui-information-hierarchy | **日期**：2026-10-10

**重要**：本功能**不新增、不修改任何契约实体**。下列对象全部是前端**展示层派生对象**，由既有 `TaskSummary` / `RuleResult` / `DataPreparation` / `DictsResponse` 字段在渲染时推导，不写入任何接口或存储。

## 来源契约（只读）

| 契约对象 | 使用字段 | 用途 |
| --- | --- | --- |
| `TaskSummary` | `task_id`、`name`、`mode`、`status`、`trigger`、`created_at`、`completed_at`、`stats`、`preparation`、`system`、`package_kind`、`inventory`、`device_id`、`customer_*` | 任务行视图、任务结论、元数据 |
| `TaskStats` | `total`、`pass`、`warn`、`fail`、`error`、`skip`、`systems` | 状态分布与计数 |
| `DataPreparation` | `status`、`items`、`total`、`success_count`、`warning_count`、`failure_count`、`skip_count` | 数据准备状态与问题摘要 |
| `SystemInspection` | `status`、`summary`、`rules`、`customer`、`version` | 结论推导与规则集合 |
| `RuleResult` | `code`、`name`、`category`、`priority`、`status`、`severity`、`summary`、`skip_reason`、`duration_ms`、`metrics`、`findings`、`metadata` | 规则关注项、规则详情 |
| `DictsResponse` | `province`、`operator`、`product`、`version` | 元数据字典名展示 |

## 展示实体

### 1. 状态分布段（StatusDistributionSegment）

由 `web/src/utils/taskDisplay.ts` 既有 `getHealthBarSegments` 产出，供列表与详情共用。

| 字段 | 类型 | 推导规则 |
| --- | --- | --- |
| `key` | `RuleStatus` | 固定集合 `pass / warn / fail / error / skip` |
| `label` | `string` | `通过 / 告警 / 失败 / 异常 / 跳过` |
| `color` | `string` | `#52c41a / #faad14 / #ff4d4f / #8c8c8c / #1677ff` |
| `value` | `number` | 来自 `TaskStats` 对应字段 |
| `percent` | `number` | `value / 五态总和 × 100` |

**校验规则**：
- `value === 0` 的段不进入渲染列表（FR-003、FR-009）。
- 五态总和为 0 时返回空数组，调用方渲染"暂无规则结果"或排队/执行中说明，不得渲染空条。

### 2. 任务结论（TaskConclusion）

由新增纯函数 `deriveTaskConclusion` 产出（`web/src/utils/taskConclusion.ts`）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tone` | `"danger" \| "warning" \| "success" \| "processing" \| "neutral"` | 决定结论区语气与配色 |
| `label` | `string` | 结论标签：任务失败 / 需要关注 / 全部通过 / 执行中 / 排队中 |
| `sentence` | `string` | 一句话结论（含失败与告警数量或失败原因） |
| `detail` | `string \| null` | 补充信息，例如失败阶段、失败规则数 |
| `nextAction` | `"logs" \| "rules" \| "report" \| null"` | 建议的下一步动作；无建议时为 `null` |

**推导优先级**（自上而下短路，状态来源 `TaskSummary.status`）：

1. `status === "failed"` → `danger`，"任务失败"，`sentence`/`detail` 取失败原因与失败阶段，`nextAction = "logs"`。
2. `status === "pending"` → `neutral`，"排队中"，说明尚未开始执行，`nextAction = null`。
3. `status === "running"` → `processing`，"执行中"，说明正在执行，`nextAction = null`。
4. `fail + error > 0` → `danger`，"需要关注"，给出失败与异常数量，`nextAction = "rules"`。
5. `warn > 0` → `warning`，"需要关注"，给出告警数量（**不得使用失败红**，边界情况要求），`nextAction = "rules"`。
6. 其余（`skip` 单独存在视为正常） → `success`，"全部通过"，`nextAction = "report"`。

**校验规则**：
- `tone === "danger"` 与 `"warning"` 都必须带文字标签，不得只靠颜色（FR-002）。
- 主包解压失败的任务不得进入规则分支，不展示伪造规则结果（边界情况）。
- 同一事实（如失败规则条数）在结论区与"重点关注"列表中只允许出现一次高权重表达（FR-016、SC-005）。

### 3. 任务行视图（TaskRowView）

任务列表每行的展示状态，不持久化。

| 字段 | 类型 | 来源 / 推导 |
| --- | --- | --- |
| `taskId` | `string` | `TaskSummary.task_id` |
| `name` | `string` | `TaskSummary.name` |
| `statusLabel` | `string` | `TASK_STATUS_LABELS[status]` |
| `statusTone` | `"success" \| "processing" \| "neutral" \| "danger"` | `completed → success`，`running → processing`，`pending → neutral`，`failed → danger` |
| `segments` | `StatusDistributionSegment[]` | 见实体 1 |
| `attentionCount` | `number` | `stats.fail + stats.warn + stats.error` |
| `reasonSummary` | `string \| null` | 任务失败时取失败阶段与原因；成功任务为 `null`（FR-008） |
| `metadataTags` | `TaskMetadataTag[]` | 复用 `getTaskMetadataTags` |
| `durationText` | `string \| null` | 复用 `formatTaskDuration` |
| `preparationIssue` | `{ failureCount: number; skipCount: number } \| null` | `preparation.failure_count / skip_count > 0` 时给出，展开区可触发重试（FR-011） |
| `primaryAction` | `"detail"` | 固定主操作（FR-012） |
| `secondaryActions` | `("report" \| "logs")[]` | 报告可用性由任务状态决定；失败任务给出日志入口 |
| `moreActions` | `("rerun" \| "rebuild_incremental" \| "rebuild_full" \| "delete")[]` | 收进 `⋯` 菜单；`delete` 与 `rebuild_full` 需二次确认 |

**排序规则（默认，不可开关）**：
1. 优先级：`failed(0) < running(1) < pending(2) < completed(3)`；`completed` 且 `fail + error > 0` 视同异常提前。
2. 同优先级内按 `created_at` 倒序。
3. 分页大小固定默认 10（FR-013、宪法）。

### 4. 规则关注项（RuleAttentionItem）

用于任务详情"重点关注"列表与全部规则分组。

| 字段 | 类型 | 来源 |
| --- | --- | --- |
| `code` / `name` | `string` | `RuleResult.code` / `name` |
| `status` | `RuleStatus` | `RuleResult.status` |
| `severity` | `Severity` | `RuleResult.severity` |
| `summaryText` | `string` | `RuleResult.summary`；为空时用状态标签兜底 |
| `skipReason` | `string \| null` | `RuleResult.skip_reason`（skip 必显，FR-021） |
| `durationText` | `string \| null` | 由 `duration_ms` 格式化 |
| `href` | `string` | `/tasks/{taskId}/rules/{code}` 深链，保持既有 URL 语义 |

**排序规则**：`fail → error → warn`（重点关注列表按 fail → warn 呈现，最多 5 条，其余折叠）；全部规则列表内按既有 `execution_order` 排序，按 `category` 分组折叠，默认展开含异常的分组（FR-017）。

### 5. 视觉基线（VisualBaseline）

非运行时对象，作为 `docs/design/DESIGN.md` 与 `contracts/ui-baseline.md` 的规范条目集合：字号层级、间距刻度、卡片与分隔线、状态语义色、操作分层、四类页面模式、空 / 加载 / 错误态、0 值规则、可访问性。

**校验规则**：其余 7 个页面必须逐页对照该清单走查；至少 1 个页面有自动化断言（SC-006）。

## 状态与生命周期

- 展示对象无持久化状态，随接口响应与 `TaskStats` 每次渲染重新推导。
- 任务处于 `pending` / `running` 时，结论与行操作必须反映进行中并禁用不可用操作（轮询节奏不变，FR-026）。
- 单规则重跑只刷新目标规则相关展示，不整页重排（FR-023、边界情况）。

## 不做的事

- 不新增 `TaskSummary` / `RuleResult` 字段，不新增接口，不改 `docs/api/openapi.yaml`（FR-027）。
- 不引入新的排序控件、不改路由、不改报告模板与规则判定。
