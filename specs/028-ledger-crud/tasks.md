---
description: "设备台账维护与网元类型命名实现任务列表"
---

# 任务：设备台账维护与网元类型命名

**输入**：来自 `/specs/028-ledger-crud/` 的设计文档

**前置条件**：plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

## 阶段 1：设置（共享基础设施）

- [x] T001 [P] 扩展 `tests/fixtures/inventory/builder.py`，支持包含 3 条设备记录、不同 `ME type` 和版本的 `LST ME.txt` 样例
- [x] T002 在 `app/models/db.py` 为 `InventoryDevice` 增加 `remark`、`created_by`、`updated_by`，并在现有 `init_db()` 路径补齐 SQLite 增量迁移，同时将 `InventoryChangeAudit.task_id` 调整为可空
- [x] T003 在 `docs/api/openapi.yaml` 增加 `/api/v2/inventory/devices` 的 `POST`、`PATCH`、`DELETE`，扩展 `InventoryDevice` 响应，并增加 `TaskInventory` 的 `network_element_type_filter`、`records`、`devices`、`archived.devices` 可选契约
- [x] T004 执行 `.venv/bin/python build.py contract` 和 `.venv/bin/python build.py gen-web-api`，确保 `web/src/api` 客户端与 OpenAPI 一致

## 阶段 2：基础层（阻塞前置条件）

- [x] T005 在 `app/models/schemas.py` 增加台账维护请求模型与任务证据 v2 契约模型；`InventoryDeviceCreateRequest` 必填 `province`、`operator`、`device_name`，`InventoryDeviceUpdateRequest` 仅支持 `remark`
- [x] T006 在 `app/services/inventory/maintenance.py` 建立设备维护服务入口，封装权限上下文、设备身份规范化、维护审计和错误码映射
- [x] T007 [P] 为 `InventoryDevice` 新增列和 `InventoryChangeAudit.task_id` 可空行为补齐数据库迁移/持久化测试

**检查点**：契约、客户端、数据模型和统一维护服务基础就绪。

## 阶段 3：用户故事 1 - 统一网元类型文案并筛选多设备（优先级：P1）🎯 MVP

**目标**：上传界面和任务详情统一显示“网元类型”；解析器按记录解析多设备，只归档网元类型与上传 `product` 相等的记录。

**独立测试**：上传 3 条设备记录、其中 2 条 `ME type` 等于所选网元类型的巡检包；任务详情显示 2 台匹配设备，台账只出现 2 台设备，不匹配设备仅保留摘要。

### 用户故事 1 的测试

- [x] T008 [P] [US1] 扩展 `tests/test_inventory_parser.py`，覆盖多设备、网元类型匹配、缺失网元类型、缺失筛选值、同名记录合并/版本冲突、游离字段、单条异常不阻断和 `PARSER_VERSION=2`
- [x] T009 [P] [US1] 扩展 `tests/test_inventory_ledger.py`，覆盖同一任务归档多台匹配设备、不匹配记录不建档、重新命中已删除设备重建
- [x] T010 [P] [US1] 扩展 `tests/test_inventory_api.py`，覆盖任务详情返回网元类型筛选摘要、匹配设备列表和归档设备列表

### 用户故事 1 的实现

- [x] T011 [US1] 重构 `app/services/inventory/parser.py` 为记录级解析；`NE name` / `ME name` 开启记录，解析 `ME type` / `NE type` / `网元类型` 和版本，规范化后与 `product` 全等匹配
- [x] T012 [US1] 调整 `app/services/inventory/ledger.py` 和调用链，让 `parse_inventory()` 接收 `product`，并为同一任务的多台匹配设备分别写入 `inventory_devices` 和 `inventory_observations`
- [x] T013 [US1] 更新 `app/services/inventory/queries.py`、`app/api/router.py` 和任务详情响应，让旧任务继续使用旧字段，新任务优先返回 `devices` / `records` / `archived.devices`
- [x] T014 [P] [US1] 更新 `web/src/pages/TaskListPage.tsx` 和相关字典/上传组件，将“产品形态”文案改为“网元类型”，占位提示改为“选择网元类型”
- [x] T015 [US1] 更新任务详情页面，展示匹配设备列表、设备网元类型、版本、来源行和未匹配/缺失原因；多设备时不得聚合为单一设备
- [x] T016 [US1] 在 `tests/web/e2e/` 或现有 E2E 目录增加完整用例：打开上传 -> 选择网元类型 -> 多设备任务完成 -> 台账只显示匹配设备

**检查点**：用户故事 1 可通过 API、任务详情和台账独立验证。

## 阶段 4：用户故事 2 - 手动新增设备档案（优先级：P1）

**目标**：管理员可新增省份、运营商和设备名组成的设备档案，不人工填版本。

**独立测试**：管理员提交新设备后列表和详情可见；同省份同名重复提交返回 409；非管理员返回 403。

### 用户故事 2 的测试

- [x] T017 [P] [US2] 在 `tests/test_inventory_crud.py` 覆盖创建成功、重复身份、必填校验、非 admin 权限和后续匹配任务合并到同一设备
- [x] T018 [P] [US2] 在 E2E 中覆盖打开台账 -> 新增设备 -> 刷新可见

### 用户故事 2 的实现

- [x] T019 [US2] 在 `app/services/inventory/maintenance.py` 实现创建逻辑：规范化设备名、派生既有 `device_key` / `device_id`、手动设备使用内部 `latest_task_id=manual`、`latest_status=manual`，并写创建审计
- [x] T020 [US2] 在 `app/api/router.py` 实现 `POST /api/v2/inventory/devices`，返回 `201 + Location`，错误码为 `device_already_exists` / `invalid_request`
- [x] T021 [US2] 更新 `web/src/pages/InventoryPage.tsx` 或 `web/src/pages/InventoryDevicePage.tsx`，提供新增弹窗，字段为省份、运营商、设备名和可选备注

## 阶段 5：用户故事 3 - 更新设备维护信息（优先级：P1）

**目标**：管理员可更新设备备注，不能修改省份、运营商或设备名身份。

**独立测试**：管理员更新备注后刷新可见；观测与版本历史不变；非 `remark` 字段不接受。

### 用户故事 3 的测试

- [x] T022 [P] [US3] 在 `tests/test_inventory_crud.py` 覆盖备注更新、不存在设备、非法字段、权限校验和观测不变
- [x] T023 [P] [US3] 在 E2E 中覆盖打开设备 -> 编辑备注 -> 刷新可见

### 用户故事 3 的实现

- [x] T024 [US3] 在 `app/services/inventory/maintenance.py` 实现备注更新、`updated_by` / `updated_at` 维护和更新审计
- [x] T025 [US3] 在 `app/api/router.py` 实现 `PATCH /api/v2/inventory/devices/{device_id}`，返回最新 `InventoryDevice`
- [x] T026 [US3] 更新设备台账表格和详情页面，提供编辑入口并只提交可维护字段

## 阶段 6：用户故事 4 - 物理删除设备台账（优先级：P1）

**目标**：管理员可物理删除设备档案，同时删除该设备全部台账观测和历史审计，并保留删除审计。

**独立测试**：删除后设备、观测和版本历史查询不可见；任务原始包和 `inventory.json` checksum 不变；重新巡检可重建。

### 用户故事 4 的测试

- [x] T027 [P] [US4] 在 `tests/test_inventory_crud.py` 覆盖物理删除范围、删除审计、不存在设备、权限校验、任务现场不变和重新建账
- [x] T028 [P] [US4] 在 E2E 中覆盖打开设备 -> 危险确认删除 -> 列表消失 -> 重新巡检可见

### 用户故事 4 的实现

- [x] T029 [US4] 在 `app/services/inventory/maintenance.py` 实现单事务物理删除：构造删除前摘要，删除设备、观测和历史审计，再写删除审计
- [x] T030 [US4] 在 `app/api/router.py` 实现 `DELETE /api/v2/inventory/devices/{device_id}`，返回 `204`
- [x] T031 [US4] 更新设备台账界面，提供危险确认弹窗并明确提示会删除台账观测和版本历史

## 阶段 7：收尾与横切关注点

- [x] T032 [P] 更新 `docs/architecture.md`、`docs/data-model.md` 或相关权威文档，说明网元类型筛选、多设备归档和台账 CRUD 语义
- [x] T033 [P] 检查 `app/cli.py` 与在线 API 的上传参数和归档入口一致，确保 CLI 传递 `product` 且结果与 API 一致
- [x] T034 运行 `.venv/bin/python build.py lint`、`.venv/bin/python build.py test`、`.venv/bin/python build.py contract`、`.venv/bin/python build.py gen-web-api`
- [x] T035 运行 `.venv/bin/python build.py web-build`、`.venv/bin/python build.py e2e` 和 `.venv/bin/python build.py verify`

## 依赖与执行顺序

### 阶段依赖

- 阶段 1 是阻塞前提；T003 完成后才可执行 T004。
- 阶段 2 依赖阶段 1 的契约与数据模型设计。
- 用户故事阶段按 US1 -> US2 -> US3 -> US4 顺序执行；US2/US3/US4 的服务与 API 依赖阶段 2。
- 收尾依赖所有用户故事完成。

### 用户故事依赖

- **US1**：依赖记录级解析、台账多观测和任务证据契约。
- **US2**：依赖设备维护模型和服务基础；不依赖 US1 的解析重构完成即可开发，但完整 E2E 依赖 US1。
- **US3**：依赖 US2 创建的设备档案。
- **US4**：依赖设备、观测与审计模型；完整重建断言依赖 US1 的匹配归档。

### 并行机会

- 阶段 1 的 fixture、OpenAPI 和数据库迁移可在契约确认后并行。
- 各用户故事内的后端测试可先并行编写。
- 前端文案、任务详情和 E2E 可在后端契约稳定后并行。

## 实现策略

### MVP 优先

完成阶段 1、2 和用户故事 1 后先验证多设备网元类型筛选闭环；再交付台账维护。

### 增量交付

1. 契约与基础层就绪。
2. US1 多设备筛选归档。
3. US2 -> US3 -> US4 台账维护闭环。
4. 收尾验证并更新权威文档。
