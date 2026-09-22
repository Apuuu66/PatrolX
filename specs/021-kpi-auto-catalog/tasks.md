# 任务：KPI 自动目录与进阶巡检（021-024 统一实现）

## 阶段 1：准备

- [ ] T001 在 `app/models/db.py` 中扩展 KPI 测量资源、阈值策略和趋势结果相关字段/表
- [ ] T002 在 `app/models/schemas.py` 中同步契约模型
- [ ] T003 在 `docs/api/openapi.yaml` 中同步资源、绑定、阈值、趋势和总览相关字段

## 阶段 2：021 自动目录

- [ ] T004 [P] [US1] 在 `app/services/kpi_measurement_units.py` 中实现自动创建/复用 ME 指标，并初始化启用、方向、重要级别、分组、显示顺序和阈值默认值
- [ ] T005 [P] [US1] 在 `app/services/kpi_measurement_units.py` 中实现预制目录增量导入与合并；缺失治理字段按默认值初始化，且不得覆盖已有值
- [ ] T006 [US1] 在 `app/inspectors/kpi/measurement.py` 中默认启用自动入库指标并移除人工确认主流程
- [ ] T007 [US1] 在 `tests/test_kpi_measurement_inspector.py` 中补充自动入库与幂等重跑测试
- [ ] T008 [US1] 在 `tests/test_kpi_measurement_resources.py` 中补充预制目录增量导入测试

## 阶段 3：022 阈值

- [ ] T009 [US2] 在 `app/services/kpi_measurement_units.py` 中实现阈值策略保存与方向校验
- [ ] T010 [US2] 在 `app/inspectors/kpi/measurement.py` 中输出业务状态，并保留可读性结论
- [ ] T011 [US2] 在 `tests/test_kpi_measurement_inspector.py` 中补充阈值状态测试
- [ ] T012 [US2] 在 `docs/api/openapi.yaml` 中同步阈值字段

## 阶段 4：023 趋势

- [ ] T013 [US3] 在 `app/services/kpi_measurement_units.py` 中解析任务内时间序列并生成趋势标签
- [ ] T014 [US3] 在 `app/inspectors/kpi/measurement.py` 中输出迷你趋势、完整趋势证据和诊断
- [ ] T015 [US3] 在 `tests/test_kpi_measurement_inspector.py` 中补充趋势标签测试
- [ ] T016 [US3] 在 `docs/api/openapi.yaml` 中同步趋势字段

## 阶段 5：024 总览与健康分

- [ ] T017 [US4] 在 `app/services/kpi_measurement_units.py` 中计算测量单元健康分和 KPI 总览
- [ ] T018 [US4] 在 `app/inspectors/kpi/measurement.py` 中输出总览和重点指标排序
- [ ] T019 [US4] 在 `web/src/pages/MeasurementUnitsPage.tsx` 中展示总览、健康分和重点指标
- [ ] T020 [US4] 在 `web/src/api/http.ts` 中接入新增契约字段
- [ ] T021 [US4] 在 `tests/test_kpi_measurement_api.py` 中补充总览和健康分契约测试

## 阶段 6：收尾

- [ ] T022 同步生成前端 API 客户端
- [ ] T023 运行 `python build.py contract`
- [ ] T024 运行 `python build.py lint`
- [ ] T025 运行 `python build.py test`
- [ ] T026 运行 `python build.py verify`
- [ ] T027 运行 `python build.py web-build`
