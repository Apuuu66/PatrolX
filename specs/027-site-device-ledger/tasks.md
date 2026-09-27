---
description: "局点设备台账实现任务列表"
---

# 任务：局点设备台账

**输入**：来自 `/specs/027-site-device-ledger/` 的设计文档

**前置条件**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`

**测试**：本功能要求自动化测试、展示效果用例和 E2E；任务按 TDD 顺序组织。

## 格式：`[ID] [P?] [故事] 描述`

- **[P]**：可并行执行（不同文件，无依赖）
- **[故事]**：该任务所属的用户故事
- 描述中包含精确文件路径

## 阶段 1：设置（共享基础设施）

- [ ] T001 建立台账 fixture 目录和包构造工具骨架：`tests/fixtures/inventory/`
- [ ] T002 在 `deploy/config/classify_rules.yaml` 增加 `^LST ME\.txt$` 精确分类规则，并补充分类单测

## 阶段 2：基础层（阻塞前置条件）

**⚠️ 关键**：本阶段完成前不得开始用户故事实现。

- [ ] T003 在 `app/models/db.py` 增加 `TaskRecord.package_kind` 增量迁移和默认 `inspection`
- [ ] T004 在 `app/models/db.py` 按数据模型创建 `inventory_devices`、`inventory_observations`、`inventory_parse_results`、`inventory_change_audits`
- [ ] T005 在 `app/models/schemas.py` 定义 `PackageKind`、台账解析状态、字段状态、版本方向、质量问题和响应模型
- [ ] T006 创建 `app/services/inventory/` 包及确定性 ID、规范化、UTC 时间和 JSON 原子写入公共工具
- [ ] T007 在 `docs/api/openapi.yaml` 前置新增 `POST /api/v3/tasks`、`/api/v2/inventory/*` 和任务详情增量 Schema
- [ ] T008 运行 `python build.py contract` 校验 OpenAPI，并运行 `python build.py gen-web-api` 更新前端客户端

**检查点**：契约、模型和基础工具就绪；台账资产写入逻辑可开始。

## 阶段 3：用户故事 1 - 上传任务并归档设备观测（P1）🎯 MVP

**目标**：巡检包完成后解析 `LST ME.txt`，归档一条当前生效设备观测；日志补充包显式跳过台账。

**独立测试**：上传含 `LST ME.txt` 的巡检包并选择省份/运营商，任务详情显示局点、设备、版本和来源文件；日志补充包显示不涉及台账。

### US1 测试

- [ ] T009 [P] [US1] 在 `tests/test_inventory_parser.py` 覆盖成功解析、别名、空白规范化、UTF-8/GB18030、缺版本、版本冲突、设备冲突、缺文件和解码失败
- [ ] T010 [P] [US1] 在 `tests/test_inventory_ledger.py` 覆盖任务观测唯一性、覆盖更新、审计、缺局点/缺设备不归档和设备状态重算
- [ ] T011 [P] [US1] 在 `tests/test_inventory_task_flow.py` 覆盖全量执行、日志补充包、缺 `LST ME.txt` 与任务不失败
- [ ] T012 [US1] 在 `tests/test_inventory_api.py` 覆盖 v3 巡检包/日志补充包校验和 v2 兼容

### US1 实现

- [ ] T013 [US1] 实现 `app/services/inventory/parser.py`：固定来源匹配、统一解码、字段别名、原始值/行号和冲突收集
- [ ] T014 [US1] 实现 `app/services/inventory/ledger.py`：写入 `inventory.json`、事务归档观测、状态重算和变更审计
- [ ] T015 [US1] 在 `app/services/tasks.py` 的全量执行和全量重建完成后接入台账归档；解析异常不使任务失败
- [ ] T016 [US1] 实现 v3 创建服务校验：巡检包必填省份/运营商，日志补充包不要求且拒绝非空局点元数据
- [ ] T017 [US1] 在 `app/api/router.py` 实现 `createTaskV3`，响应 `202 + Location`
- [ ] T018 [US1] 在 `app/models/schemas.py` 和任务详情服务中增量返回 `package_kind`、`inventory`
- [ ] T019 [US1] 在 `app/cli.py` 为 `run` 增加 `--package-kind`、`--province`、`--operator`、`--product`，并复用共享归档入口
- [ ] T020 [US1] 补充 CLI/API 同一样例一致性测试，确保本地和在线 `inventory.json` 语义一致

**检查点**：P1 后端路径完整；任务详情可展示台账证据；日志补充包不生成观测。

## 阶段 4：用户故事 2 - 按局点查看设备台账（P1）

**目标**：按省份和运营商列出当前局点设备，并可进入设备详情。

**独立测试**：构造多局点设备观测，局点视图只显示当前局点设备，历史局点只在设备详情观测历史出现。

### US2 测试

- [ ] T021 [P] [US2] 在 `tests/test_inventory_api.py` 增加设备列表分页、当前局点过滤、设备详情和历史观测测试
- [ ] T022 [P] [US2] 在 `web/e2e/inventory.spec.ts` 增加上传巡检包 → 任务详情 → 局点列表 → 设备详情 E2E

### US2 实现

- [ ] T023 [US2] 实现 `app/services/inventory/queries.py`：设备分页查询、当前局点过滤、设备详情、观测历史和质量标记
- [ ] T024 [US2] 在 `app/api/router.py` 实现 `GET /api/v2/inventory/devices`、`GET /api/v2/inventory/devices/{device_id}`、`GET .../observations`
- [ ] T025 [US2] 创建 `web/src/pages/InventoryPage.tsx`：省份/运营商选择、设备表、观测次数、当前版本、质量提示和分页
- [ ] T026 [US2] 创建 `web/src/pages/InventoryDevicePage.tsx`：设备状态、当前版本、观测历史和局点归属提示
- [ ] T027 [US2] 在 `web/src/App.tsx` 注册 `/inventory` 和 `/inventory/devices/:deviceId`

**检查点**：用户可在 3 次点击内从局点设备列表进入设备详情。

## 阶段 5：用户故事 3 - 设备版本历史（P1）

**目标**：按时间展示版本历史、来源任务、缺口和相邻有效版本方向。

**独立测试**：构造 `V1 → V2 → V1`、缺版本和版本冲突观测，验证升级/降级/未变化和缺口提示。

### US3 测试

- [ ] T028 [P] [US3] 在 `tests/test_inventory_api.py` 增加版本历史分页、方向、缺口、冲突和当前版本来源断言
- [ ] T029 [P] [US3] 在 `web/src/pages/InventoryDevicePage.test.tsx` 覆盖版本方向、缺口和当前版本来源展示

### US3 实现

- [ ] T030 [US3] 扩展 `app/services/inventory/queries.py`：版本历史投影、字典序方向、缺口标记和分页
- [ ] T031 [US3] 在 `app/api/router.py` 实现 `GET /api/v2/inventory/devices/{device_id}/version-history`
- [ ] T032 [US3] 扩展 `web/src/pages/InventoryDevicePage.tsx`：版本时间线、方向标签、观测缺口和来源任务

**检查点**：设备详情可解释当前版本来源和历史版本路径。

## 阶段 6：用户故事 4 - 识别台账数据质量（P2）

**目标**：集中展示缺失、冲突和局点归属变化，并支持追溯到任务或设备。

**独立测试**：构造五类质量问题样例，质量问题视图能定位任务/设备，日志补充包不产生质量问题。

### US4 测试

- [ ] T033 [P] [US4] 在 `tests/test_inventory_api.py` 覆盖五类质量问题、过滤、分页、任务/设备追溯和日志补充包排除
- [ ] T034 [P] [US4] 在 `web/src/pages/InventoryPage.test.tsx` 覆盖质量过滤和跳转入口

### US4 实现

- [ ] T035 [US4] 扩展 `app/services/inventory/queries.py`：解析结果和观测投影生成质量问题及确定性 `issue_id`
- [ ] T036 [US4] 在 `app/api/router.py` 实现 `GET /api/v2/inventory/quality-issues`
- [ ] T037 [US4] 扩展 `web/src/pages/InventoryPage.tsx`：质量问题 Tab、类型/局点过滤和跳转链接

**检查点**：质量问题可见、可过滤、可追溯。

## 阶段 7：收尾与横切关注点

**目的**：完成展示闭环、文档一致性和全量验证。

- [ ] T038 在 `web/src/pages/TaskListPage.tsx` 增加包类型选择和条件字段；巡检包移除人工版本/设备 ID，日志补充包隐藏局点字段
- [ ] T039 在 `web/src/pages/TaskDetailPage.tsx` 和 `web/src/components/task-detail/TaskInventoryPanel.tsx` 展示台账证据、未归档原因和日志补充包不适用
- [ ] T040 补充 `web/e2e/inventory.spec.ts` 日志补充包完整入口：上传、任务详情、无设备观测
- [ ] T041 更新 `docs/architecture.md` 和 `docs/data-model.md` 的台账分层、存储、任务生命周期和失败语义
- [ ] T042 运行 `python build.py lint`、`python build.py test`、`python build.py contract`、`python build.py gen-web-api`
- [ ] T043 运行 `python build.py verify`、`python build.py web-build`、`python build.py e2e`
- [ ] T044 按 `quickstart.md` 手动核对成功、缺版本、冲突、缺设备、缺局点、缺文件和日志补充包展示

## 依赖与执行顺序

### 阶段依赖

- **设置（阶段 1）**：立即开始。
- **基础层（阶段 2）**：依赖 T001/T002；阻塞所有故事。
- **US1（阶段 3）**：依赖基础层。
- **US2/US3/US4**：依赖基础层；查询和界面依赖 US1 数据可用。
- **收尾（阶段 7）**：依赖所有用户故事。

### 用户故事依赖

- **US1**：基础层完成后开始。
- **US2**：US1 观测归档完成后最有意义；契约和测试可先行。
- **US3**：依赖 US1 观测；与 US2 可共享设备详情页。
- **US4**：依赖 US1 解析结果；与 US2/US3 查询层可并行设计。

### 并行机会

- T009/T010/T011 可并行编写。
- T021/T022 可并行。
- T028/T029、T033/T034 可并行。
- 后端查询任务 T023、T030、T035 属同一文件，应串行。
- 前端页面 T025/T026/T032/T037 存在页面重叠时串行。

## 实现策略

1. 完成阶段 1/2。
2. 完成 US1 并验证 MVP。
3. 按 US2 → US3 → US4 增量交付。
4. 最后执行前端上传、任务详情、文档和全量门禁。
