# 实现计划：设备台账维护与网元类型命名

**分支**：`028-ledger-crud` | **日期**：2026-10-07 | **规格**：[spec.md](spec.md)

**输入**：来自 `/specs/028-ledger-crud/spec.md` 的功能规格

## 摘要

将用户可见的“产品形态”统一为“网元类型”，同时保留 `product` 字段和字典键，避免契约与历史任务数据被破坏。解析器升级为记录级模型：`LST ME.txt` 可包含多台设备，先按记录解析设备名、网元类型和版本，再只归档网元类型与上传 `product` 相等的记录。设备台账新增设备档案维护能力：管理员可新增、查询、更新备注和物理删除设备；台账观测与版本历史在删除时同步清理，但任务原始包、任务详情与 `inventory.json` 不修改。

## 技术上下文

**语言/版本**：Python 3.11+，Node.js 20+ / TypeScript 5
**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、SQLite、React 18、Ant Design、Vite
**存储**：SQLite（`inventory_devices`、`inventory_observations`、`inventory_change_audits`）
**测试**：pytest、Vitest、Playwright
**目标平台**：桌面优先 Web，本地 / 在线 API 共用后端
**项目类型**：全栈功能
**性能目标**：台账 CRUD 为低频管理操作；多设备解析和列表查询保持现有分页性能
**约束条件**：离线巡检；不连接被检系统；不人工维护版本；不修改原始包
**规模/范围**：网元类型筛选与多设备台账归档、设备档案维护入口、后端 CRUD API、OpenAPI/前端客户端、权限和审计

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 原则 | 结论 | 说明 |
| --- | --- | --- |
| 一个包、一个任务、一个输出目录 | 通过 | 多设备解析仍属于同一个任务证据；CRUD 不改变任务隔离 |
| 台账资产不因任务重建丢失 | 调整后通过 | 用户明确选择物理删除；删除只由管理员显式触发 |
| 不人工维护版本 | 通过 | 新增和更新接口都不接受版本 |
| 任务观测与证据只读 | 调整后通过 | `inventory.json` 和任务详情不改；台账观测按用户确认随设备物理删除 |
| OpenAPI 优先 | 通过 | 先扩展 `docs/api/openapi.yaml`，再实现并重新生成前端客户端 |
| API 兼容性 | 通过 | 只新增可选响应字段和新端点；既有 `product` 字段含义不变 |
| 管理与审计 | 通过 | 写接口使用 admin 权限，创建/更新/删除写审计 |

## 项目结构

### 文档（本功能）

```text
specs/028-ledger-crud/
├── plan.md              # 本文件
├── research.md          # 关键技术决策
├── data-model.md        # 台账维护与任务证据模型
├── contracts/
│   ├── inventory-crud-api.md
│   └── inventory-type-filter.md
├── quickstart.md        # 展示效果与验证步骤
└── tasks.md             # 后续由 speckit-tasks 生成
```

### 源代码

```text
app/
├── api/router.py
├── models/db.py
├── models/schemas.py
└── services/inventory/
    ├── parser.py
    ├── ledger.py
    ├── queries.py
    └── maintenance.py

web/
├── src/api/http.ts
├── src/api/client.ts
├── src/pages/TaskListPage.tsx
├── src/pages/TaskDetailPage.tsx
├── src/pages/InventoryPage.tsx
└── src/pages/InventoryDevicePage.tsx

tests/
├── test_inventory_parser.py
├── test_inventory_ledger.py
├── test_inventory_api.py
├── test_inventory_crud.py
└── web/e2e/
```

**结构决策**：沿用现有分层。解析器只负责任务证据；台账归档器消费证据并写入多设备观测；维护逻辑放在 `app/services/inventory/`，API 只做契约、鉴权和错误转换；前端继续使用生成客户端调用。

## 技术方案

### 网元类型文案与筛选

- 上传表单字段标签改为“网元类型”，占位提示改为“选择网元类型”。
- 数据字典分类 `product` 的展示标题改为“网元类型”。
- 任务元数据展示中 `product` 的中文标签同步改为“网元类型”。
- 后端 `product` 字段、OpenAPI 字段名、数据库存储和字典键不变。
- 上传时选择的 `product` 是台账筛选条件；缺失时任务继续完成，但台账不归档，并显示 `network_element_type_filter_missing`。

### `LST ME.txt` 记录级解析

- `PARSER_VERSION` 升级为 `2`，用于区分旧的单设备证据。
- 按设备名行开启记录：`NE name`、`ME name`、`网元名称`、`设备名称`；后续行归属最近一次开启的记录，直到下一个设备名行。
- 每条记录解析：
  - 设备名：`NE name`、`ME name`、`网元名称`、`设备名称`。
  - 网元类型：`ME type`、`NE type`、`网元类型`。
  - 版本：`Software version`、`SW version`、`软件版本`。
- 设备名和网元类型规范化为 NFC、去首尾空白、合并连续空白，不做大小写转换。
- `product` 与记录网元类型规范化后执行全等匹配。
- 输出包含 `records`（全部可读记录）与 `devices`（按匹配设备去重），每项保留原始值、规范化值、来源文件和行号。
- 同一任务内规范化设备名相同且匹配的多条记录合并为一台设备；版本一致时归档一条，版本不同时版本冲突且不归档。
- 设备名行之前的游离键值字段不归档，写入结构化错误或摘要。
- 无匹配时返回 `not_archived` 和明确原因，不把任务置为失败。
- 单个记录字段缺失或解析异常不中断其他记录；结构化写入 `errors`。

### 任务证据兼容

- `TaskInventory` 保留既有 `device` / `version` 字段用于兼容旧客户端和旧详情展示：
  - 只有一个匹配设备时，字段值与该设备一致。
  - 多个匹配设备时，`device.status=matched_multiple`，`device.normalized_name=null`；版本不做单一聚合。
- 新增可选 `network_element_type_filter` 和 `records` / `devices` 数组，前端优先展示列表。
- `archived` 保留旧单设备字段；单设备时继续填充，多设备时旧字段为空并新增 `archived.devices[]` 表达每台设备的 `device_id` / `observation_id`。
- `devices` 只包含匹配上传网元类型的记录；`records` 包含全部可读记录和 `matched` 布尔值，用于解释未归档原因。
- OpenAPI 同步新增可选字段与列表子结构；不改变既有字段含义。

### 设备档案模型

在 `InventoryDevice` 上增加维护列：

- `remark: TEXT | NULL`：管理员维护备注。
- `created_by: VARCHAR(64) | NULL`：创建者；巡检解析生成时为 `system`。
- `updated_by: VARCHAR(64) | NULL`：最近维护者；巡检重算不改写该字段。
- `updated_at` 已存在，用于展示最近更新时间。

不新增设备状态列；删除即物理删除记录。手动新增设备仍复用 `InventoryDevice` 表。手动设备没有观测时，`latest_task_id` 使用内部哨兵值 `manual`，`latest_status` 使用 `manual`；这两个字段不暴露到公共契约。

### CRUD 行为

- **Create**：校验省份、运营商和设备名；规范化设备名后计算既有 `device_key` 和 `device_id`；重复返回 `device_already_exists`。
- **Read**：沿用现有列表和详情；`InventoryDevice` 契约新增可选 `remark`、`created_by`、`updated_by`、`updated_at`。
- **Update**：第一版只允许更新 `remark`；返回最新设备档案。
- **Delete**：在单事务中删除设备、观测和该设备相关历史审计，再写入一条删除审计；任务目录、原始包和 `inventory.json` 不修改。
- **重建/归档**：匹配网元类型的任务再次解析出同一设备身份时，如果设备不存在则重新创建；观测与版本历史重新累积。

### API 设计

新增到 `/api/v2/inventory/devices`：

- `POST /api/v2/inventory/devices`：创建设备档案，`201 + Location`。
- `PATCH /api/v2/inventory/devices/{device_id}`：更新备注，返回设备档案。
- `DELETE /api/v2/inventory/devices/{device_id}`：物理删除，返回 `204`。

三个接口均要求 `admin`。资源路径继续使用 `device_id`，不在路径中携带省份或运营商。删除确认由前端弹窗负责；后端不做 `confirm` 请求参数。

### 审计设计

- 创建：`action=create`，`before_snapshot=null`，`after_snapshot` 保存设备档案。
- 更新：`action=update`，`before_snapshot` 保存旧备注，`after_snapshot` 保存新备注。
- 删除：先保存被删除设备与观测摘要到 `before_snapshot`，执行删除后写 `action=delete`。
- 维护审计的 `task_id` 改为可空，不伪造任务。

### 前端设计

- 上传弹窗和任务详情统一显示“网元类型”。
- 任务详情优先展示匹配设备列表；多设备时显示设备、网元类型、版本和来源行，不再只展示单一设备名。
- 设备台账列表顶部提供“新增设备”按钮。
- 表格新增维护列，展示备注摘要和维护时间。
- 行操作提供“编辑”和“删除”；点击表格其他区域仍进入设备详情。
- 新增/编辑使用弹窗表单；删除使用危险确认弹窗，明确提示会删除台账观测和版本历史。
- API 调用全部使用 OpenAPI 生成客户端；手写 HTTP 封装只保留类型引用和方法入口。

## 复杂度跟踪

> 无宪法豁免项。修改台账删除语义来自用户明确确认；实现仍保持任务原始现场不可变。
