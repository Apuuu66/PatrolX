# 实现计划：告警生命周期与闪断检测

**分支**：`030-alarm-flapping` | **日期**：2026-10-09 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/030-alarm-flapping/spec.md` 的功能规格

## 摘要

新增独立告警规则 `alarm.flapping`（P1、告警类、初始 `rule_version=1.0.0`），按 `alarm_code + object` 分组，在单包数据上计算告警生命周期：出现次数、首次/最近出现、最长与累计持续、最短复发间隔、闪断事件序列。以"出现次数在复发窗口内 ≥ 阈值"判定反复，以"清除后到下次出现的间隔 ≤ 闪断间隔"合并闪断事件，以"清除后观察窗充足且无复发"才允许判为稳定恢复。

规则与 `alarm.stat` 读取同一批告警文件（`source_refs: ["alarm_all"]`），但独立解析、零依赖、无 prepare。结论通过既有 `RuleResult.status + metrics + findings + metadata.alarm_flapping` 交付：不新增接口、不改 OpenAPI、不改 `alarm.stat` 的语义与版本。默认操作窗 00:00–02:00 只做证据标注（窗口内/外出现、窗口外再现、窗口后仍未恢复），不降噪、不折叠、不降低主状态。

代表性样例包（`tests/fixtures/make_real_package.py` → `ZZapp01BCN_app_Problem_scene_333.zip`）按宪法 2.9.0 扩充：在既有告警压缩包内新增 `ALARM_CSV_003`（`alarm_history_202609010101137101_003.csv`，9 行：未清除反复、已清除反复、操作窗跨界的窗口外再现、稳定恢复、观察窗不足），既有 13 行语义与时间**保持不变**（只增不减）；既有短告警 `SCTP_LINK_DOWN / umf-node-01`（alarm_id 1002，26 秒）继续演示"短告警且观察窗充足仍不判稳定"，由 `is_short` 分支先于观察窗判定保证。扩充后覆盖 22 行 / 17 个分组 / 全部六种主状态与三条 Finding 路径。阈值以规则参数声明（`short_alarm_sec=300`、`repeat_window_sec=3600`、`min_repeat_count=3`、`flap_gap_sec=1800`、`stable_observation_sec=1800`、`operation_window=00:00-02:00`、`operation_window_enabled=true`），改默认值后单规则重跑即可验证结论变化。

## 技术上下文

**语言/版本**：Python 3.11+（仓库 `.venv` 为 3.12.x）

**主要依赖**：仅标准库（`csv`、`datetime`、`collections`、`statistics`）；不新增运行时依赖，不使用 pandas

**存储**：沿用文件存储；结果写入 `output/<task_id>/rules/alarm.flapping.json`，不新增目录层与存储结构

**测试**：pytest（解析/去重/状态机/阈值/操作窗/容错/单规则重跑/样例包看护）+ 前端 E2E + `python build.py lint/test/verify/web-build`

**目标平台**：macOS 开发机 + Linux 容器部署；本地 CLI 与在线 API 共用同一规则实现

**项目类型**：离线巡检系统（FastAPI 在线模式 + 本地 CLI 模式），两模式契约同构

**性能目标**：告警文件单次遍历 + 分组聚合；样例包（22 行 / 3 个 CSV）内规则耗时 < 100ms，大包下随行数线性增长、不引入明显劣化（FR-021）

**约束条件**：规则零跨规则依赖、无 prepare；阈值只影响判定不改变 `rule_version`；不改 OpenAPI 与既有契约字段；操作窗只作证据；观察窗不足不得判稳

**规模/范围**：1 条新规则 + 1 个规则元数据命名空间 + 1 个规则详情页面板 + 样例包扩充；不含跨包闪断历史、维护窗口计划内判定、告警与 KPI 关联

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 处理 |
| --- | --- | --- |
| 离线优先 | 通过 | 只读取任务内已解压告警文件，不引入在线采集与被检系统连接 |
| 一个包、一个任务 | 通过 | 只消费 `output/<task_id>/alarm/**`，不新增目录身份，不跨任务读取 |
| 契约驱动 | 通过 | 不新增 API、不改 `docs/api/openapi.yaml`；新增指标键与 `metadata.alarm_flapping` 命名空间，不改 `RuleResult`/`Metric`/`Finding` 字段语义 |
| 模式同构 | 通过 | 规则注册于同一注册表，CLI 与 API 共用执行器；输出契约一致（SC-006） |
| 巡检器插件架构 | 通过 | 以 `Inspector` 注册实现，不硬编码业务规则，不改调度器 |
| 源文件显式匹配 | 通过 | 声明 `source_refs: ["alarm_all"]` 展开为 `^alarm/.*$`；不导入/调用 `alarm.stat` 或其他规则，无规则间依赖图 |
| 增量重跑 | 通过 | 规则粒度持久化；`verify-one --rule alarm.flapping` 只重跑本规则（SC-006） |
| 解压先行 | 通过 | 不触碰解压流程；规则只读取已解压匹配文件 |
| 规则私有预处理 | 通过 | 不声明 prepare，无 prepared 数据，不涉及跨规则共享 |
| 幂等与可追溯 | 通过 | 固定排序键与去重键；Finding 携带 `source_file` + 行号 + 阈值证据；重复执行结果等价 |
| 轻量默认 | 通过 | 标准库实现、无外部服务、无新依赖；不改变默认单节点部署形态 |
| 容错 | 通过 | 单文件/单行失败隔离并计数，任务不中断；无文件或全部时间不可解析返回 `skip` + `skip_reason` |
| 安全解压 | 通过 | 不改动解压与路径校验 |
| 语言策略 | 通过 | 规格、计划、任务、代码注释与文档使用中文；标识符与字段使用英文 |

**阶段 1 复查**：设计未引入新契约字段、新依赖、新目录层或规则间依赖；观察窗与参数口径已固化为可测试规则；宪法 2.9.0 的样例包要求已进入 FR-025 与样例设计。结论不变。

## 阶段 0 研究结论

详见 [research.md](research.md)。关键决定：

1. **规则形态**：新增自包含规则 `alarm.flapping`（`source_refs: ["alarm_all"]`），不扩展 `alarm.stat`、不使用 prepare（R1）。
2. **覆盖窗口**：`coverage_start = min(created_at)`；`coverage_end = max(cleared_at ?? created_at)`；观察窗以分组最晚事实为参照（保守收紧，CR-005）（R2）。
3. **解析**：统一解码（UTF-8 / GB18030）、字段名大小写与空白容错、四项去重键、跨文件合并排序；文本行按未清除处理（R3）。
4. **判定算法**：单次遍历 + 分组聚合；滑动窗口判反复、清除到再现间隔并事件、观察窗充足才允许稳定（R4）。
5. **Finding 与规则状态**：三态映射 CRITICAL/HIGH/MEDIUM；Finding 最多 20 条按风险排序，完整明细进元数据（R5）。
6. **参数**：`Inspector.params` 声明式默认值，无站点级覆盖、无配置开关（R6）。
7. **操作窗**：默认 00:00–02:00、可关；只标注证据，不降噪（R7）。
8. **展示契约**：复用 `RuleResult.metadata.alarm_flapping`；前端在 `RuleDetailPage` 增加条件渲染面板；不改 OpenAPI（R8）。
9. **样例包**：`make_real_package.py` 新增 `ALARM_CSV_003`（9 行），既有 13 行不动；固定字面量、幂等（R9）。
10. **性能/容错/时区/重跑**：标准库单遍扫描、单文件与单行失败隔离、带时区记录统一换算、无 prepare 保证单规则重跑一致（R10–R12）。

## 阶段 1 设计

### 1. 规则实现（`app/inspectors/alarm/flapping.py`）

- `Inspector` 元数据：`code="alarm.flapping"`、`name="告警闪断检测"`、`category=ALARM`、`priority=P1`、`severity=HIGH`、`rule_version="1.0.0"`、`source_refs=["alarm_all"]`、完整 `description`/`recommendation`/`outputs_metrics`/`params`。
- 模块级 `FlappingPolicy`（dataclass，`slots=True`）承载七个参数默认值；`inspector.params` 由同一默认表生成，避免声明值与计算值脱节。参数可通过修改默认值后单规则重跑验证。
- 执行链路：`ctx.resolved_files()` → 统一解码逐行解析 → 记录级校验/去重 → 全局排序 → 按 `(alarm_code, object)` 分组 → 单次遍历计算 → 组装 `RuleResult`。
- 分组明细、策略副本、覆盖窗口、计数与截断标记写入 `metadata["alarm_flapping"]`；Finding 仅输出 `uncleared_repeated`/`cleared_repeated`/`cleared_short` 三类，最多 20 条。
- 不声明 prepare、不写 `prepared/` 目录、不读取其他规则结果。

### 2. 判定算法要点

- 反复：以出现时间为轴的滑动窗口，存在**从某次出现起算、跨度 ≤ `repeat_window_sec`** 的区间包含 ≥ `min_repeat_count` 次出现（相邻出现时间差回看判定，FR-008；不等价于分组首末出现跨度）。
- 闪断事件：前次清除到下次出现 ≤ `flap_gap_sec` 并入同一事件；前次未清除时后续出现一律并入（FR-009）。
- 观察窗：`observation_gap_sec = coverage_end - 分组最晚一次清除时间`；存在未清除记录，或该间隔不足 `stable_observation_sec`，则 `observation_insufficient = true`（CR-005 保守口径，以最晚事实为参照）。
- 主状态按 [data-model.md](data-model.md) §7 优先链互斥输出；`observation_insufficient` 为独立标记，可与其他状态共存。
- 规则状态：存在未清除反复或已清除反复 → `fail`；仅短告警/未清除未反复/观察窗不足 → `warn`；否则 `pass`；无文件或全部记录时间不可解析 → `skip` + 非空 `skip_reason`（FR-014、FR-015）。

### 3. 操作窗

- 默认 `00:00-02:00`，按每条记录**所在自然日**的本地时间判定；`operation_window_enabled=false` 时不做归属统计。
- 输出 `in_window_occurrences` / `out_of_window_occurrences` / `out_of_window_reappear` / `unrecovered_after_window`；窗口命中不改变主状态、不产生静默或折叠（FR-022–FR-024）。

### 4. 展示与消费

- `web/src/pages/RuleDetailPage.tsx`：当 `result.metadata.alarm_flapping` 存在时渲染"告警生命周期分组"卡片（状态、出现次数、首次/最近出现、最短复发间隔、观察窗标记、操作窗标记），按状态优先级排序；API 客户端与 OpenAPI 不变。
- HTML 报告：Finding 区块已覆盖三条 Finding 的标题、证据、来源与建议；本版不新增报告模板字段。
- 规则详情页与报告均直接读取既有 `RuleResult`，无前端手写接口调用。

### 5. 样例包与看护测试

- `tests/fixtures/make_real_package.py`：在既有 `alarm_history_202609010101137101.zip` 内新增 `ALARM_CSV_003`（`alarm_history_202609010101137101_003.csv`，9 行，覆盖未清除反复、已清除反复、操作窗跨界、稳定恢复、观察窗不足）；既有 13 行语义与时间保持不变；行顺序为 1050×2（行 2–3）、1051×3（行 4–6）、1052×3（行 7–9）、1053×1（行 10），既有样例的 `alarm_code` 为符号名（`1002`/`1008`/`1009` 是 `alarm_id`），新增行使用数字告警码 `1050`–`1053`；`1053` 于 `2026-09-02 12:00` 出现、`12:05:30` 清除（330 秒，覆盖窗末端），演示"已清除但观察窗为零"。扩充后 alarm.stat 断言为：总量 22、未处理 11、严重级 `CRITICAL 6 / HIGH 8 / MEDIUM 6 / LOW 2`。
- 新增 `__main__` CLI 入口：`.venv/bin/python tests/fixtures/make_real_package.py <目录>`，便于 quickstart 与人工复核。
- 同步更新既有断言：`tests/test_real_package.py`（`alarm.stat` 总量 13 → 22、未处理 8 → 11、严重级分布 `CRITICAL 6 / HIGH 8 / MEDIUM 6 / LOW 2`）与 `tests/test_sample_guard.py`（预期跳过集合不变、新增 `alarm.flapping` 必须出现在结果中）。
- 新增 `tests/test_alarm_flapping.py`：规则元数据、六态判定、重复行、时钟倒挂、部分/全部时间不可解析、对象缺失、TXT/CSV 混合、单文件解析失败、参数变化重跑、单规则重跑一致性。
- 前端新增 E2E：真实样例包执行后，规则详情页"告警生命周期分组"可见且四类结论可区分（SC-005、SC-008）。

### 6. 兼容与边界

- `alarm.stat` 的模型、字段、语义与 `rule_version` 零变化；两规则匹配同一批文件、独立解析。
- `RuleResult` / `Metric` / `Finding` 字段含义不变；新增命名空间与指标键可被旧前端忽略，不构成破坏性变更。
- 本版不新增接口，因此无需 `python build.py contract` / `gen-web-api`；若实现阶段发现展示必须新增对外字段，先更新 OpenAPI 再实现。
- 不引入跨包状态、缓存、数据库或站点级配置；设备身份解析与跨包时间轴留给 031。

## 项目结构

### 文档（本功能）

```text
specs/030-alarm-flapping/
├── plan.md                              # 本文件
├── research.md                          # 阶段 0 输出
├── data-model.md                        # 阶段 1 输出
├── quickstart.md                        # 阶段 1 输出
├── contracts/
│   └── alarm-flapping-result.md         # 规则结果元数据契约
└── tasks.md                             # 阶段 2 输出（$speckit-tasks）
```

### 源代码（仓库根目录）

```text
app/
└── inspectors/
    └── alarm/
        ├── stat.py                      # 不改语义与版本
        └── flapping.py                  # 新增：告警生命周期与闪断规则

web/
└── src/pages/
    └── RuleDetailPage.tsx               # 新增条件渲染的分组面板

tests/
├── fixtures/make_real_package.py        # 新增 ALARM_CSV_003 + CLI 入口（既有 13 行不动）
├── test_alarm_flapping.py               # 新增：解析/判定/容错/重跑
├── test_real_package.py                 # 更新 alarm.stat 断言并新增 flapping 断言
└── test_sample_guard.py                 # 保证新规则在真实样例包中非 skip

web/e2e/                                 # 规则详情页分组面板 E2E
docs/architecture.md                     # 规则清单补充 alarm.flapping
docs/design/mechanisms.md                # 告警生命周期判定机制说明
AGENTS.md                                # 新规则约定与样例包要求的既有条款已覆盖
```

**结构决策**：规则放在 `app/inspectors/alarm/` 下与 `stat.py` 同级，保持 `api → services → inspectors/models` 分层；展示复用既有规则详情页与报告，不新增页面、服务或接口。

## 复杂度跟踪

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 新增 `metadata.alarm_flapping` 命名空间（对外可观察结构） | FR-020 要求分组明细可被规则详情页与报告读取，而本版不允许新增接口 | 新增独立查询接口：超出范围且触发 OpenAPI 变更；把明细塞进 Finding：会淹没顶部告警且不满足"稳定分组零 Finding" |
| Finding 上限 20 条 | 大包下 Finding 数量必须可控，同时保留完整证据 | 每个分组都出 Finding：值班首屏被淹没；只出聚合 Finding：丢失可追溯性（违反幂等与可追溯） |
| 观察窗口径取"最晚事实"：存在未清除记录直接标记不足，否则按最后清除时间到覆盖末端计算 | 避免覆盖期内反复出现或仍未恢复的分组被误判为稳定，符合"已清除不等于已解决"的核心诉求 | 只看最后清除时间：反复闪断或仍有未清除记录的分组会产出假稳定，违反 SC-003 的意图 |
