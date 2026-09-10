# AGENTS.md — PatrolX 巡检系统

## 项目简介

PatrolX 是一个面向系统维护场景的**离线巡检系统**。系统不连接被检系统、不做在线数据采集，用户将预先收集好的数据打包（zip/tar.gz）上传后，系统对包内数据进行解析与巡检分析，输出巡检结果与报告。

典型输入为一个数据收集包，其中包含：

- **日志文件**：系统日志、错误日志、堆栈等。
- **KPI 数据**：指标导出文件（CSV/Excel/JSON 等）。
- **话统数据**：话务统计导出（呼叫量、接通率、话务量等）。
- **告警数据**：告警导出（告警列表、告警历史等）。
- **基础配置信息**：配置文件、参数配置、版本信息、健康检查输出等。
- **资源数据**：Pod CPU/内存使用、业务内存占用、控制块、定时器等关键运行资源快照。
- 其他辅助信息：系统描述文档、版本说明等。

核心能力：

- **包解析**：安全解压、按类落位与自动分类（日志/KPI/话统/告警/配置/资源）；嵌套子压缩包按名称规律与内容嗅探分类；**一个数据包 = 一个任务 = 一个系统（1:1）**——在线一次上传一个包，离线目录顺序分析。
- **日志巡检**：采用「先过滤、再分析」流水线——先按时间范围/级别/关键字/模块裁剪数据，再执行错误聚合、堆栈模式识别、时间分布等分析；单条分析规则调试只消费过滤后数据，执行效率高。
- **KPI 巡检**：阈值检查、趋势分析、基线比对、数据完整性校验。
- **话统巡检**：指标统计、环比/同比比对、异常指标识别。
- **告警巡检**：告警量统计、类型分布、重复告警与处置状态分析。
- **配置巡检**：基础配置完整性检查、关键配置项比对、参数一致性校验。
- **资源巡检**：Pod CPU/内存水位与限制余量、业务内存增长与泄漏迹象、控制块使用率与分配失败、定时器数量与超时堆积检查。
- **规则执行编排**：巡检规则按优先级分级执行（P0 数据准备 → P1 基础检查 → P2 综合分析），规则间依赖由「消费的中间产物」自动推导；支持单条规则单独重跑并自动补跑依赖链，中间产物复用避免重复解析。
- **巡检任务与报告**：规则模板、结果记录、HTML 报告在线预览与历史归档（不做 PDF/下载）。

## 运行模式

系统支持两种运行模式，二者共享同一套巡检器（Inspector）注册机制与巡检规则库：

### 在线模式

- 面向团队/多人使用，提供 Web 前端，支持多人同时上传数据包、发起巡检与查看报告。
- 纯内部使用：系统默认开放，不接入用户认证与权限控制。
- 能力：巡检任务管理、报告在线预览与共享、历史记录与归档。
- 执行模型：首版为**单线程顺序执行任务**，不做并发与分布式；架构稳定后再按需优化性能。
- 数据持久化：SQLite（任务元数据）+ 文件存储（上传原始包存 `uploads/`，解压与产出等运行时数据统一落在 `output/` 下，不入库；默认零安装、无外部服务）；多人/大规模部署时可选切换 PostgreSQL，不影响契约与业务代码。
- 部署：单机部署（Docker 可选），默认无外部数据库/中间件依赖；集群/K8s 后期按需引入。

### 本地开发模式

- 面向巡检规则开发者，用于快速自验巡检规则，无需启动 Web 服务与数据库。
- 依赖最简：无数据库，直接产出契约 JSON 文件与 HTML 报告，秒级启动，便于规则迭代与单元测试。

**典型调试工作流**：

1. **首次运行**：本地运行默认扫描 `uploads/` 根目录下的压缩包——把收集包直接放进该目录，执行 `python main.py`（等价于 `make verify` / `python -m app.cli run`）即可一键跑通全部流程：扫描包、自动解压、运行全部规则、生成契约化数据与 HTML 报告并打印摘要；多个压缩包**顺序分析**，每个包独立一个任务；可选 `PACKAGE_DIR=<目录>` 指定其他输入目录。离线模式忽略客户信息，`system_id` 自动由包名生成；原始包归档到 `uploads/<task_id>/`，解压数据、中间产物与契约结果统一落在输出目录（`output/<task_id>/<system_id>/`），全部不入库。
2. **单条规则调试**：执行 `make verify-one RULE=<rule_code> [SYSTEM=<system_id>]`（CLI 以 `--rule` 指定规则 code、`--system-id` 限定系统），仅重跑指定规则并原地更新其结果数据。
3. **快速看效果**：启动前端（`cd web && npm run dev`），刷新页面即可查看最新巡检结果与展示效果，无需重跑全部规则。
4. **PyCharm 一键运行**：每个规则文件内置独立运行入口（`if __name__ == "__main__"`），在编辑器中直接点击 Run 按钮即可执行该规则（依赖自动补跑），更新契约数据并打印摘要；默认扫描 `uploads/` 根目录的包（多个包时取最新添加的一个），无包时回退样例数据包 `tests/fixtures/sample/`，也可用 `PATROLX_PACKAGE_DIR` 环境变量指定，无需命令行参数。

## 技术栈（默认，可在需求确认后调整）

- 后端：Python 3.11+，Web 框架 FastAPI，数据校验 Pydantic v2。
- 数据分析：pandas、pyarrow 等按需引入（大型日志/CSV 解析），以简化开发成本为准，不做强制依赖。
- 存储：轻量优先——SQLite + 扁平 JSON 文件存储（默认零安装、无外部服务）；在线模式多人/大数据量场景可选切换 PostgreSQL。巡检结果统一以扁平 JSON 文档存储（任务/系统/规则独立文档），避免按规则定制表结构。
- 报告：Jinja2 生成 HTML，Web 在线预览（不做 PDF 与下载）。
- 前端：React + TypeScript + Vite + Ant Design + ECharts（UI 风格“简约而不简单”）。
- 部署：Docker + Docker Compose。
- 可观测：structlog 结构化日志、Prometheus 指标暴露。

## 核心处理流程

以下流程描述在线模式；本地开发模式执行同一套“解压 → 识别 → 巡检 → 产出结果”流水线，直接输出终端摘要与 JSON，不涉及上传与前端展示。**`python main.py` 是本地离线全流程的统一入口**（等价于 `make verify` / `python -m app.cli run`）。

1. **上传**：在线一次上传一个压缩包，对应一个任务；离线模式默认扫描 `uploads/` 根目录下的压缩包（可选 `PACKAGE_DIR=<目录>` 指定其他目录），多个压缩包顺序分析；只识别根目录下的压缩包文件，忽略归档子目录。校验格式（zip/tar.gz）、大小限制（默认 2GB，可配置）。
2. **系统识别**：在线模式上传时可选从**可配置数据字典**中选择省份、运营商、产品形态、版本等（均非必填），系统按「省份 + 运营商」组合生成客户标识 `system_id`（可手动覆盖）；不选时 `system_id` 取包名去扩展名兜底。离线模式忽略客户信息与版本，按包名自动生成 `system_id`，只产生规则契约结果。
3. **执行巡检**：执行器按优先级执行规则；解压作为隐藏的 P0 规则族（`pkg.extract.{category}`）自动先跑——主包按类落位、嵌套子包按类懒解压（清单去重、只解压一次），随后 P1/P2 巡检规则执行，产出契约化结果与中间产物。
4. **生成报告**：聚合系统与规则结果，生成 HTML 报告落盘 `output/<task_id>/report.html` 并归档。
5. **查看**：前端展示任务 → 系统 → 规则三级下钻，报告在线预览、历史任务查询、执行日志查看。

## 接口契约约定

- **契约优先**：前后端接口以 OpenAPI 3.0 契约为准，契约文件存放于 `docs/api/openapi.yaml`。
- **契约即实现**：后端 FastAPI 基于 Pydantic Schema 生成接口，并保证与契约一致；前端基于契约生成类型与 API 客户端（如 openapi-typescript），禁止手写与契约不一致的调用代码。
- **版本化**：接口路径带版本前缀 `/api/v1`；破坏性变更必须升级版本号（`v2`），禁止在既有版本内修改字段含义或删除字段。
- **统一响应**：资源接口成功直接返回资源 JSON（不套壳）；创建/重跑类接口返回 `202 + Location` 供轮询；错误统一返回 `{code, message, detail}` + HTTP 状态码，`code` 枚举在契约中列出。
- **分页与过滤**：列表接口统一使用 `page`/`page_size` 分页与结构化过滤参数，响应返回总数。
- **变更流程**：接口契约变更需同步更新契约文件与前端生成代码；新规则等内部能力扩展优先走巡检器注册机制，不依赖接口变更。
- **交付节奏**：前端与后端可按契约独立开发与联调，契约文件先于实现落地；契约审查通过后才允许进入编码。

### 接口清单（v1）

**任务**

- `POST /api/v1/tasks`：创建任务，multipart 上传一个数据包（一个压缩包 = 一个任务）→ `202 + Location: /tasks/{id}`，前端轮询任务状态；可选 `customer{province,operator}`、`version`、`name`。
- `GET /api/v1/tasks`：任务列表（`page/page_size/status/system_id` 过滤，返回摘要与总数）。
- `GET /api/v1/tasks/{task_id}`：任务摘要（`stats` + 系统状态，不含全量规则结果）。
- `POST /api/v1/tasks/{task_id}/rerun`：增量重跑，body `{rule_codes?}`（不填表示重跑该任务全部规则）→ `202`。
- `GET /api/v1/tasks/{task_id}/report`：巡检报告（HTML 在线预览，不做下载）。
- `GET /api/v1/tasks/{task_id}/logs`：任务执行日志（任务创建、解压/子包、分类落位、每规则执行与异常、报告生成），供调试与追溯。

**系统**

- `GET /api/v1/tasks/{task_id}/system`：系统摘要（`summary` + 规则状态列表 + `customer`/`version`）。
- `GET /api/v1/tasks/{task_id}/rules/{rule_code}`：单规则完整结果（`metrics`/`findings`/`artifacts`），供前端增量刷新。

**规则元数据**

- `GET /api/v1/inspectors`：全部已注册规则元数据（`code/name/category/severity/priority/rule_version/hidden/description/recommendation/inputs/outputs/params`），供规则管理、依赖展示与处理建议展示；前端不展示 `hidden=true` 的内部规则。
- **规则管理边界**：在线规则管理仅提供只读查看（`GET /api/v1/inspectors`），不做在线启停、参数配置与代码编辑/上传；规则变更一律走代码开发 → 本地自验 → 部署。

**数据字典**

- **预制字典**：省份/运营商/产品形态/版本等字典作为初始化数据随系统内置（种子数据，开箱即用），后续可配置扩展。
- `GET /api/v1/dicts`：返回全部预制字典，供上传表单下拉选择。
- `PUT /api/v1/dicts/{dict_name}`：维护字典项（纯内部开放；管理页面后续再做）。

## 前端界面设计

### 技术栈与工程

- React + TypeScript + Vite + Ant Design + ECharts；API 客户端由 `docs/api/openapi.yaml` 经 openapi-typescript 生成（`web/src/api/`），禁止手写与契约不一致的接口调用。
- 桌面优先（纯内部使用），不做移动端适配；视觉风格延续「简约而不简单」——卡片化、留白充足、语义色徽标、无冗余动效。

### 页面与路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/` | 任务列表 | 默认首页：状态统计 + 任务列表 + 上传入口 |
| `/tasks/:taskId` | 任务详情 | 摘要统计卡片 → 包信息 → 规则列表，支持重跑与报告/日志入口 |
| `/tasks/:taskId/rules/:ruleCode` | 规则详情 | 指标图表、发现证据、处理建议、产物 key |
| `/tasks/:taskId/report` | 报告预览 | iframe 在线预览 Jinja2 生成的 HTML 报告（不做下载） |
| `/tasks/:taskId/logs` | 执行日志 | 结构化执行日志查看 |
| `/inspectors` | 规则管理 | 只读规则列表（过滤 `hidden` 内部规则） |
| `/dicts` | 数据字典 | 字典分组查看与维护 |

### 布局与导航

- 左侧导航 + 主内容区（Antd `Layout`）：导航项「巡检任务 / 规则管理 / 数据字典」；任务详情页提供返回与面包屑。
- 状态徽标统一语义色：`pass` 绿 / `warn` 黄 / `fail` 红 / `error` 灰 / `skip` 蓝（悬停展示 `skip_reason`）。

### 核心页面与交互

1. **任务列表页**：顶部状态分布统计卡片；列表支持按状态/时间分页筛选；「上传数据包」按钮弹出上传对话框——选择一个压缩包 + 可选字典下拉（省份/运营商/产品形态/版本）+ 任务名称，提交后轮询任务状态直至完成。
2. **任务详情页**：摘要统计卡片（pass/warn/fail/error/skip）→ 包信息（`package_file`/`version`/`customer`）→ 规则列表（状态徽标 + summary + severity，按类别分组）；支持「重跑全部」与单规则「重跑」，执行中定时轮询（如 2s）自动刷新；提供「查看报告」「执行日志」入口。
3. **规则详情页**：规则描述与处理建议（只读）；指标区用 ECharts 渲染——单值大数字 + 阈值参考线，`series` 趋势用折线图，通用表格兜底；发现列表展示 severity 徽标、`evidence`（截断展示）、`source_file` 与 `recommendation`；底部列出产出/消费的产物 key。
4. **报告预览页**：iframe 内嵌 HTML 报告，不做 PDF/下载。
5. **规则管理页**：只读表格（`code/name/category/priority/severity/rule_version/description/recommendation/inputs/outputs`），过滤 `hidden=true`，支持按类别筛选与搜索。
6. **数据字典页**：按字典分组展示；首版先做查看，维护（`PUT /dicts/{name}`）后续补充。

### 增量刷新

- 单规则重跑完成后仅刷新该规则卡片/详情，不整页重载；任务执行中自动轮询，完成后刷新摘要。

### 本地模式

- 本地模式与在线模式共用同一套页面：本地启动后端（`uvicorn app.main:app`）直读 `output/`，前端 `npm run dev` 通过代理（`VITE_API_PROXY`）指向本地 API，无需数据库即可浏览巡检结果。

## 契约化巡检数据

- 巡检任务与结果数据（任务、系统、规则结果、告警发现等）由 OpenAPI 契约中的 Schema 统一定义（如 `InspectionTask`、`RuleResult`），CLI 落盘数据与在线模式 API 返回数据使用同一套 Pydantic 模型，保证展示层一致。
- 本地输出目录按「任务 → 系统 → 规则」组织，规则结果以单文件存储（`output/<task_id>/<system_id>/rules/<code>.json`），支持单条规则重跑后原地更新。
- Web 展示层只消费契约化数据：在线与本地模式均通过同一套 API 提供（本地模式由 FastAPI 直读 `output/` 契约 JSON，无需数据库），两者数据结构一致，前端一套组件两种模式通用。

## 巡检数据模型（输出结构）

输出采用「任务 → 系统 → 规则 → 发现」四层结构，全部由 OpenAPI 契约 Schema 定义，保证可扩展性与展示一致性。

### 层级说明

| 层级 | 模型 | 说明 |
| --- | --- | --- |
| 任务 | `InspectionTask` | 一次巡检执行，对应一个压缩包/客户系统 |
| 系统 | `SystemInspection` | 一个压缩包/客户系统，含包元信息与多个规则结果 |
| 规则 | `RuleResult` | 一条巡检规则的结果，含优先级、消费/产出产物、指标（metrics）与发现（findings），可产出中间产物（artifacts）供下游规则复用 |
| 发现 | `Finding` | 具体问题点，含证据、影响与建议 |

### 核心字段

- `InspectionTask`：`task_id`、`name`、`mode`（online/local）、`status`、`trigger`、`created_at`、`completed_at`、`stats`、`system`（一个压缩包/客户系统的巡检结果，1:1）。
- `SystemInspection`：`system_id`、`system_name`、`package_file`、`package_checksum`、`version`（可选：版本，来自版本字典）、`status`、`summary`、`rules[]`（规则结果列表）、`customer{}`（可选：省份/运营商/产品形态等，来自可配置字典，键值可扩展）。
- `RuleResult`：`code`、`name`、`category`（log/kpi/traffic/alarm/config/resource/other）、`priority`、`inputs[]`（消费的中间产物 key，执行器据此自动推导依赖）、`execution_order`、`status`（pass/warn/fail/error/skip）、`severity`、`summary`、`skip_reason`（可选：未执行原因，`status=skip` 时必填）、`executed_at`、`duration_ms`、`metrics[]`、`findings[]`、`artifacts[]`（产出中间产物 key，供下游规则消费）、`metadata{}`。
- `Metric`：`key`、`label`、`value`、`unit`、`threshold{}`、`baseline`、`series[]`（趋势图数据）。
- `Finding`：`finding_id`、`title`、`severity`、`source_file`、`evidence`、`details`、`recommendation`、`metrics[]`。

### 输出结构示例（简化）

```json
{
  "task_id": "task-20260909-001",
  "status": "completed",
  "stats": { "systems": 1, "pass": 8, "warn": 2, "fail": 1, "error": 0, "skip": 1 },
  "system": {
    "system_id": "sys-001",
    "system_name": "客户A核心网",
    "package_file": "customer_a.tar.gz",
    "version": "R12",
    "status": "completed",
    "summary": { "total": 12, "pass": 8, "warn": 2, "fail": 1, "error": 0, "skip": 1 },
    "rules": [
      {
        "code": "log.error_density",
        "name": "日志错误密度",
        "category": "log",
        "priority": 1,
        "inputs": ["pkg.extract.log.ready"],
        "execution_order": 3,
        "status": "warn",
        "severity": "medium",
        "summary": "错误日志密度超限",
        "metrics": [
          { "key": "error_count", "label": "错误条数", "value": 152, "unit": "条", "threshold": { "max": 100 } }
        ],
        "findings": [
          {
            "finding_id": "f-001",
            "title": "核心网错误日志密度超限",
            "severity": "medium",
            "source_file": "logs/core/error_20260909.log",
            "evidence": "2026-09-09T10:00:00Z ERROR ...",
            "recommendation": "检查数据库连接池配置"
          }
        ]
      }
    ]
  }
}
```

### 扩展与展示约定

- **扩展约定**：新增规则只新增 `code` 与自定义 `metric.key`/`metadata` 字段，禁止改动既有字段语义；新增类别需在 `category` 枚举与契约中同步扩展。
- **状态语义**：`pass`=通过（绿）、`warn`=告警（黄）、`fail`=失败（红）、`error`=执行异常（灰）、`skip`=跳过（蓝，展示未执行原因）。
- **展示建议**：任务/系统摘要卡片（状态统计）→ 规则列表（状态徽标+summary）→ 规则详情（指标图表、发现证据、建议）；`metrics.series` 供趋势图，`finding.evidence` 供证据展示。
- **展示路径**：任务 → 系统 → 规则 三级下钻；跨任务/跨客户对比属于后期趋势分析能力。

### 状态机与统计口径

- `InspectionTask.status`：`pending`（排队中）→ `running`（执行中）→ `completed`（完成）/ `failed`（任务级失败）；`trigger` 为任务触发来源（`api` 上传 / `cli` 本地 / `rerun` 重跑）。
- `SystemInspection.status`：`completed` / `failed`；`summary.total` = 该系统全部规则结果数（含 hidden 规则与 `skip`），`pass/warn/fail/error/skip` 各项之和等于 `total`。
- `InspectionTask.stats`：跨系统汇总（单系统任务下与系统 `summary` 一致，另含 `systems` 计数）。

## 规则执行编排

巡检规则通过**优先级分级 + 消费即依赖**组织执行顺序：规则只声明优先级与消费的中间产物，依赖关系由执行器自动推导，避免重复计算，同时保证单条规则可独立重跑。

### 优先级分级

| 优先级 | 说明 | 示例 |
| --- | --- | --- |
| P0 数据准备 | 加载、解析、标准化、过滤，只产出中间产物（artifacts） | `log.filter`（日志裁剪）、`kpi.load`（指标加载） |
| P1 基础检查 | 单维度阈值与统计，消费 P0 产物 | `log.error_density`、`kpi.threshold`、`alarm.stat` |
| P2 综合分析 | 跨维度关联、环比/同比、趋势与根因分析，消费 P0/P1 产物 | `traffic.compare`、`resource.trend` |

- 规则注册时声明 `priority`（默认 P1）与 `inputs[]`（消费的中间产物 key，如 `log.filter.artifacts.filtered_logs`）。
- **消费即依赖**：执行器维护「产物 key → 生产者规则」映射，从规则 `inputs[]` 自动反推依赖关系，无需手写依赖规则列表。
- 依赖约束：自动推导出的依赖只能指向**更高优先级**规则；同优先级内不允许互依赖，**例外**是解压基础设施规则（`pkg.extract.*`，hidden）可被同优先级规则依赖（如 `log.filter` 依赖 `pkg.extract.log`），执行计划将其置前、天然无环；注册/启动时校验循环依赖与非法依赖，违规直接报错。
- 全量执行：按优先级分组升序执行，组内按推导出的依赖拓扑排序；同一规则只执行一次。

### 规则元数据与输出契约

每个规则注册时声明完整元数据与输出结构（RuleContract），保证规则**可独立执行、松耦合、统一管理与稳定消费**：

- 元数据：`code`、`name`、`category`、`severity`、`priority`、`rule_version`（规则代码版本，修改逻辑必须升级；与数据包版本 `SystemInspection.version` 区分）、`hidden`（是否前端展示，默认 false；解压等内部准备规则置 true，不展示、不进报告）、`description`（规则描述：检查内容与判定逻辑）、`recommendation`（处理建议：命中时如何处置）；
- `inputs[]`：消费的中间产物 key；
- `outputs.metrics[]`：产出指标定义（`key/label/unit/type`），如 `error_count`（条/数值）、`cpu_usage`（%/数值或趋势）；
- `outputs.artifacts[]`：产出的中间产物 key；
- `params[]`：可配置参数定义。

- 注册时校验（`description`/`recommendation` 非空、契约合法）；执行时校验实际产出与契约一致（指标 key 集合与 unit 一致），不一致记为 `error` 结果；**`skip`/`error` 状态豁免输出契约校验**（仅 `pass`/`warn`/`fail` 要求产出声明的 metrics）。
- **松耦合**：规则之间互不引用代码，仅通过 `inputs`/artifacts 传递数据；每个规则可独立执行、单独重跑，不依赖其他规则的实现。
- 意义：`metric.key` 成为**契约级稳定标识**，跨任务/跨系统趋势聚合可靠；`GET /api/v1/inspectors` 返回全部规则元数据与输出契约，前端据此渲染规则描述、处理建议与图表。

### 单规则重跑与依赖

- 单独重跑规则 R 时，执行器沿 R 的 `inputs[]` 查找生产者形成依赖链；前置规则结果缺失或过期则自动补跑，再执行 R。
- 重跑完成后只更新 R（及其直接依赖它的规则）的结果数据，Web 增量刷新对应规则卡片，其余规则结果不动。
- 规则结果独立落盘/独立接口（`output/<task_id>/<system_id>/rules/<code>.json`），单规则更新不影响其他规则。

### 中间产物（artifacts）

- 为避免重复解析，规则可将解析/过滤结果写入运行时工作目录 `output/<task_id>/<system_id>/artifacts/<rule_code>/`。
- **显式传递**：下游规则只能通过 `inputs[]` 声明要消费的 artifacts，执行器据此推导依赖，不读其他规则产物，依赖关系可追踪。
- artifacts 为运行时中间数据，不进入契约结果 JSON；规则结果通过 `artifacts[]` 字段声明产出 key 供下游引用。
- **统一格式 + 定制化**：规则结果采用统一契约格式（`status/severity/summary/metrics[]/findings[]/metadata{}`）；定制化数据通过 `metadata{}`（结构化自由键值）与 artifacts（自由格式数据，输出契约声明 key）承载。展示层统一渲染通用字段，对定制数据透传可扩展。
- **依赖产物过期判定**：首版采用「存在即复用」——数据包未变时直接复用依赖产物，不做过期判断；重跑某规则时其依赖链自动补跑或复用。
- 产物有效性校验（规则版本）：每个 artifact 记录生产它的规则 `rule_version`；执行器判断产物存在且版本与当前注册规则一致才复用，版本不一致视为过期、自动重跑生产者重新生成。修改规则逻辑必须升级 `rule_version`。

### 日志先过滤再分析

- 日志类规则统一走 `log.filter`（P0）：按时间范围、级别、关键字、模块先裁剪原始日志，产出过滤后数据集与索引。
- `log.filter` 默认行为：首版默认「全量规范化 + 按级别/模块切分」产出产物；时间范围、关键字等过滤参数使用规则代码内的默认参数，需要调整时改代码并升级 `rule_version`（在线不做参数配置）。
- 各分析规则（`log.*`，P1/P2）通过 `inputs: [log.filter.artifacts.filtered_logs]` 只读取过滤产物，不再重复扫描全量日志；单条分析规则调试时仅需 `log.filter + 目标规则`，执行速度快。

## 解压与目录规划

### 目录布局（客户隔离 + 按类落位）

每个客户系统独占一个目录，解压时边解压边按类落位，分类结果由目录结构直接表达：

```
uploads/                        # 上传的原始压缩包（输入现场，只存原始包、长期保留）
└── <task_id>/
    └── <原始压缩包>             # 如 customer_a.tar.gz（在线上传落盘；本地运行直接放置于 uploads/ 根目录）

output/                         # 运行时统一目录（处理现场：解压数据与全部产出，不入库）
└── <task_id>/
    ├── <system_id>/            # 每客户独立目录（省份+运营商字典组合生成，可选覆盖，包名兜底）
    │   ├── logs/               # 日志类（解压数据）
    │   ├── kpi/                # KPI 类
    │   ├── traffic/            # 话统类
    │   ├── alarm/              # 告警类
    │   ├── config/             # 配置类
    │   ├── resource/           # 资源类
    │   ├── other/              # 未分类
    │   ├── artifacts/          # 中间产物（<rule_code>/）
    │   └── rules/              # 规则契约结果（<code>.json）
    ├── report.html             # HTML 报告
    └── execution.log           # 结构化执行日志
```

- **目录职责分离**：`uploads/` 根目录是本地运行的默认输入源（直接放包即可运行），任务处理完成后原始包归档到 `uploads/<task_id>/` 长期保留（输入现场，解压只读不修改）；`output/<task_id>/` 存放全部处理产物（解压数据、中间产物、规则契约结果、执行日志、报告，不入库）。二者共同构成一个任务的完整现场，删除任务即级联删除两个目录。

- **客户归属规则**：在线模式上传时可选从数据字典选择省份/运营商/产品形态/版本（均非必填），按「省份 + 运营商」组合生成 `system_id`（可手动覆盖）；不选时取包名去扩展名兜底。离线模式忽略客户信息与版本，`system_id` 由包名自动生成，只产生规则契约结果。一个压缩包独立一个任务与目录；客户关联通过 `system_id` 跨任务聚合（用于后期趋势分析），不做同任务合并。
- **`system_id` 生成**：字典组合按「省份编码 + 运营商编码」生成（如 `gd_cmcc`；字典项含中英文名与编码，编码仅小写字母/数字/`_`，保证可作为目录名）；可手动覆盖；离线包名兜底时同样清洗（去扩展名、非法字符转 `_`）。
- **原始包处理**：原始压缩包保留在 `uploads/<task_id>/` 长期留存（在线上传落盘；本地运行直接放置于 `uploads/` 根目录，处理后归档到 `uploads/<task_id>/`），名称记录在契约数据 `package_file` 中用于追溯；解压只读取原始包，不修改其内容。
- 文件按分类规则（文件名/扩展名/目录前缀）直接解压到对应类别目录，保留包内相对路径。
- 嵌套子压缩包先判定类别，解压到 `<类别>/<子包名>/` 下，保留原始层级，便于 `finding.source_file` 定位。

### 子包只解压一次（幂等 + 去重）

- 每个系统目录维护解压清单 `.patrolx-extracted.json`，记录每个子包的 `checksum + 解压目标目录 + 文件数`。
- 解压清单由解压规则族（`pkg.extract.{category}`）维护，随任务生命周期管理。
- 同一子包（checksum 相同或同一相对路径已解压）直接复用，不重复解压；规则单条重跑时解压阶段幂等跳过。

### 子包名称规律分类（可配置规则表）

- 子包名称往往含业务变量但存在规律，如 `ServiceLog.zip`、`AAAService.zip` 均对应日志；分类不依赖精确文件名。
- 分类规则采用**可配置规则表**（正则/通配符 + 中文别名），如 `*log*`、`*service*`、`*日志*` → 日志；支持业务名前缀变量（`{module}Log.zip`、`{module}Service.zip`）。
- 分类规则表以配置文件承载（如 `deploy/config/classify_rules.yaml`），随部署可调，不改代码。
- 名称无法判定时，解压后按**内部文件名/内容嗅探**兜底分类；仍无法判定归入 `other/`。
- 新增客户包格式通过补充规则适配，不修改核心分类逻辑。

### 安全限制

- 嵌套解压限制：深度上限（默认 2 层）、文件数上限、单文件大小上限、总量预算（上传大小 × 膨胀系数），防解压炸弹。
- 每层解压均做路径穿越与链接防护；超限/异常文件不中断任务，记录到 `pkg.extract` 规则结果（ERROR/WARN）。

### 生命周期

- 任务、巡检结果与执行日志**长期保留，不自动清理**；支持手动删除任务（级联删除该任务的 `uploads/<task_id>/` 与 `output/<task_id>/` 全部现场数据）。

### 与规则执行衔接

- **解压即规则**：解压作为 P0 规则（`pkg.extract.{category}`，如 `pkg.extract.log`）实现，标记 `hidden=true` 前端不展示；执行结果落盘便于追溯，异常时在 `pkg.extract` 结果中提示。
- 主包解压：`pkg.extract.main`（hidden，P0）负责主包按类落位并写入子包清单；执行器先跑 `pkg.extract.main`，各类别子包解压规则随后按需执行。
- hidden 规则的 `error` 计入任务/系统摘要的 error 统计（任务状态可置为 failed/warn），详情在执行日志中查看。
- 执行流程：主包解压按类落位 → 嵌套子包仅登记清单（名称/类别/checksum，不立即解压）→ 某类别规则执行前，执行器自动先跑该类别解压规则（`pkg.extract.{category}`），按类解压、按类落位 → 再执行巡检规则。
- 依赖衔接：`log.filter` 等规则通过 `inputs: [pkg.extract.log.ready]` 依赖对应类别解压产物，执行器沿 `inputs` 自动补跑解压规则；清单去重保证子包只解压一次。
- **解压时机**：解压仅在任务执行时按需触发，`main` 启动只自动装载规则、不预解压；首次解压无时机限制。
- **就绪判定**：某类别是否存在未解压子包，由主包解压时写入的解压清单（`.patrolx-extracted.json`）提供；执行器执行该类首个规则前检查清单，有未解压子包则先跑该类解压规则。

## 目录结构

```
PatrolX/
├── app/                        # 后端主包
│   ├── main.py                 # 统一入口：python main.py 一键跑本地离线全流程；作为模块导入（uvicorn app.main:app）时提供 FastAPI 服务
│   ├── cli.py                  # 本地开发模式 CLI 入口（规则自验，main.py 的等价/细粒度入口）
│   ├── api/                    # 路由层（上传、任务、报告、规则管理）
│   ├── core/                   # 配置、安全解压、文件识别、规则注册表
│   ├── models/                 # SQLAlchemy 模型与 Pydantic Schema
│   ├── services/               # 业务逻辑（任务执行、结果归档、报告生成）
│   ├── inspectors/             # 各领域巡检器
│   │   ├── log/                # 日志规则
│   │   ├── kpi/                # KPI 规则
│   │   ├── traffic/            # 话统规则
│   │   ├── alarm/              # 告警规则
│   │   ├── config/             # 配置规则
│   │   ├── resource/           # 资源规则（Pod/内存/控制块/定时器）
│   │   └── base.py             # Inspector 基类与注册机制
│   └── reports/                # 报告模板与渲染
├── web/                        # 前端工程（React+TS+Vite+Antd+ECharts）
│   └── src/
│       ├── api/                # 契约生成的 API 客户端（openapi-typescript）
│       ├── layouts/            # 主布局（侧边导航 + 内容区）
│       ├── pages/              # 任务列表/详情、规则详情、报告、日志、规则管理、字典
│       ├── components/         # StatusTag、SummaryCard、MetricChart、FindingList、UploadModal 等
│       └── hooks/              # 任务/规则重跑轮询等
├── uploads/                    # 上传的原始压缩包（输入现场：根目录为本地输入源，按 task 归档，不入库）
├── output/                     # 运行时唯一根：解压数据、中间产物、规则契约结果、执行日志与报告（全部不入库）
├── deploy/                     # Docker、编排、环境配置
├── docs/                       # 设计文档、接口契约（api/openapi.yaml）、规则规范
├── tests/                      # 单元与集成测试（fixtures/sample/ 样例数据包）
├── README.md
├── .gitignore                  # 忽略 output/、uploads/、.venv、node_modules 等运行时目录
├── requirements.txt
├── pyproject.toml
└── Makefile
```

## 开发约定

- 语言：注释、提交信息、文档使用中文；代码标识符、接口字段使用英文。
- Python 规范：Python 3.11+，全量类型注解，遵循 PEP 8；使用 ruff 做 lint，格式化使用 ruff format。
- 后端分层：`api`（接口）→ `services`（业务）→ `inspectors`（巡检逻辑）/`models`（数据），禁止跨层调用。
- 契约一致性：后端新增或修改接口时，必须同步更新 `docs/api/openapi.yaml`；前端改动调用前先核对契约。
- 巡检器扩展：新巡检能力继承 `Inspector` 基类并注册；启动时自动扫描规则目录装载全部规则（新增规则即插即用，无需修改注册代码），禁止修改核心调度逻辑。
- 规则编排校验：新增规则声明 `priority` 与 `inputs[]`；执行器由 `inputs` 自动推导依赖并校验循环与优先级合法性（只允许依赖更高优先级规则），注册时自动校验。
- 规则输出契约：每个规则注册时声明输出结构（`outputs.metrics[]`/`outputs.artifacts[]` 等），执行产出必须与契约一致；`metric.key` 为契约级稳定标识，跨任务不可变。
- 规则元数据：每个规则必须声明 `rule_version`、`description`（规则描述）与 `recommendation`（处理建议），注册时校验非空；规则间松耦合，只通过 `inputs`/artifacts 交互，可独立执行与单独重跑。
- 本地一键运行：每个规则文件必须提供独立运行入口（`if __name__ == "__main__"`），默认使用样例数据包执行自身规则并更新契约数据，便于 PyCharm 直接点击运行。
- 无数据处理：规则未扫描到所需文件或依赖产物缺失时，必须返回 `status=skip` 并明确填写 `skip_reason`（如“未发现日志类文件”“依赖产物 `log.filter.artifacts.filtered_logs` 缺失”），不得抛异常或静默通过。
- 证据控制：规则写 `finding.evidence` 时需截断控制长度（默认单条 2KB），完整上下文保留在源文件，通过 `source_file` 定位。
- 规则自验：新增或修改巡检规则后，必须能在本地开发模式（CLI）下用样例数据包快速验证通过。
- 示例先行：初期为日志/KPI/话统/告警/配置/资源每个类别各落地一个示例规则，用真实样例包验证整体流程与展示效果，再扩展规则集并按需调整设计。
- 压缩包处理：必须使用安全解压（校验路径穿越、符号链接与解压炸弹），按类落位到客户独立目录；嵌套子包按校验和清单去重，每个子包只解压一次。
- 数据解析：统一使用 pandas/pyarrow 读取结构化数据，读取失败需记录为“解析失败”规则结果而非中断任务。
- 格式对齐：包内数据格式以真实内网数据为准，按样例逐步对齐——每接入一种新格式通过新增/调整分类规则与解析器适配，不预设完整格式规范，核心流程不变。
- 错误处理：业务错误使用统一异常类型与错误码，禁止静默吞掉异常；每个任务执行必须有结果记录。
- 日志：统一使用 structlog，输出 JSON 格式；关键操作记录任务 ID、操作人与结果。
- 执行日志：执行引擎按任务记录结构化执行日志（任务创建、解压与子包处理、分类落位、每规则执行与异常、报告生成），落盘到任务目录（`output/<task_id>/execution.log`）；规则结果与日志通过 `task_id/rule_code/时间` 关联，便于追溯与前端查看。
- 时间：所有时间统一使用 UTC 存储，展示层转本地时区；时间字段统一命名 `*_at`。
- 测试：每条规则必须有单元测试；新增规则需配套样例数据与测试用例。
- 双模式一致性：同一数据包分别经 CLI 与 API 执行，结果 JSON 一致性由测试保障（除 id/时间戳外逐字段比对）。
- 命名：目录与包名小写单数；巡检器命名遵循业务领域词汇（如 `LogErrorInspector`、`KpiThresholdInspector`）；规则 `code` 用小写点分命名（`<category>.<name>`，仅小写字母/数字/点，同时作为结果文件名，保证文件系统安全）。

## Git 约定

- 分支命名：`feature/*`、`fix/*`、`chore/*`、`docs/*`。
- 提交信息格式：`<type>(<scope>): <subject>`，如 `feat(kpi): 增加阈值巡检器`。
- 提交前检查：通过 `make lint` 与 `make test`，并保持提交粒度聚焦。

## 常用命令

```bash
make install      # 安装后端依赖
make run          # 本地启动 API 服务（uvicorn app.main:app --reload）
make verify       # 本地开发模式：等价于 python main.py——扫描上传目录中的压缩包（默认 uploads/ 根目录，可选 PACKAGE_DIR=<目录>，每个包独立任务、顺序分析）并运行全部规则，生成契约化巡检数据与报告
make verify-one   # 本地开发模式：仅重跑指定规则（RULE=<rule_code>，可选 SYSTEM=<system_id>）
make contract     # 校验并导出 OpenAPI 契约到 docs/api/openapi.yaml
make gen-web-api  # 前端基于契约生成 API 客户端
make test         # 运行 pytest
make lint         # 运行 ruff 检查与格式化校验
docker compose up # 启动服务与依赖
cd web && npm run dev  # 启动前端开发服务
```

## 迭代计划

迭代节奏遵循「契约先行、示例先行、从简优先」：先冻结契约与骨架，再跑通本地全流程，补齐六类示例规则，最后做在线模式与前端；性能优化与趋势分析不在本期范围。

**当前进度**：M0–M4 已完成（`make test` 28 passed、`make contract`/`make lint` 绿；M4 前端已构建并与后端联调冒烟通过）；M5 已落地 structlog 结构化日志、`/metrics` Prometheus 指标、Dockerfile/docker-compose（用户暂不安装 Docker，`docker compose up` 待实际环境验证）、任务生命周期执行日志与错误码枚举；浏览器全流程与真实内网包格式对齐待补充。

### M0 工程初始化与契约先行

- 目标：工程骨架落地、OpenAPI 契约 v1 冻结。
- 范围：`git init` 与目录骨架（app/web/deploy/docs/tests）、`README.md`/`.gitignore`/`Makefile`/`pyproject.toml`；`docs/api/openapi.yaml` 定义全部 Schema 与接口；Pydantic 模型与契约对齐；数据字典种子数据（省份/运营商/产品形态/版本）。
- 验收：`make contract` 通过；模型与契约一致性测试通过；`make lint`/`make test` 绿。
- 依赖：Python 3.11+ 环境（本机 3.9.6 不满足，需先准备）。

### M1 规则框架与本地全流程

- 目标：`python main.py` 一键跑通本地离线全流程。
- 范围：`Inspector` 基类与自动装载、`RuleContract` 注册校验（`description`/`recommendation`/`rule_version`/`priority`/`inputs`）；安全解压（路径穿越/链接/炸弹防护）与按类落位；`deploy/config/classify_rules.yaml` 分类规则表；子包清单 `.patrolx-extracted.json` 去重；解压规则族 `pkg.extract.main`/`pkg.extract.{category}`（hidden P0）；执行器（优先级分级 + 消费即依赖 + `rule_version` 产物校验 + `skip` 语义）；契约 JSON 落盘与 `execution.log`；首个示例规则闭环（`log.filter` + `log.error_density`）。
- 验收：样例包全流程通过；规则文件可 PyCharm 单跑（`if __name__ == "__main__"`）；`make verify` 通过。

### M2 六类示例规则与报告

- 目标：六类规则各一个示例、HTML 报告可预览。
- 范围：log/kpi/traffic/alarm/config/resource 各落地一个示例规则；按真实内网样例包逐步对齐数据格式；Jinja2 生成 `output/<task_id>/report.html`。
- 验收：六类规则均产出契约结果；报告可在线预览；无数据时正确返回 `skip` + `skip_reason`。
- 依赖：需要真实内网样例包，格式按样例逐步对齐。

### M3 在线模式

- 目标：FastAPI 在线服务全流程可用。
- 范围：实现全部 v1 接口（任务/重跑/报告/日志/系统/单规则/规则元数据/字典）；SQLite 元数据与任务状态机；上传（multipart、默认 2GB）；单线程任务队列顺序执行；`rerun` 增量重跑。
- 验收：CLI 与 API 结果一致性测试通过；在线流程（上传 → 轮询 → 报告预览）可用。

### M4 前端 Web

- 目标：一套页面同时服务在线与本地模式。
- 范围：React + TS + Vite + Antd + ECharts 工程；openapi-typescript 生成 API 客户端；任务列表/详情、规则详情、报告预览、执行日志、规则管理、数据字典页面；增量刷新与状态轮询。
- 验收：本地模式直读 `output/`、在线模式走 API，浏览器全流程可用。

### M5 打磨与部署

- 目标：可交付运行。
- 范围：错误码与执行日志完善、测试与 lint 补齐、Docker Compose 部署、按需基础性能优化。
- 验收：`make test`/`make lint` 全绿；`docker compose up` 一键运行。

### 后续规划（暂不排期）

- 客户维度跨时间/版本趋势分析；规则在线启停与参数配置；字典管理页面增强。

## 后期演进规划（暂不实现）

- **客户维度跨时间/版本趋势分析**：巡检次数累积后，按客户观察不同时间、不同版本的 KPI 业务量、资源使用、告警量等趋势（如 KPI 业务量曲线、内存/CPU 趋势、话务量环比）。
- 当前设计已为此预留支撑，后续无需重构：
  - `system_id` 由「省份 + 运营商」字典组合生成，跨时间稳定，同一客户多次巡检复用同一标识并按任务归档，天然形成时间序列；
  - 巡检结果数值化（`metrics[].value`）且支持 `series[]`，跨任务聚合即可绘制趋势；
  - 版本信息由 `SystemInspection.version` 显式承载（在线上传可选填写），趋势分析时按 `system_id + created_at + 版本` 分组。
- 届时实现形态：新增跨任务聚合分析能力与趋势接口（如 `GET /api/v1/customers/{system_id}/trends?metric=...`）及对应展示组件；涉及契约变更走版本化升级。

## Agent 开发流程约定

- **项目规则优先**：本文件是 PatrolX 的最高约束；Superpowers 只用于辅助 Agent 开发流程，不覆盖、不改写项目架构与契约约定。
- **适用边界**：新增大功能、修改 OpenAPI 契约/数据模型、演进规则执行器或任务模型、设计复杂前端交互时，可使用 Superpowers 流程（brainstorm → spec → plan → TDD → review）；小型改动、文案调整、单条规则调试不强制走完整流程。
- **多窗口协作**：多个窗口/Agent 并行开发时，优先使用独立分支或 `git worktree`；共享同一工作区时必须先沟通写文件边界，避免同时修改同一文件。
- **交付门槛**：无论是否使用 Superpowers，合入前仍必须通过 `make lint`、`make test`；接口变更必须同步 `docs/api/openapi.yaml`，巡检规则逻辑变更必须升级 `rule_version`。
- **触发约定**：
  - “走完整流程” = `superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:test-driven-development` → `superpowers:verification-before-completion`。
  - “小改动” = `superpowers:test-driven-development` → `superpowers:verification-before-completion`。
  - “排查问题” = `superpowers:systematic-debugging`。
  - 用户明确指定技能名时，按指定技能执行；纯文档、注释或文案微调可直接修改并验证。

## 设计原则

- **离线优先**：系统只消费上传的数据包，不连接被检系统、不进行在线采集；被检系统的对接只体现在收集包内容的格式适配。
- **模式同构**：在线模式与本地开发模式共享同一套巡检器注册机制与规则库；在线模式是本地模式的编排、持久化与多人协作扩展，CLI 与 API 必须产出相同的巡检结果。
- **契约驱动**：后端与 Web 通过 OpenAPI 契约交付，契约先行、双向一致，便于前端多形态（Web/CLI/移动端等）扩展。
- **增量重跑**：巡检结果按规则粒度落盘与更新，支持单条规则单独重跑；Web 刷新即可查看最新效果，无需全量重跑。
- **规则编排**：优先级显式声明、依赖由「消费的中间产物」自动推导（消费即依赖），DAG 化执行；单规则重跑时依赖链自动补跑，中间产物显式传递，避免重复解析。
- **先过滤后分析**：大体积数据（如日志）先裁剪出中间产物，再执行各分析规则；单条规则调试只处理过滤后数据，保证快速迭代。
- **任务/客户隔离**：一个数据包 = 一个任务 = 一个系统，按 `system_id` 隔离数据与结果；在线一次一包创建任务、离线目录顺序分析，支持单任务重跑，互不影响。
- **幂等与可重复**：同一数据包可重复巡检，结果一致；解压按类规划、子包去重只解压一次；任务与结果入库留痕。
- **可追溯**：每条巡检结论记录来源文件、规则、触发值与阈值；告警类结论必须可定位到原始数据。
- **存储扁平化、少定制**：契约化数据按「任务 → 系统 → 规则」平铺为 JSON 文档，目录/文档即层级，不为单个规则定制存储结构；新增规则只新增 `code`/`metric.key`，不新增表与定制字段。
- **轻量存储、少安装**：默认 SQLite + 文件存储，无外部数据库/消息中间件依赖，开箱即用；重组件仅按需选配，选配切换不影响契约与规则代码。
- **从简优先**：首版以单机、单线程、轻量实现为目标，优先保证正确性与架构稳定；性能优化（并发、缓存、分布式）在功能稳定后按需进行。
- **简约而不简单**：前端视觉简约克制——留白、语义色（pass/warn/fail/error/skip）、信息密度适中，功能完整但不花哨，不做无意义动效。
- **容错**：单个文件解析失败不影响整个任务，以“解析失败”规则结果记录。
- **可扩展**：文件类型识别器与巡检器均采用注册机制，新增数据格式与规则不修改核心流程。
