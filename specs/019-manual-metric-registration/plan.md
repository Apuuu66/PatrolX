# 实现计划：人工注册指标

**分支**：`feature/019-manual-metric-registration` | **日期**：2026-09-22 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/019-manual-metric-registration/spec.md` 的功能规格

## 摘要

在 KPI 测量单元绑定现场补录未注册的 ME 指标。系统用 `ME__MANUAL_` 前缀加唯一后缀生成可识别资源 ID，允许维护人员在界面继续编辑人工指标的中文名、英文名和启用状态；资源 ID 与绑定来源保持不可变，绑定确认仍由人工完成。

## 技术上下文

**语言/版本**：Python 3.11+

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、React + TypeScript + Ant Design

**存储**：SQLite，复用既有 `kpi_measurement_resources` 与 `kpi_measurement_bindings` 表

**测试**：pytest + 前端构建；契约一致性使用 `python build.py contract`

**目标平台**：本地/在线共用的单节点离线巡检系统

**项目类型**：FastAPI 后端 + React 前端

**性能目标**：常规管理操作单次请求完成；绑定列表维持当前分页行为

**约束条件**：离线优先、契约驱动、不自动确认绑定、不修改任务原始包

**规模/范围**：仅 ME 资源注册与人工指标维护，不扩展测量单元、单位、CSV 导入合并规则和派生指标模型

## 宪法检查

- **离线优先**：符合；只维护巡检结果中发现的资源目录，不连接被检系统。
- **契约驱动**：新增/修改 API 前同步 `docs/api/openapi.yaml`，再实现 Pydantic/FastAPI，并重新生成前端客户端。
- **模式同构**：资源目录与绑定是共享服务，本地/API 模式读取同一数据模型。
- **插件架构**：不修改规则调度器，不在核心调度器硬编码业务逻辑；KPI 巡检器继续按确认绑定读取数据。
- **幂等与可追溯**：绑定保留任务、来源文件、原始列名和基础列名；编辑资源不重写绑定来源。
- **轻量默认**：继续使用 SQLite，不新增外部依赖。
- **数据分页默认**：新列表沿用默认 `page_size=10`；本功能主要复用现有列表。
- **容错**：注册和编辑失败返回统一错误码，不影响任务执行和其他绑定。

## 项目结构

### 文档（本功能）

```text
specs/019-manual-metric-registration/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── api/router.py
├── models/db.py
├── models/schemas.py
└── services/kpi_measurement_units.py
docs/api/openapi.yaml
tests/
├── test_kpi_measurement_api.py
├── test_kpi_measurement_binding.py
└── test_kpi_measurement_resources.py
web/src/
├── api/http.ts
└── pages/MeasurementUnitsPage.tsx
```

**结构决策**：复用既有测量单元领域服务、v5 API 路由、Pydantic Schema 和测量单元页面，不新建独立模块。资源 ID 前缀是人工注册来源标记，不新增来源枚举字段。

## 实现要点

1. 服务层新增绑定现场注册能力：
   - 未注册绑定必须有 `metric_resource_id IS NULL`。
   - 中文名为空拒绝；英文名可空。
   - 同类 ME 中文名已存在时返回冲突，前端允许改为绑定已有指标或修改中文名。
   - 若显式选择已有 ME 资源，则只更新当前绑定的 `metric_resource_id`，不创建资源。
   - 创建成功后仅更新当前绑定关联，保持 `candidate`。
2. 人工 ID 生成：
   - 前缀固定 `ME__MANUAL_`。
   - 可读部分优先来自英文名；无英文名时使用稳定占位词；最后追加随机唯一后缀。
   - 只保留 ASCII 字母、数字、下划线；总长不超过数据库 `String(128)`。
   - 生成后查询主键唯一性，冲突时重新生成后缀。
3. 资源编辑：
   - 仅 `resource_id.upper().startswith("ME__MANUAL_")` 可通过新编辑路径修改。
   - 可编辑 `name_zh`、`name_en`、`enabled`；字段级部分更新。
   - 不允许修改 `resource_id`、`kind`、`filename_fragment`；资源目录本不保存绑定来源。
   - 中文名冲突返回明确错误；编辑不触碰绑定状态、原始列名和任务来源。
4. API：
   - `POST /api/v5/kpi/measurement-bindings/{binding_id}/register-metric`
   - `PATCH /api/v5/kpi/measurement-resources/{resource_id}`
   - 两者使用 admin 权限，返回资源/绑定形态的 JSON，并同步 OpenAPI。
5. 前端：
   - 候选且未关联指标的绑定提供“注册指标”入口。
   - 表单预填基础列名与展示单位，支持改绑已有指标。
   - ID 以 `ME__MANUAL_` 开头的指标显示“人工注册”标签并提供编辑入口。
   - 编辑弹窗只暴露中文名、英文名、启用状态。

## 复杂度跟踪

无宪法违规。
