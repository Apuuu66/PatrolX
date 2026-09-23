---
description: "KPI 跨任务历史趋势实现任务列表"
---

# 任务：KPI 跨任务历史趋势

**输入**：来自 `/specs/025-kpi-cross-task-trend/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/api.md、quickstart.md

**测试**：项目质量门禁要求关键场景必须有测试；以下任务按 TDD 执行，先写测试并确认失败，再实现。

**组织方式**：任务按用户故事分组；实现 worktree 必须从已提交全部 Speckit 产物的 `main` 创建。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事
- 路径均相对仓库根目录

---

## 阶段 1：设置（共享契约与类型）

**目的**：先固化 OpenAPI 和生成客户端，避免实现与契约漂移。

- [ ] T001 更新 `docs/api/openapi.yaml`：为 `Body_createTaskV2` 新增可选 `device_id`，为 `TaskSummary` 新增 `device_id`，新增 `TaskDeviceIdUpdateRequest`、`MeasurementHistoryTrend` 及嵌套 Schema，新增 `PATCH /api/v2/tasks/{task_id}/device-id` 和 `GET /api/v2/tasks/{task_id}/rules/{rule_code}/measurement-units/{measurement_unit_id}/metrics/{metric_resource_id}/history-trend`
- [ ] T002 执行 `.venv/bin/python build.py contract` 校验 T001，并执行 `.venv/bin/python build.py gen-web-api` 生成 `web/src/api/client.ts`
- [ ] T003 [P] 在 `app/models/schemas.py` 中新增历史趋势响应 Pydantic 模型，字段和枚举与 `data-model.md`、`contracts/api.md` 完全一致
- [ ] T004 [P] 在 `web/src/api/http.ts` 中新增设备 ID 更新和单指标历史趋势的类型化 API 方法，复用生成的 client 类型，不手写与 OpenAPI 冲突的请求结构

**检查点**：OpenAPI、Pydantic、前端客户端类型已对齐；后续实现不得修改契约语义。

---

## 阶段 2：用户故事 1 - 标记和维护设备 ID（优先级：P1）🎯 MVP

**目标**：任务创建时保存设备 ID，admin 可创建后修改，重跑/重建不丢失。

**独立测试**：创建任务填写设备 ID 后，任务详情能显示；admin 修改后详情和历史匹配使用新值；普通用户修改被拒绝；重跑/重建后仍保留。

### 用户故事 1 的测试

- [ ] T005 [P] [US1] 在 `tests/test_kpi_device_history.py` 中编写 API 测试：创建时保存并 trim `device_id`；`TaskSummary.device_id` 正确展示；空设备 ID 允许；非空长度必须为 1–128
- [ ] T006 [P] [US1] 在 `tests/test_kpi_device_history.py` 中编写设备 ID 修改测试：admin 成功修改并同步 `task.json` / `system.json`；viewer 返回 403；pending/running 返回 409；任务不存在返回 404
- [ ] T007 [P] [US1] 在 `tests/test_kpi_device_history.py` 中编写重跑/重建测试：重跑、全量重建和增量重建后 `customer.device_id` 保持不变
- [ ] T007b [P] [US1] 在 `tests/test_kpi_device_history.py` 中补充索引刷新断言：重跑、全量重建和增量重建后 `output/<task_id>/kpi/history/index.jsonl` 与最新任务结果一致，且不残留旧任务索引点

### 用户故事 1 的实现

- [ ] T008 [US1] 在 `app/services/tasks.py` 的 `reserve` 和创建链路中接收并保存 `device_id` 到 `TaskRecord.customer["device_id"]`，保存前去除首尾空格
- [ ] T009 [US1] 在 `app/api/router.py` 的 `create_task_v2` 中新增 `device_id: str | None = Form(None)` 并透传给 `TaskService.reserve`
- [ ] T010 [US1] 在 `app/models/schemas.py` 的 `TaskSummary` 中新增 `device_id`，并在 `app/services/tasks.py` 的 `list_tasks`、SQLite 兜底列表和详情返回中从任务 customer 派生该字段
- [ ] T011 [US1] 在 `app/services/tasks.py` 中实现设备 ID 更新服务：校验 trim 后长度 1–128，拒绝 pending/running，同步更新 SQLite、`output/<task_id>/system.json` 和 `task.json`
- [ ] T012 [US1] 在 `app/api/router.py` 中新增 `PATCH /tasks/{task_id}/device-id`，operation_id 为 `updateTaskDeviceIdV2`，使用 `require_role("admin")` 并返回 `TaskSummary`
- [ ] T013 [US1] 在 `web/src/pages/TaskListPage.tsx` 的上传表单中新增可选“设备 ID”输入框，提交前 trim，并随 FormData 发送
- [ ] T014 [US1] 在 `web/src/pages/TaskDetailPage.tsx` 中用“设备 ID”替代裸 JSON 展示；admin 可编辑，编辑成功后刷新任务详情，失败时显示后端错误信息

**检查点**：用户故事 1 应完整可用且可独立测试；此时历史能力尚未开放。

---

## 阶段 3：用户故事 2 - 查看同一设备的历史趋势（优先级：P1）

**目标**：按设备、测量单元、指标、行对象和周期读取历史点，并提供单指标按日对齐曲线。

**独立测试**：准备两个以上相同设备 ID、不同日期的完成任务，查询同一维度趋势；确认能返回 7 天窗口、按日曲线和来源任务。

### 用户故事 2 的测试

- [ ] T015 [P] [US2] 在 `tests/test_kpi_history_index.py` 中编写索引生成测试：`inspect_measurement_files` 后生成 `output/<task_id>/kpi/history/index.jsonl`；每行为 UTF-8 JSONL；包含 `task_id`、`measurement_unit_id`、`metric_resource_id`、`object_key`、`period_minutes`、`measured_at`、`value`、`source_file`；不包含 `device_id`
- [ ] T016 [P] [US2] 在 `tests/test_kpi_history_index.py` 中编写解析与删除测试：空值、解析失败值不入索引；同任务重复时间点沿用均值去重；删除任务目录后索引不可访问
- [ ] T017 [P] [US2] 在 `tests/test_kpi_history_service.py` 中编写匹配测试：只匹配相同 `device_id`、测量单元、指标、行对象和周期；设备不同、对象不同、周期不同、指标不同均零混合
- [ ] T018 [P] [US2] 在 `tests/test_kpi_history_service.py` 中编写窗口和冲突测试：窗口为当前任务最新 UTC 测量日及前 6 个自然日；跨任务同时间点保留候选任务中完成时间最新的值；完成时间相同按 `task_id` 倒序
- [ ] T019 [P] [US2] 在 `tests/test_kpi_history_api.py` 中编写 API 契约测试：`history-trend` 返回 `MeasurementHistoryTrend`；参数缺失返回 422/400；任务、规则、测量单元或指标不存在返回 404

### 用户故事 2 的实现

- [ ] T020 [US2] 在 `app/services/kpi_history.py` 中实现索引记录、原子写入、流式读取和索引校验；写入路径固定为 `output/<task_id>/kpi/history/index.jsonl`
- [ ] T021 [US2] 在 `app/services/kpi_measurement_units.py` 的 KPI 结果组织完成后调用索引写入器，为每个原始绑定指标的有效时间序列生成去重索引
- [ ] T022 [US2] 在 `app/services/kpi_history.py` 中实现历史查询服务：读取当前任务元数据和候选任务索引，过滤 7 天窗口，排除当前任务，只使用 `completed` 且完成时间不晚于当前任务的任务
- [ ] T023 [US2] 在 `app/services/kpi_history.py` 中组装 `current_points`、`history_series`、`coverage`、`source_tasks` 和 UTC `date` / `time_label`
- [ ] T024 [US2] 在 `app/api/router.py` 中实现 `getMeasurementHistoryTrendV2`，必填 query 为 `object_key` 和 `period_minutes`；服务层返回当前指标存在但历史不可用的降级投影而不是 404
- [ ] T025 [US2] 在 `web/src/utils/measurementHistory.ts` 中实现响应解析、按日/时刻分组和 `__all__` 周期展示辅助
- [ ] T026 [P] [US2] 在 `web/src/utils/measurementHistory.test.ts` 中覆盖按日分组、时间排序、多任务同日合并和无效点过滤
- [ ] T027 [US2] 在 `web/src/components/MeasurementTrendChart.tsx` 中增加“历史对比”视图：打开趋势弹窗且设备 ID 存在时调用 `getMeasurementHistoryTrend`，展示按日曲线、当前任务曲线、日期图例和点来源任务
- [ ] T028 [US2] 在 `web/src/components/MeasurementTrendChart.tsx` 中增加行对象和周期选择器；默认选择当前单任务主趋势的 `object_key` 与 `period_minutes`

**检查点**：用户故事 1 和 2 均可独立验证；历史曲线可追溯到任务和来源文件。

---

## 阶段 4：用户故事 3 - 历史基线和偏差解释（优先级：P1）

**目标**：为同一时刻输出可解释的中位数基线、当前值、偏差和显著偏离结论。

**独立测试**：构造当前值明显高于或低于历史同时刻的场景，确认摘要显示基线、偏差、样本数和日期数；正常值不误报。

### 用户故事 3 的测试

- [ ] T029 [P] [US3] 在 `tests/test_kpi_history_service.py` 中编写基线测试：同时刻样本使用中位数；样本数少于 3 时 `significance=insufficient`；偏差、偏差比例和覆盖日期数正确
- [ ] T030 [P] [US3] 在 `tests/test_kpi_history_service.py` 中编写显著偏离测试：偏离超过中位数 + MAD 鲁棒阈值时标记 `higher` / `lower`；正常波动标记 `normal`；基线为 0 时不产生非有限值
- [ ] T031 [P] [US3] 在 `web/src/utils/measurementHistory.test.ts` 中编写前端摘要测试：格式化基线、偏差、比例、样本数、覆盖日期数和显著方向

### 用户故事 3 的实现

- [ ] T032 [US3] 在 `app/services/kpi_history.py` 中实现 `baseline_points`：按 `HH:mm` 汇总历史值，使用中位数、MAD、3 倍 scale 和 10% 可解释阈值，输出 `HistoryBaselinePoint`
- [ ] T033 [US3] 在 `app/services/kpi_history.py` 中将当前任务同 `HH:mm` 最新值与基线配对；无当前点或样本不足时不得给出显著结论
- [ ] T034 [US3] 在 `web/src/utils/measurementHistory.ts` 中实现历史基线摘要对象和中英文状态映射
- [ ] T035 [US3] 在 `web/src/components/MeasurementTrendChart.tsx` 中展示窗口日期、历史任务数、覆盖日期数、样本数、基线值、偏差、偏差比例和显著点列表
- [ ] T036 [US3] 在 `web/src/components/MeasurementTrendChart.tsx` 的历史图表中绘制虚线“历史基线”，并高亮显著偏离点

**检查点**：历史趋势不仅有多日曲线，还能直接解释当前值是否显著偏离。

---

## 阶段 5：用户故事 4 - 无历史或数据不足时可靠降级（优先级：P2）

**目标**：所有不可比较场景都有明确原因，并保留单任务趋势。

**独立测试**：分别构造无设备 ID、无历史任务、索引缺失、周期不同和样本不足场景，确认中文降级原因和单任务趋势仍可用。

### 用户故事 4 的测试

- [ ] T037 [P] [US4] 在 `tests/test_kpi_history_service.py` 中编写降级测试：当前设备 ID 缺失、当前最新测量时间缺失、历史索引缺失、候选任务设备 ID 缺失、样本不足分别返回对应 `reason_code`
- [ ] T038 [P] [US4] 在 `tests/test_kpi_history_api.py` 中编写 HTTP 降级测试：历史不可用仍返回 200 和 `match.status`；只有当前任务或指标不存在才返回 404
- [ ] T039 [P] [US4] 在 `web/src/utils/measurementHistory.test.ts` 中编写降级文案映射测试：覆盖 `device_id_missing`、`current_measurement_time_missing`、`history_index_missing`、`period_mismatch`、`metric_not_supported`、`insufficient_samples`
- [ ] T040 [P] [US4] 在 `tests/test_kpi_device_history.py` 中补充设备 ID 修改后的历史匹配测试：修改为空后历史降级，修改为另一设备后不匹配旧设备历史

### 用户故事 4 的实现

- [ ] T041 [US4] 在 `app/services/kpi_history.py` 中实现统一降级结构：`matched`、`no_history`、`degraded` 和 `reason_code`；不得抛出业务错误替代降级
- [ ] T042 [US4] 在 `app/services/kpi_history.py` 中保证索引缺失不触发自动回填，也不回退加载整个 `system.json` 或 KPI 规则 JSON
- [ ] T043 [US4] 在 `web/src/components/MeasurementTrendChart.tsx` 中根据 `match` 显示中文 Alert，历史失败或无历史时自动保留单任务趋势和重试按钮
- [ ] T044 [US4] 在 `web/src/components/MeasurementTrendChart.tsx` 中为样本不足、周期不一致、索引缺失和设备缺失展示不同说明，避免把降级渲染成异常结论

**检查点**：历史不可用时不会误导巡检人员，单任务能力不被破坏。

---

## 阶段 6：用户故事 5 - 大指标量下按需查看（优先级：P2）

**目标**：600+ 指标首屏不加载历史，单个趋势弹窗只请求单指标数据。

**独立测试**：浏览任务结果首屏确认无历史请求；打开一个指标弹窗只发起一次该指标、对象、周期的请求；切换维度时重新请求。

### 用户故事 5 的测试

- [ ] T045 [P] [US5] 在 `tests/test_kpi_history_service.py` 中编写流式读取测试：生成包含多个指标/对象/周期的索引后，查询只读取匹配维度并保持常量级可控行为；响应不包含其他指标点
- [ ] T046 [P] [US5] 在 `tests/test_kpi_history_api.py` 中编写响应体测试：单次响应最多包含当前指标、当前对象、当前周期和 7 天窗口数据
- [ ] T047 [P] [US5] 在 `web/src/components/MeasurementTrendChart.test.tsx` 中编写交互测试：任务首屏渲染趋势缩略图不请求历史；打开弹窗请求一次；切换对象或周期重新请求；历史失败重试只请求当前维度

### 用户故事 5 的实现

- [ ] T048 [US5] 在 `app/services/kpi_history.py` 中按行读取 JSONL，逐行反序列化并立即过滤；不得把全部索引文件读成数组后过滤
- [ ] T049 [US5] 在 `app/api/router.py` 中为历史接口增加响应模型校验，确保只返回 `MeasurementHistoryTrend` 声明字段，不返回原始整段规则结果
- [ ] T050 [US5] 在 `web/src/components/MeasurementInspectionPanel.tsx` 中确认 `MetricTrendCell` 只接收当前指标摘要，不新增任务级历史数据加载
- [ ] T051 [US5] 在 `web/src/components/MeasurementTrendChart.tsx` 中使用弹窗状态缓存当前维度结果；关闭弹窗释放状态，切换维度时展示 loading 并取消旧请求语义

**检查点**：600+ 指标任务首屏不受历史能力影响，单指标历史响应可控。

---

## 阶段 7：收尾与横切关注点

**目的**：验证任务隔离、双模式行为、契约一致性和质量门禁。

- [ ] T052 [P] 在 `docs/architecture.md` 的 KPI 或运行时数据章节补充 `kpi/history/index.jsonl` 的职责、生命周期和任务隔离说明
- [ ] T053 [P] 在 `docs/data-model.md` 或最接近的 KPI 数据章节链接 `specs/025-kpi-cross-task-trend/data-model.md`，说明设备 ID 与历史索引存储边界
- [ ] T054 在 `tests/test_kpi_device_history.py` 中补充任务删除测试：删除任务后 SQLite、`uploads/<task_id>`、`output/<task_id>` 和历史索引都不可访问
- [ ] T055 在 `tests/test_baseline_pipeline.py` 或新增 `tests/test_kpi_history_local_mode.py` 中验证本地/CLI 巡检也会生成相同结构的索引；无设备 ID 的本地任务不参与历史匹配
- [ ] T056 运行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确认最终代码没有契约漂移
- [ ] T057 运行 `.venv/bin/python build.py lint` 和 `.venv/bin/python build.py test`
- [ ] T058 运行 `cd web && npm test && npm run build`
- [ ] T059 运行 `.venv/bin/python build.py verify`，并按 `specs/025-kpi-cross-task-trend/quickstart.md` 检查设备 ID、历史趋势、降级、按需加载和任务删除场景
- [ ] T060 检查 `git status`，确认所有新增测试、索引样例和文档已提交；任务清单复选框全部更新

---

## 依赖与执行顺序

### 阶段依赖

```text
阶段 1 契约与类型
  └── 阶段 2 设备 ID（US1）
        └── 阶段 3 历史匹配与索引（US2）
              ├── 阶段 4 基线解释（US3）
              ├── 阶段 5 可靠降级（US4）
              └── 阶段 6 按需性能（US5）
                    └── 阶段 7 收尾与验证
```

- T001 → T002 必须最先完成。
- T003 / T004 依赖 T001，可并行。
- US1 是历史匹配的设备归属基础，必须先于 US2 完成。
- US2 的索引和查询服务是 US3 / US4 / US5 的前置。
- US3 / US4 / US5 可在 US2 完成后按优先级或并行推进；并行时注意 `app/services/kpi_history.py`、`app/api/router.py` 和 `web/src/components/MeasurementTrendChart.tsx` 的合并冲突。
- 阶段 7 必须最后执行。

### 用户故事依赖

- **US1**：只依赖阶段 1。
- **US2**：依赖 US1 的设备 ID 存储和读取。
- **US3**：依赖 US2 的历史点投影。
- **US4**：依赖 US2 的查询路径；建议在 US3 前后都可以实现，但最终需与 US3 联合验证。
- **US5**：依赖 US2 的索引读取和前端历史视图；需要与 US3/US4 的展示逻辑集成验证。

### 关键路径

1. OpenAPI → 生成客户端。
2. 设备 ID 创建/修改。
3. 历史索引生成。
4. 历史查询服务。
5. 历史 API。
6. 历史弹窗。
7. 基线、降级、性能验证。

---

## 并行机会

### 阶段 1

- T003 与 T004 可并行，但都必须在 T001/T002 后开始。

### 用户故事 1

- T005、T006、T007 三个测试文件任务可并行起草。
- T008 / T009 属于同一创建链路，建议串行。
- T013 与后端 T011 / T012 可并行，但联调依赖契约已生成。

### 用户故事 2

- T015、T016、T017、T018、T019 测试可并行起草。
- T025 / T026 前端工具与 T020–T024 后端服务可并行，只要契约已固定。
- T027 / T028 建议在 T025 后串行，避免同文件冲突。

### 用户故事 3–5

- 三个故事的测试任务可并行准备。
- 后端基线、降级和性能优化会修改同一服务文件，建议由同一实现者串行处理。
- 前端摘要、降级和按需交互会修改同一趋势组件，建议合并成一个前端串行序列。

---

## 并行示例

```text
# 契约完成后
T003: app/models/schemas.py 历史响应模型
T004: web/src/api/http.ts API 方法

# US2 测试先行
T015: tests/test_kpi_history_index.py
T017: tests/test_kpi_history_service.py
T019: tests/test_kpi_history_api.py

# US2 后端完成后
T029: tests/test_kpi_history_service.py 基线
T037: tests/test_kpi_history_service.py 降级
T045: tests/test_kpi_history_service.py 流式读取
```

---

## 实现策略

### MVP 优先（US1 + 最小 US2）

1. 完成阶段 1。
2. 完成 US1，验证设备 ID 创建、展示、修改和保留。
3. 完成 US2 的索引、匹配、窗口和基础历史曲线。
4. 停止验证 MVP；此时已具备跨任务趋势主干。
5. 再补充 US3 基线、US4 降级、US5 性能交互。

### 增量交付

1. US1：设备归属可用。
2. US2：多日历史曲线可用。
3. US3：历史结论可解释。
4. US4：降级可信。
5. US5：大规模指标场景不拖慢首屏。
6. 阶段 7：全量验证和文档补齐。

### 质量门禁

每个用户故事完成后至少运行对应测试；合并前必须完成阶段 7 的全部验证任务。涉及 API 的任何语义调整必须回到 plan/spec review，不得直接改实现绕过契约。
