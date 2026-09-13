---
description: "CSV KPI 离线巡检实现任务列表"
---

# 任务：CSV KPI 离线巡检

**输入**：来自 `/specs/006-csv-kpi-inspection/` 的设计文档

**前置条件**：`plan.md`、`spec.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md` 已完成。

**测试**：包含测试任务。项目工作流要求新巡检规则提供单元测试、单规则重跑和关键场景验证。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属用户故事（US1–US6）
- 所有文件路径以仓库根目录为基准

---

## 阶段 1：设置

**目的**：准备共享配置，并移除与新 CSV 结构冲突的旧规则入口。

- [x] T001 在 `deploy/config/kpi_rules.yaml` 创建 KPI 配置：`version: 1`、`input_timezone: "Asia/Shanghai"`；`aliases.call` 映射呼叫请求/成功/失败/成功率/失败率；`capacity_metrics.call` 为 `统计峰值 -> stat_peak(peak)` 和 `最大并发 -> max_concurrency(concurrency)` 且 `status=confirmed`；呼叫 `call_success_rate` 四个周期默认 `99.0` 且方向 `min`、`call_failure_rate` 四个周期默认 `1.0` 且方向 `max`；`budgets` 包含 64 MiB、100000 行、256 列、1000 文件和 200000 记录上限。
- [x] T002 [P] 删除 `app/inspectors/kpi/threshold.py`，并在 `tests/test_rules.py`、`tests/test_baseline_pipeline.py`、`tests/test_baseline_consistency.py`、`tests/test_baseline_rerun.py`、`tests/test_api.py`、`tests/test_prepare_pipeline.py` 中移除或改写对 `kpi.threshold` 的直接断言；不得让新规则与旧规则重复巡检。

**检查点**：旧规则不再注册；`deploy/config/kpi_rules.yaml` 已具备呼叫阈值、别名和预算配置。

---

## 阶段 2：基础层（阻塞前置条件）

**目的**：实现三条规则共享但不共享结果数据的 CSV 解析与时间规范化能力。

**⚠️ 关键**：本阶段完成前不得开始用户故事规则实现。

- [x] T003 在 `tests/test_kpi_csv_rules.py` 编写共享解析器失败测试：覆盖两行表头结构、`5/15/30/60` 周期、naive 时间按 `Asia/Shanghai` 转 UTC、`end_at = start_at + period`、文件名周期与行周期不一致、列数不一致、指标值不可解析、空测量集、重复指标名、别名与容量 key 冲突和资源预算超限；测试必须先失败。
- [x] T004 在 `app/inspectors/kpi/common.py` 实现共享解析 helper：从任务相对路径解析 domain/period；用标准库 `csv` 流式解析第 1 行测量集、第 2 行测量对象、第 3 行起数据行；产出 `data-model.md` 定义的 `KpiCsvFile` / `KpiRecord` / `KpiError` 数据形状；实现 UTC 转换、资源预算、行级错误隔离和确定性错误码。
- [x] T005 在 `app/inspectors/kpi/common.py` 实现配置读取与校验：读取 `deploy/config/kpi_rules.yaml`；校验 `aliases`、`capacity_metrics`、`limits` 和 `budgets` 的完整性与类型；周期缺失使用 `default`；配置缺失、YAML 非法、方向/语义/状态非法、别名与容量 key 冲突或预算字段非法时抛出统一可追溯异常，不得静默使用内置阈值。

**检查点**：共享解析器可通过自身测试；三个领域规则可以开始实现。

---

## 阶段 3：用户故事 1 - 识别 KPI 数据文件（优先级：P1）🎯

**目标**：准确识别 `kpi-<domain>-<period>.csv` 的领域、周期和来源路径，并在无法识别时显式跳过。

**独立测试**：构造包含三类 KPI 与四个周期的任务包，执行任务后验证每个文件都进入对应规则、领域和周期；无匹配领域时对应规则为 `skip`。

- [x] T006 [P] [US1] 在 `tests/test_kpi_single_rule.py` 编写文件识别测试：验证 `api/media/call` 与 `5/15/30/60` 的 source pattern 匹配、嵌套子包路径匹配、`.main/` 与 prepared 目录不匹配、无匹配文件返回 `skip` 且 `skip_reason` 非空。
- [x] T007 [US1] 在 `app/inspectors/kpi/common.py` 中完善路径识别结果到 `metadata.kpi_files[]` 的映射，确保每条文件级结论都保留任务内 POSIX 相对路径、domain、period、measurement_set、objects、status 和 errors。
- [x] T008 [US1] 在 `tests/test_classify.py` 增加 `kpi-call-15.csv`、`kpi-api-5.csv`、`kpi-media-60.csv` 的分类断言，证明这些文件进入 `kpi/` 且不会被 `traffic` 模式抢占。

**检查点**：文件识别、周期归属和 `skip` 行为可独立验证。

---

## 阶段 4：用户故事 2 - API KPI 巡检（优先级：P1）

**目标**：新增独立 `kpi.api` 规则，完成 API KPI 文件解析、完整性检查和指标展示。

**独立测试**：只提供 API KPI CSV，运行 `kpi.api`，检查文件数、记录数、指标列数、错误数、metadata 来源和状态。

- [x] T009 [P] [US2] 在 `tests/test_kpi_single_rule.py` 编写 `kpi.api` 测试：正常文件 `pass`；同领域同周期多文件聚合为一个总结论且保留每个文件明细；空文件、缺表头、坏行返回 `fail` 且其他文件继续处理；无文件返回 `skip`。
- [x] T010 [US2] 创建 `app/inspectors/kpi/api.py` 并注册普通规则 `kpi.api`：`category=kpi`、`severity=medium`、`priority=P1`、`rule_version=1.0.0`、source pattern `^kpi/(?:.*/)?kpi-api-(?:5|15|30|60)\.csv$`、不声明 prepare。
- [x] T011 [US2] 在 `app/inspectors/kpi/api.py` 实现结果构建：输出固定 metrics `file_count/record_count/metric_count/parse_error_count`；`metadata.kpi_files` 保存记录、时间和原始指标值；不生成业务阈值告警，不输出成功率或失败率。
- [x] T012 [US2] 在 `tests/test_baseline_pipeline.py` 中更新样例包与规则计数，使 `kpi.api` 进入本地全流程且不重复处理 `kpi.threshold` 旧格式。

**检查点**：`kpi.api` 可独立 pass/fail/skip，且单文件异常不中断其他文件。

---

## 阶段 5：用户故事 3 - 媒体统计 KPI 巡检（优先级：P2）

**目标**：新增独立 `kpi.media` 规则，支持多周期媒体统计 KPI 解析和展示。

**独立测试**：只提供 `kpi-media-5.csv` 与 `kpi-media-60.csv`，运行 `kpi.media`，检查不同周期可追溯、无阈值告警。

- [x] T013 [P] [US3] 在 `tests/test_kpi_single_rule.py` 编写 `kpi.media` 测试：多周期文件聚合为一个总结论；每个展示值可追溯到 path、period、line_number、start_at/end_at 和指标名；周期无法识别或行周期不匹配时显式失败；无文件时 `skip`。
- [x] T014 [US3] 创建 `app/inspectors/kpi/media.py` 并注册普通规则 `kpi.media`：复用 `app/inspectors/kpi/common.py`，声明与 `kpi.api` 对等的元数据和 source pattern `^kpi/(?:.*/)?kpi-media-(?:5|15|30|60)\.csv$`，不声明 prepare。
- [x] T015 [US3] 在 `app/inspectors/kpi/media.py` 实现固定 metrics `file_count/record_count/metric_count/parse_error_count` 和 `metadata.kpi_files` 明细；不生成业务阈值告警，不构造成功率或失败率。
- [x] T016 [US3] 更新 `tests/test_baseline_pipeline.py` 与代表性 fixture，使 `kpi.media` 进入任务结果且与 `kpi.api` 互不影响。

**检查点**：`kpi.media` 可独立验证；同一规则结果可区分多个周期。

---

## 阶段 6：用户故事 4 - 呼叫 KPI 阈值巡检（优先级：P2）

**目标**：新增独立 `kpi.call` 规则，完成呼叫 CSV 解析、周期追溯和呼叫成功/失败率阈值判断。

**独立测试**：只提供呼叫 KPI CSV，运行 `kpi.call`，检查多周期结论、成功率低于 99% 与失败率高于 1% 的 fail 结果、阈值来源和 evidence。

- [x] T017 [P] [US4] 在 `tests/test_kpi_single_rule.py` 编写 `kpi.call` 阈值测试：显式成功率列优先、无显式列时用请求/成功/失败派生；成功率越限、失败率越限、双越限、正常通过、多文件聚合、多周期追溯、显式比率与原始计数来源保留。
- [x] T018 [US4] 创建 `app/inspectors/kpi/call.py` 并注册普通规则 `kpi.call`：`rule_version=1.0.0`、source pattern `^kpi/(?:.*/)?kpi-call-(?:5|15|30|60)\.csv$`、无 prepare；不得导入或调用 `kpi.api` / `kpi.media`。
- [x] T019 [US4] 在 `app/inspectors/kpi/call.py` 实现固定 metrics 与阈值结果：`file_count/record_count/parse_error_count/consistency_error_count/success_rate_min/failure_rate_max/success_breach_count/failure_breach_count/capacity_metric_count/capacity_unknown_count`；每个 pass/warn/fail 结果包含全部 metric key；阈值 metric 和 finding 记录 `deploy/config/kpi_rules.yaml`、direction、period 和实际阈值。
- [x] T020 [US4] 在 `tests/test_kpi_single_rule.py` 增加配置异常测试：删除/破坏 `deploy/config/kpi_rules.yaml` 相关配置时 `kpi.call` 返回 `error`，不得退回硬编码阈值；随后在 `tests/test_baseline_pipeline.py` 更新呼叫样例与规则计数。

**检查点**：`kpi.call` 可独立产生阈值结论，且阈值来源完整可追溯。

---

## 阶段 7：用户故事 5 - 呼叫请求关联巡检（优先级：P2）

**目标**：将呼叫请求、请求成功、请求失败作为关联指标族，输出自洽异常和派生结论，并保留连续周期趋势。

**独立测试**：构造同一领域、同一周期的总量/成功/失败一致、不一致、分母为零和连续失败异常样例，运行 `kpi.call` 后检查不同的状态、finding 和 evidence。

- [x] T021 [P] [US5] 在 `tests/test_kpi_csv_rules.py` 编写关联指标测试：`请求成功 + 请求失败 == 呼叫请求` 正常；不一致生成 `consistency_error_count` 与确定性 finding；分母为零或字段缺失时对应派生率为 `N/A` 且不判阈值；派生字段保留原始三值来源。
- [x] T022 [US5] 在 `app/inspectors/kpi/common.py` 和 `app/inspectors/kpi/call.py` 实现 `derived` 字段：`call_success_rate`、`call_failure_rate`、`call_count_difference`；仅三项数据可用时输出差值；派生率采用百分比。
- [x] T023 [US5] 在 `app/inspectors/kpi/call.py` 中生成连续周期展示与异常证据：按 `path + start_at` 排序，在 `metadata.kpi_files[].records[]` 与 finding evidence 中保留每个异常周期的行号、原始值、派生率和阈值；数据自洽异常与业务阈值异常不得混为同一状态原因。
- [x] T024 [US5] 在 `tests/test_kpi_single_rule.py` 验证同一行或同一文件存在解析错误时，不使用不完整指标判阈值；损坏行/文件仍返回结构化错误且其他行、其他文件继续处理。

**检查点**：呼叫关联巡检可独立验证，能区分数据自洽异常、阈值越限和解析失败。

---

## 阶段 8：用户故事 6 - 容量峰值类指标巡检（优先级：P2）

**目标**：展示 `统计峰值` 与 `最大并发` 的时间趋势和来源，不做成功/失败派生，不做业务阈值告警。

**独立测试**：提供只有容量列、以及容量与请求列共存的呼叫 CSV，运行 `kpi.call` 后确认容量值和趋势可追溯，且不存在容量阈值 finding 或容量成功/失败率。

- [x] T025 [P] [US6] 在 `tests/test_kpi_csv_rules.py` 编写容量指标测试：`统计峰值` 映射 `stat_peak`、`最大并发` 映射 `max_concurrency`；连续记录形成时间趋势；只有容量列时规则仍可处理；结果不得为容量指标生成成功率、失败率或业务阈值 finding。
- [x] T026 [US6] 在 `app/inspectors/kpi/common.py` 中按 `capacity_metrics` 配置识别容量型指标，写入 `capacity_values` 及 `status/semantics`；`status=unknown` 时保留原始值并生成 `capacity_semantics_unknown` 错误；未配置容量列仍保留原始指标名和数值；不同文件同名容量指标不得跨文件混合计算峰值。
- [x] T027 [US6] 在 `app/inspectors/kpi/call.py` 中实现 `capacity_metric_count`、`capacity_unknown_count` 和容量趋势展示：使用 `metadata.kpi_files[].records[].capacity_values` 按时间返回值；`unknown` 容量列只展示且生成低严重度 finding；如使用 `Metric.series`，只使用现有 `t/v` 契约，不修改 OpenAPI。
- [x] T028 [US6] 在 `tests/test_kpi_single_rule.py` 验证容量指标只展示、来源文件和周期可追溯，`confirmed` 容量列带口径，`unknown` 容量列生成 `capacity_semantics_unknown` 但不生成阈值告警；缺少请求成功/失败字段不会导致规则失败。

**检查点**：容量 KPI 展示与呼叫阈值检查分离，能独立通过验收场景。

---

## 阶段 9：收尾与横切关注点

**目的**：完成展示、迁移、隔离、幂等和交付验证。

- [x] T029 在 `web/src/components/KpiDetailTable.tsx` 新增只读 KPI 明细表，按文件、周期、时间、指标名、值和错误渲染 `RuleResult.metadata.kpi_files`；在 `web/src/pages/RuleDetailPage.tsx` 中展示该表；使用 OpenAPI 生成客户端类型，不手写不一致 API 调用。
- [x] T030 [P] 在 `docs/architecture.md` 更新 KPI 规则说明：三条规则、source pattern、私有无 prepare、`deploy/config/kpi_rules.yaml`、错误隔离和旧 `kpi.threshold` 下线。
- [x] T031 在 `tests/test_baseline_rerun.py` 增加三条新规则的单规则重跑测试：prepare 缺失不阻塞无 prepare 规则；只替换目标规则 JSON；同规则同输入重复执行结果一致（执行时间戳除外）。
- [x] T032 在 `tests/test_kpi_single_rule.py` 增加跨领域隔离测试：一个领域文件损坏或规则失败时，另外两条领域规则的结果、状态和证据不受影响；三类均无数据时三条规则均返回明确 `skip`。
- [x] T033 运行 `make lint`、`make test`、`make verify-one RULE=kpi.api`、`make verify-one RULE=kpi.media`、`make verify-one RULE=kpi.call`，并按 `specs/006-csv-kpi-inspection/quickstart.md` 验证代表性样例；修复发现的问题。
- [x] T034 运行 `make verify` 验证完整任务流；确认一个包、一个任务、一个输出目录，原始包未被修改，HTML/API 结果可追溯到 KPI 来源文件。

---

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：立即开始；T002 可与 T001 并行。
- **基础层（阶段 2）**：依赖 T001 的配置结构和预算定义；阻塞所有用户故事。
- **用户故事（阶段 3–8）**：均依赖阶段 2 完成。
  - US1 是规则实现前的识别验证，建议先完成。
  - US2、US3 可在 US1 后并行。
  - US4、US5、US6 都修改 `kpi.call` / 共享呼叫逻辑，建议按顺序执行；US4 完成后 US5 可先于 US6。
- **收尾（阶段 9）**：依赖 US1–US6 完成。

### 用户故事依赖

- **US1**：依赖共享解析器；不依赖领域规则。
- **US2**：依赖 US1 和 `common.py`；不依赖 US3–US6。
- **US3**：依赖 US1 和 `common.py`；不依赖 US2、US4–US6。
- **US4**：依赖 US1；建议在 US2/US3 后实现呼叫规则。
- **US5**：依赖 US4 的 `kpi.call` 骨架和固定 metrics。
- **US6**：依赖 US4 的呼叫结果契约；可与 US5 的实现评审交叉，但同文件任务应顺序执行。

### 每个故事内部

- 测试任务在实现任务之前。
- 先共享 parser/config，再规则注册，再结果构建。
- 每个故事完成后再进入下一个优先级。
- 同一个 `common.py`、`call.py` 的任务不得并行修改。

### 并行机会

- T001 与 T002 可并行。
- T003 与配置文件最终内容评审可并行，但 T004/T005 依赖 T001。
- US2 的 T009–T012 与 US3 的 T013–T016 在 `common.py` 稳定后可并行。
- T025、T029、T030 可在对应依赖完成后并行。
- T031、T032 可在全部领域规则完成后并行，但都依赖 T033 之前的基础测试稳定。

### 实现策略

#### MVP 优先

1. 完成阶段 1–4。
2. 独立验证文件识别与 API KPI。
3. 通过后再实现媒体与呼叫能力。

#### 完整交付

1. 完成阶段 1–8，确保六个用户故事都可独立追溯。
2. 完成阶段 9 的前端展示、文档、重跑和跨领域隔离验证。
3. 最终通过 `quickstart.md` 和全部质量门禁。

## 注意事项

- 不修改 `docs/api/openapi.yaml`；若实现中确需扩展公共 schema，必须回到 Speckit review。
- 不引入被检系统连接、在线采集、外部数据库或消息代理。
- 不建立普通规则依赖图；共享 helper 不能变成规则间输入。
- 不使用规则私有 prepare；规则直接读取自己的 `source_patterns` 匹配文件。
- 所有持久化时间为 UTC，字段使用 `*_at`。
- 所有 finding 必须包含任务内相对路径和 evidence。
