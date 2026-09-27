# 实现计划：局点设备台账

**分支**：`feature/027-site-device-ledger` | **日期**：2026-09-27 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/027-site-device-ledger/spec.md` 的功能规格

## 摘要

为巡检包建立独立于任务产物的设备台账。局点继续由上传时的 `province + operator` 表达，设备身份由包内 `LST ME.txt` 解析出的规范化设备名表达。每个完成任务最多保留一条当前生效设备观测；任务重跑按任务覆盖，并保留台账变更审计。系统按观测时间维护版本历史，当前版本取最近一次成功解析版本的观测值，版本方向只按原始版本字符串字典序判断。

新增“日志补充包”任务类型。该类型不要求局点或设备元数据，不解析 `LST ME.txt`，不进入设备台账和版本历史；任务详情明确显示台账不适用。普通巡检包缺少 `LST ME.txt` 仍然按巡检包执行，只显示设备观测未归档及原因。

## 技术上下文

**语言/版本**：Python 3.11+；Node.js / TypeScript（现有 web 工具链）

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、React、TypeScript、Vite、Ant Design

**存储**：文件系统任务目录；SQLite 中新增设备、观测、任务解析结果和变更审计表；`inventory.json` 只作为任务级可重建证据

**测试**：pytest、FastAPI TestClient、Vitest、Playwright、npm build、本地全流程验证

**目标平台**：本地桌面浏览器 + 单节点 FastAPI / CLI 共享服务层

**性能目标**：局点设备列表和设备详情分页加载；单任务台账归档在任务完成后同步执行，解析异常只降级不阻断任务

**约束条件**：离线优先；一个包、一个任务、一个输出目录；UTC 存储；契约先行；台账资产不可因任务重建丢失；日志补充包显式分流

**规模/范围**：单节点设备台账、局点设备视图、设备详情、任务台账面板、台账质量问题视图和上传类型选择

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

### 阶段 0 前检查

- **离线优先**：通过：只读取本地上传包和解压现场，不连接被检系统。
- **一个包、一个任务**：通过：台账观测通过 `task_id` 引用任务；不改变包名派生任务 ID 和任务目录隔离。
- **契约驱动**：通过：先新增 `POST /api/v3/tasks` 和台账只读查询契约，再生成客户端和实现。
- **模式同构**：通过：解析、归档、查询服务放在共享 service；CLI 与 API 都调用同一入口。
- **巡检器插件架构**：通过：台账解析不作为普通 Inspector 展示，不进入规则结果；也不建立规则间依赖。
- **轻量默认**：通过：继续使用 SQLite + 文件存储，不引入外部数据库或后台服务。
- **容错与编码兼容**：通过：单文件解析失败只降级台账状态；读取接入 UTF-8 / GB18030 兼容入口。
- **安全解压与原始包不可变**：通过：台账只读取安全解压后的文件，不修改或重复解压原始包。
- **新功能验证与展示效果**：通过：计划包含 API、持久化、CLI/API 一致性和前端 E2E 展示路径。

### 阶段 1 后复查

- **通过**：数据模型将设备台账放在 SQLite 独立表，任务产物重建不会清空台账；观测覆盖写入审计。
- **通过**：`POST /api/v3/tasks` 显式携带 `package_kind`，避免用“缺少设备信息”或“缺少 `LST ME.txt`”猜测日志补充包。
- **通过**：日志补充包不参与设备身份、版本、观测和局点统计；任务详情返回 `not_applicable` 证据。
- **通过**：设备列表以设备当前局点过滤，历史局点只在设备详情观测历史中出现。
- **通过**：版本历史不做语义解释，只在相邻有效版本间使用原始字符串字典序展示方向。
- **通过**：所有新增持久化时间字段使用 UTC 和 `*_at` 命名。
- **通过**：列表接口默认分页大小为 10，与既有约定一致。

## 项目结构

### 文档（本功能）

```text
specs/027-site-device-ledger/
├── plan.md              # 本文件
├── research.md          # 阶段 0 结论
├── data-model.md        # 阶段 1 持久化与状态模型
├── quickstart.md        # 阶段 1 验证指南
├── contracts/
│   ├── inventory-api.md # API 契约边界
│   └── inventory-evidence.md # inventory.json 与任务详情增量契约
└── tasks.md             # 后续 $speckit-tasks 生成
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py                     # 新增 v3 创建任务与 v2 台账只读路由
├── models/db.py                      # TaskRecord 增量字段与四张台账表
├── models/schemas.py                 # PackageKind、台账查询/响应、任务详情增量字段
├── services/tasks.py                 # 任务完成后调用共享台账归档入口
├── services/inventory/
│   ├── __init__.py
│   ├── parser.py                     # LST ME.txt 解析与字段冲突判定
│   ├── ledger.py                     # 观测归档、设备状态重算、审计
│   └── queries.py                    # 设备、观测、版本历史、质量问题查询
└── cli.py                            # run 命令补充任务类型与局点元数据

deploy/config/classify_rules.yaml      # 精确匹配 LST ME.txt 并归入 config
docs/api/openapi.yaml                  # 契约唯一事实源

web/src/
├── pages/TaskListPage.tsx            # 上传包类型与条件表单
├── pages/TaskDetailPage.tsx          # 挂载任务台账面板
├── pages/InventoryPage.tsx           # 局点设备列表与质量问题入口
├── pages/InventoryDevicePage.tsx     # 设备详情、观测历史、版本历史
└── components/task-detail/
    └── TaskInventoryPanel.tsx        # 任务级台账解析状态与证据

tests/
├── test_inventory_parser.py
├── test_inventory_ledger.py
├── test_inventory_api.py
├── test_inventory_task_flow.py
└── fixtures/inventory/

web/e2e/
└── inventory.spec.ts
```

**结构决策**：沿用现有 `api → services → models` 分层。台账是任务域之外的持久资产域，因此使用独立 `services/inventory/` 包；不放入 `inspectors/`，避免被误当成普通巡检规则，也不把台账解析结果伪装成 `RuleResult`。

## 阶段 0 研究结论

见 [research.md](research.md)。

## 阶段 1 设计

- 持久化与状态模型见 [data-model.md](data-model.md)。
- API 契约见 [contracts/inventory-api.md](contracts/inventory-api.md)。
- 任务证据与详情增量契约见 [contracts/inventory-evidence.md](contracts/inventory-evidence.md)。
- 展示与验证见 [quickstart.md](quickstart.md)。

## 技术方案

### 任务类型与上传契约

新增 `PackageKind`：

- `inspection`：巡检包。
- `log_supplement`：日志补充包。

新增 `POST /api/v3/tasks`，请求体包含 `package_file`、`name`、`package_kind`、`province`、`operator`、`product`；不提供人工 `version` 和 `device_id`。服务端条件校验：

- `inspection`：`province` 和 `operator` 必填；`product` 可选；不允许人工版本。
- `log_supplement`：不要求局点或设备元数据；若传入非空省份、运营商或产品形态，返回明确校验错误，避免把这些字段静默关联到日志补充任务。
- `/api/v2/tasks` 保持不变，既有客户端继续可用。
- 前端上传切换到 v3，并按包类型显示条件字段。

`TaskRecord` 增加可选增量列 `package_kind`，旧库通过 `ALTER TABLE` 增加并默认 `inspection`。任务详情契约增加可选 `package_kind` 和 `inventory`，不改变既有字段含义。

### 解析与归档

共享服务 `app/services/inventory/` 负责三步：

1. **解析**：从安全解压现场按 `config/**/LST ME.txt` 精确匹配来源；统一使用 UTF-8 / GB18030 解码；提取设备名和版本别名；规范化设备名；汇总重复值、冲突值和来源文件。
2. **写证据**：生成或更新 `output/<task_id>/inventory.json`，记录任务类型、解析状态、局点来源、设备/版本状态、来源文件、冲突和错误。
3. **归档**：仅在任务正常完成后写 SQLite。设备观测归档要求局点和有效设备身份；版本缺失或冲突不阻断观测，但当前版本不更新。日志补充包只写 `not_applicable` 解析结果，不写观测。

解析失败、来源缺失、字段缺失或冲突都会产生明确状态和原因，不中断其他规则和任务完成态。

### 任务生命周期接入

- 全量执行：任务正常完成后同步调用台账归档。
- 全量重建：重建完成后再调用台账归档；同一任务最多一条当前生效观测。
- 任务重跑：按任务覆盖当前生效观测；结果变化时写审计。
- 增量重建或单规则重跑：不触发台账归档，避免无关规则执行改变台账。
- 任务产物清理后重建：台账表不清空；重建后按同一任务安全覆盖或保持原观测。
- 任务删除后的台账保留策略继续按规格范围外处理，本功能不新增级联删除台账逻辑。

### 设备状态与版本历史

设备当前状态由该设备全部当前生效观测重算：

- 当前局点跟随最近一次有效观测。
- 当前版本是最近一次 `version_status=ok` 的观测值，不是所有版本中的最大值。
- `first_seen_at` 取最早观测，`last_seen_at` 取最近观测。
- 观测数量、局点变化数量和局点冲突标记随覆盖重算。

版本历史按观测时间展示；只有相邻两个 `version_status=ok` 的观测之间计算方向：

- `raw_version < previous_raw_version`：`downgrade`
- `raw_version > previous_raw_version`：`upgrade`
- 相等：`unchanged`

缺失和冲突版本保留在时间线上并标为观测缺口，不参与方向计算。方向比较使用 Python 原始字符串 Unicode 码点顺序，不做大小写折叠、版本号拆解或语义比较。

### 查询与前端

台账查询服务提供设备列表、设备详情、观测历史、版本历史和质量问题分页查询。所有数据列表默认 `page_size=10`，最大 100。

前端新增：

- **上传表单**：选择“巡检包 / 日志补充包”；巡检包必选省份和运营商且移除人工版本；日志补充包隐藏并禁用局点与设备字段。
- **任务详情台账面板**：巡检包显示局点来源、局点、设备状态、版本状态、来源文件和冲突；日志补充包显示“不涉及设备台账”。
- **局点设备页**：先选省份和运营商，再展示当前局点设备列表、观测次数、当前版本和质量提示。
- **设备详情页**：展示当前状态、观测历史、版本历史和局点归属变化。
- **质量问题视图**：按问题类型、局点、设备或任务过滤，并支持跳转详情。

OpenDesign 可继续用于视觉稿和组件布局验证，但 Speckit 规格、计划和任务清单仍是实现权威；OpenAPI 生成客户端必须被使用，禁止手写不一致调用。

## 复杂度跟踪

> 无宪法豁免项。新增独立服务包是为了保护台账资产边界，不构成架构违规。
