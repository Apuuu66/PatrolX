# 任务：基于测量单元的 KPI 巡检

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/api.md`

## 阶段 1：设置

- [ ] T001 在 `specs/017-kpi-measurement-units/` 保存规格、计划、研究、数据模型、API 契约和快速验证文档
- [ ] T002 从 `main` 创建实现分支与 `.worktrees/017-kpi-measurement-units`，并确认干净基线

## 阶段 2：基础层

- [ ] T003 在 `app/models/db.py` 删除旧 KPI 表并新增测量资源、绑定、派生定义模型
- [ ] T004 在 `app/models/schemas.py` 删除旧 KPI Schema，新增资源导入、目录、绑定、派生和巡检结果契约
- [ ] T005 在 `app/services/kpi_measurement_units.py` 实现资源 CSV upsert、MU 开关、绑定查询/确认和派生定义服务
- [ ] T006 在 `app/inspectors/kpi/measurement.py` 实现文件匹配、CSV 锚点解析、候选发现、行对象聚合和派生成功率
- [ ] T007 在 `app/api/router.py` 删除旧 KPI 路由并新增 v5 资源/绑定/派生管理接口
- [ ] T008 在 `app/api/openapi.yaml` 同步删除旧 KPI 接口并新增 v5 契约
- [ ] T009 在 `web/src` 删除旧 KPI 页面组件，新增测量单元目录与任务结果面板

## 阶段 3：用户故事 1 - 维护测量单元资源目录（P1）

- [ ] T010 [P] [US1] 在 `tests/test_kpi_measurement_resources.py` 增加导入新增、重复 upsert、不删除缺失资源、非法前缀、禁用开关用例
- [ ] T011 [P] [US1] 在 `tests/test_kpi_measurement_api.py` 增加 CSV 上传、列表分页、MU 启停接口用例
- [ ] T012 [US1] 实现/修正 `app/services/kpi_measurement_units.py` 与 `app/api/router.py`，通过 US1 测试

## 阶段 4：用户故事 2 - 任务文件归属（P1）

- [ ] T013 [P] [US2] 在 `tests/test_kpi_measurement_matching.py` 增加精确匹配、大小写拒绝、多文件、unmatched、ambiguous、disabled、parse_error 用例
- [ ] T014 [US2] 实现/修正文件片段匹配与发现状态，通过 US2 测试

## 阶段 5：用户故事 3 - 指标绑定发现与确认（P1）

- [ ] T015 [P] [US3] 在 `tests/test_kpi_measurement_binding.py` 增加单位括号剥离、候选保留、未确认不巡检、冲突不改绑、未注册列用例
- [ ] T016 [US3] 实现/修正任务候选发现与绑定持久化，通过 US3 测试

## 阶段 6：用户故事 4 - 测量单元巡检结果（P1）

- [ ] T017 [P] [US4] 在 `tests/test_kpi_measurement_inspector.py` 增加全部可读、列缺失、空值、解析失败、全 0、无绑定 skip 用例
- [ ] T018 [US4] 实现/修正指标观察与 MU 汇总，通过 US4 测试
- [ ] T019 [US4] 集成任务包端到端用例，验证规则结果可读取且单文件失败隔离

## 阶段 7：用户故事 5 - 行对象观察（P2）

- [ ] T020 [P] [US5] 在 `tests/test_kpi_measurement_objects.py` 增加多 Pod、单对象异常、重复对象聚合、无维度列默认对象用例
- [ ] T021 [US5] 实现/修正行对象锚点与统计，通过 US5 测试

## 阶段 8：用户故事 6 - 成功率派生指标（P3）

- [ ] T022 [P] [US6] 在 `tests/test_kpi_measurement_derived.py` 增加正常计算、分母 0、依赖缺失/空值/解析失败用例
- [ ] T023 [US6] 实现派生定义管理与按对象计算，通过 US6 测试

## 阶段 9：收尾

- [ ] T024 删除旧 KPI 实现文件、测试、样例和前端组件，更新架构文档与路由菜单
- [ ] T025 执行 `python build.py contract && python build.py gen-web-api`
- [ ] T026 补充 OpenAPI/Pydantic 契约一致性和前端关键模型用例
- [ ] T027 执行 `python build.py lint && python build.py test`
- [ ] T028 执行 `python build.py verify`
- [ ] T029 提交实现，按用户要求推送并清理 worktree

## 依赖与执行顺序

- T002 → T003 → T004/T005/T006/T007/T008/T009 可按依赖推进。
- US1 是资源维护基线；US2、US3、US4 依赖基础层；US5、US6 依赖 US4。
- 测试任务先确认失败，再实现对应服务/规则。
- T024 后必须重新执行契约生成与全量验证。

## 并行机会

- T010/T011、T013、T015、T017、T020、T022 分属独立测试文件，可并行补充。
- 前端面板与后端模型可并行设计，但接口契约先冻结。

## 实现策略

按基础层 → US1 → US2 → US3 → US4 → US5 → US6 → 收尾执行；每个优先级完成后先跑局部测试再进入下一阶段。
