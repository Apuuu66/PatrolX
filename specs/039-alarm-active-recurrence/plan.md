# 实现计划：未清除告警与反复上报巡检

**分支**：`feature/039-alarm-active-recurrence` | **日期**：2026-11-04 | **规格**：[spec.md](./spec.md)

**输入**：来自 `specs/039-alarm-active-recurrence/spec.md` 的已澄清功能规格

## 摘要

新增两条彼此独立的 P1 告警规则：

- `alarm.active_state`：只把规范化状态为 `Not Cleared` 的记录视为活动告警，按严重级、原始重复次数、持续时长降序展示，并汇总活动记录/分组、严重级分布、状态分布和两种上报口径。
- `alarm.recurrence`：按 `App Name + Alarm ID` 汇总全部有效生命周期，同时保留对象明细，识别多次发生、持续期内重复上报、短告警、快速复发和 `Reset Cleared`。

两条规则共享 `app/inspectors/alarm/common.py` 中的纯解析与归一化能力，但不互相导入、调用或消费结果。解析模块集中维护中英文表头、状态、严重级和对象键映射；未知值进入质量统计。扫描组 `alarm_all` 只匹配 `alarm/` 直属 `.csv`。结果仍使用既有 `RuleResult`、`Metric`、`Finding` 契约，只新增 `metadata.alarm_active` 与 `metadata.alarm_recurrence`。

前端在既有规则详情页按 metadata 命名空间渲染两个独立面板；HTML 报告增加活动告警关键统计和处置建议。不新增 HTTP API，不修改 OpenAPI。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript 5.6、React 18、Vite 5

**主要依赖**：Python 标准库 `csv`、`dataclasses`、`datetime`、`hashlib`、`pathlib`；FastAPI/Pydantic v2 既有模型；Ant Design 5 既有前端组件

**存储**：沿用任务目录规则 JSON 和 HTML 报告；本功能不新增数据库表、迁移或 prepared 数据

**测试**：pytest、Vitest/React Testing Library、Playwright；真实告警文件验收使用只读输入和独立结果目录

**目标平台**：现有离线 PatrolX 本地 CLI 与在线 API/Web

**项目类型**：后端巡检规则 + 前端结果展示 + HTML 报告

**性能目标**：当前 2,209 条告警、约 712 KiB 文件的单规则执行目标不超过 2 秒；两条规则各自独立解析，不共享运行产物。解析期间只保留规范化记录、汇总对象和展示用 Top-N，不保留原始整文件副本。

**约束条件**：

- 输入仅限 `ctx.files` 中由 `^alarm/[^/]+\.csv$` 匹配到的任务内直属 CSV，禁止跨任务路径和嵌套目录。
- 单文件超过 32 MiB、单文件超过 100,000 个数据行，或任务累计超过 250,000 个数据行时，受控失败/降级并输出明确原因，不得耗尽任务进程。
- 无时区时间按 UTC+8 解释后转 UTC；所有输出时间使用带时区 ISO-8601 和 `*_at` 后缀。
- 单文件失败隔离；未知映射、坏时间、无效重复次数等进入质量统计。
- 展示明细最多保留每类 100 条；所有汇总始终基于完整有效数据，并输出截断状态。

**规模/范围**：两条 P1 规则、一个集中映射/解析模块、一个扫描组、两个规则详情面板、一个报告区块；合成样例覆盖中英文与全部关键边界，真实数据仅做只读验收。

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后复核。*

- [x] **离线优先**：只读取已解压任务文件，不连接被检系统。
- [x] **一个包、一个任务**：仅使用 `ctx.files`/`ctx.resolved_files()`，不引入跨任务路径。
- [x] **真实数据隔离**：真实 CSV 只读；测试夹具全部为固定时间戳合成数据；不暂存 `output/`。
- [x] **契约驱动**：不新增或修改 HTTP API、OpenAPI、`RuleResult`、`Metric`、`Finding` 字段；新增内容全部位于规则 metadata。
- [x] **模式同构**：本地 CLI、在线 API 和单规则重跑共用同一注册表与规则执行入口。
- [x] **巡检器插件架构**：两条规则通过 `Inspector` 注册，扫描组通过 `source_refs` 解析，不改核心调度器。
- [x] **源文件显式匹配**：`alarm_all` 展开为 `^alarm/[^/]+\.csv$`，POSIX 相对路径完整匹配。
- [x] **规则独立**：`active_state.py` 与 `recurrence.py` 只依赖公共解析模块，不互相导入或调用；无 prepare。
- [x] **增量重跑**：结果按规则落盘；现有执行器即可支持单规则重跑。
- [x] **业务错误契约**：无文件/无有效记录返回 `skip + skip_reason`；单文件失败进入 metadata 并降级规则状态。
- [x] **规则版本**：两条新规则初始版本均为 `1.0.0`；后续判定变化必须递增。
- [x] **契约字段与时区**：使用 UTC 存储，输出时间统一为 `*_at`。

**阶段 1 复核**：设计没有新增跨规则输入、prepared、公共 API 或存储模型；前端只消费既有规则结果 JSON；报告只读取同一 `SystemInspection`。宪章门禁通过，无复杂度违规。

## 项目结构

### 文档（本功能）

```text
specs/039-alarm-active-recurrence/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── alarm-active-result.md
│   └── alarm-recurrence-result.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/inspectors/alarm/
├── __init__.py
├── common.py                 # 集中映射、CSV 读取、规范化、质量统计、共用聚合辅助
├── active_state.py           # alarm.active_state 规则注册与结果构造
└── recurrence.py             # alarm.recurrence 规则注册与结果构造

deploy/config/
└── scan_rules.yaml           # 新增 alarm_all

web/src/components/
├── AlarmActiveStatePanel.tsx
└── AlarmRecurrencePanel.tsx

web/src/pages/
└── RuleDetailPage.tsx        # 按 metadata 命名空间接入两个面板

web/src/components/
├── AlarmActiveStatePanel.test.tsx
└── AlarmRecurrencePanel.test.tsx

web/e2e/
└── alarm-active-recurrence.spec.ts

app/reports/templates/
└── report.html.j2            # 活动告警关键统计和优先处置建议

tests/
├── test_alarm_common.py
├── test_alarm_active_state.py
├── test_alarm_recurrence.py
├── test_alarm_recurrence_report.py
└── fixtures/make_real_package.py
```

**结构决策**：沿用仓库单一 FastAPI/React 项目结构。公共解析放在规则目录内，不提升为服务层，避免调度器依赖业务规则；两个规则模块只有注册和结果组织职责。前端沿用 `RuleDetailPage` + 专用面板组件，不新增页面或路由。

## 阶段 0：研究结论

见 [research.md](./research.md)。已解决的关键决策：

1. 共用解析器不是规则、不产出 `RuleResult`，不会形成规则间依赖。
2. 状态只由显式清除状态字段决定；清除时间为空或非空都不用于推断状态。
3. 原始重复次数与估算上报总数分别输出，估算口径固定为 `1 + Repeat Times`。
4. 覆盖末刻取全部有效 Raised/Cleared 的最大值；未清除持续时长计算到该末刻。
5. 完全重复记录按规范化业务字段去重；重复次数或生命周期时间不同则保留。
6. 中英文归一化后产生同一规范化结果；未知映射进入质量统计。
7. 明细可截断，汇总不可截断；安全预算在解析阶段显式失败隔离。

## 阶段 1：设计与契约

- 数据结构见 [data-model.md](./data-model.md)。
- `alarm.active_state` metadata 契约见 [contracts/alarm-active-result.md](./contracts/alarm-active-result.md)。
- `alarm.recurrence` metadata 契约见 [contracts/alarm-recurrence-result.md](./contracts/alarm-recurrence-result.md)。
- 验证步骤见 [quickstart.md](./quickstart.md)。

### 共用解析设计

- `HEADER_ALIASES`：表头大小写/空白归一化后的 canonical key 映射，覆盖英文和已登记中文。
- `STATUS_ALIASES`、`SEVERITY_ALIASES`：集中同义词映射；未知值保留原文计数。
- `OBJECT_KEY_ALIASES`：按 `Pod Name → Located Device → Service Name → Alarm Source` 固定优先级解析对象。
- `TimePolicy`：UTC+8 无时区解释、偏移时间转 UTC、ISO-8601 序列化。
- `AlarmRecord`：规范化后的有效生命周期记录，携带相对来源文件和物理/逻辑行号。
- `AlarmParseResult`：有效记录、文件结果、覆盖区间、质量统计和预算状态。
- 解析错误按文件隔离；规则层只决定状态、指标、Finding 和展示截断。

### 规则设计

**`alarm.active_state`**

- 过滤 `state == NOT_CLEARED`；按 `(app_name, alarm_id, object)` 分组。
- 输出记录明细和分组明细；两者均按严重级 → 原始重复次数 → 持续时长降序。
- Critical/Major 活动 → `fail`；其它活动 → `warn`；无活动且输入可分析 → `pass`；无文件/无有效记录 → `skip`。
- 存在失败文件或质量降级时不得静默 `pass`，提升为 `warn`。
- Finding 每个活动分组一条，id 由稳定业务键构造，证据包含来源文件、行号和关键数值。

**`alarm.recurrence`**

- 按 `(app_name, alarm_id)` 汇总全部有效状态；对象作为独立子明细。
- 计算生命周期、原始重复合计、最大单条重复、估算总数、首次/最近上报、最长持续、最短相邻间隔、状态/严重级分布。
- 标记 `multi_lifecycle`、`repeat_reporting`、`short_alarm`、`rapid_recurrence`、`reset_cleared`。
- 快速复发采用排序后滑动窗口：窗口内至少 `rapid_recurrence_min_count` 次上报即命中。
- 未清除且重复上报/快速复发 → `fail`；其它风险证据 → `warn`；无风险证据 → `pass`；无文件/无有效记录 → `skip`。
- Finding 顺序：未清除且持续重复/快速复发 → 未清除风险 → 短告警/已清除反复 → 仅 Reset 等其它风险。

### 展示设计

- `AlarmActiveStatePanel`：覆盖期、活动记录/分组、最高严重级、重复口径和状态分布置顶；分组表展示严重级、告警、应用、对象、首次上报、持续时长、原始重复、估算上报；全部列模式显示来源行和最近时间。
- `AlarmRecurrencePanel`：类型聚合表展示生命周期、两种累计上报口径、最大单条重复、首次/最近、间隔和五类证据标记；展开行展示对象明细和状态/严重级分布。
- `RuleDetailPage` 只在对应 metadata 存在时渲染面板；历史 `alarm_flapping` 渲染保持原样。
- HTML 报告新增“告警优先处置”区块，读取 `alarm.active_state` metadata，展示活动数、最高严重级、原始重复合计、估算总数和优先分组/建议。

### 测试设计

- 解析单元测试：中英文等价、未知映射、时间转换、坏时间、重复次数缺失/负数、跨文件去重、坏文件隔离、预算边界。
- 规则单元测试：活动筛选/排序/状态阈值/默认参数/五类标记/对象聚合/幂等 Finding。
- 集成测试：代表性合成包经分类后，两条规则均只匹配直属 CSV；无关目录变化不影响结果；CLI/API/单规则重跑语义一致。
- 报告测试：活动关键统计和建议可见。
- 前端组件测试：两种 metadata 的关键字段、标记、截断提示和全部列切换。
- E2E：从规则详情入口打开两类规则，能一次浏览区分活动风险和反复风险。
- 性能看护：2,209 行真实只读验收不写回源文件；合成 5,000 行解析守护用例记录耗时上限。
