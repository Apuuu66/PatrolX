# PatrolX 架构文档

本文档描述 PatrolX 的系统结构、运行模式、数据流、规则编排和运行时目录。项目长期约束见
[`.specify/memory/constitution.md`](../.specify/memory/constitution.md)；在线接口结构以
[`docs/api/openapi.yaml`](api/openapi.yaml) 为唯一契约源。

## 1. 系统定位

PatrolX 是离线巡检系统：

- 不连接被检系统，不做在线数据采集。
- 输入是预先收集好的 `zip` / `tar.gz` 数据包。
- 一个包对应一个任务和一个系统巡检上下文。
- 输出契约化巡检结果和 HTML 报告。
- 本地模式与在线模式共用同一套巡检器、规则库和结果契约。

## 2. 总体结构

```text
┌──────────────┐
│  数据包输入  │  uploads/：原始包输入现场
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 安全解压层   │───▶│ 按类落位目录   │
│ pkg.extract  │    │ logs/kpi/...   │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 规则私有准备 │───▶│ prepared/<rule>│
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 规则执行器   │───▶│ rules/*.json   │
│ P1/P2        │    │ report.html    │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐    ┌────────────────┐
│ 报告生成器   │───▶│ report.html    │
└──────┬───────┘    └────────────────┘
       │
       ▼
┌──────────────┐
│ Web / CLI    │  任务 → 系统 → 规则 → 发现
└──────────────┘
```

后端分层：

```text
api/          HTTP 路由与请求/响应边界
services/     任务、执行、报告、结果组织等业务编排
inspectors/   各领域巡检规则，直读 source_patterns 匹配文件
models/       Pydantic 契约模型与持久化模型
core/         配置、注册表、安全解压、分类等基础能力
```

约束：

- `api` 不得直接实现巡检逻辑。
- `inspectors` 不得依赖 Web 层或数据库。
- 规则之间不得互相引用实现；每条普通规则只读取自己的 source_patterns 匹配文件。

## 3. 运行模式

### 3.1 本地模式

本地模式面向规则开发和快速自验，无数据库依赖。

常用入口：

```bash
make verify                     # 等价于 python main.py，全流程
make verify-one RULE=<code>     # 单规则重跑
make test
make lint
```

默认行为：

- 扫描 `uploads/` 根目录下的压缩包。
- 多个包顺序分析，每个包一个任务。
- 任务 ID 由包名清洗生成，格式为 `task-<包名清洗后的标识>`。
- 原始包归档到 `uploads/<task_id>/`。
- 解压数据、规则结果和报告写入 `output/<task_id>/`。

### 3.2 在线模式

在线模式面向多人使用，提供 Web 界面和 API。

- 默认无认证、纯内部使用。
- 一次上传一个包，创建一个任务。
- 首版任务为单线程顺序执行。
- SQLite 只保存轻量任务/系统元数据；巡检结果和运行现场以文件为主。
- 前端通过 `/api/v2` 访问后端，API 客户端由 OpenAPI 生成。

启动：

```bash
python run_online.py
```

该入口会启动 FastAPI 后端和 Vite 前端。生产部署可使用 Docker Compose，Docker 是可选扩展。

## 4. 核心数据流

1. **输入识别**
   - 只识别任务输入目录根层的压缩包。
   - 校验压缩包格式和大小限制。
   - 原始包保留为输入现场，解压过程只读。

2. **任务识别**
   - 任务 ID 由包名清洗生成。
   - 在线可选记录省份、运营商、产品形态、版本等任务元数据。

3. **安全解压与按类落位**
   - 主包由隐藏规则 `pkg.extract.main` 处理。
   - 文件按日志、KPI、话统、告警、配置、资源、其他分类落位。
   - 嵌套包登记清单，由对应 `pkg.extract.{category}` 在 `EXTRACT` 阶段完成解压。
   - 同一子包通过 checksum/manifest 去重，只解压一次。
   - 主包解压失败时任务失败，不进入后续阶段。

4. **规则私有 prepare**
   - 全部解压准备到达终态后，才执行 `PREPARE`。
   - 普通规则可以声明至多一个私有 prepare；prepare 继承 owner 的 `source_patterns` 和优先级。
   - prepared 数据写入 `prepared/<owner_code>/`，只有 owner 规则可读取。
   - prepare 失败或无匹配输入时，owner inspect 显式 `skip`；其他规则继续。

5. **普通规则 inspect**
   - prepare 阶段完成后，P1 基础检查和 P2 综合分析按优先级顺序执行。
   - 每条普通规则只按自己的 `source_patterns` 匹配任务目录内相对路径。
   - 无匹配文件、格式不适用或解析失败时返回 `skip`，不静默通过。
   - 单规则可原地重跑，不自动补跑其他普通规则。

6. **结果与报告**
   - 规则结果写入 `rules/<rule_code>.json`。
   - 执行日志写入 `output/<task_id>/execution.log`。
   - 报告写入 `output/<task_id>/report.html`。
   - Web 只消费契约化数据，不直接理解规则内部实现。

## 5. 运行时目录

```text
uploads/
└── <task_id>/
    └── <原始压缩包>

output/
└── <task_id>/
    ├── task.json
    ├── system.json
    ├── logs/
    ├── kpi/
    ├── traffic/
    ├── alarm/
    ├── config/
    ├── resource/
    ├── other/
    ├── prepared/
    │   └── <rule_code>/
    ├── rules/
    │   └── <rule_code>.json
    ├── report.html
    ├── execution.log
    └── .patrolx-extracted.json
```

职责：

| 目录 | 职责 |
| --- | --- |
| `uploads/` | 原始包输入现场，长期保留，不修改 |
| `output/` | 处理现场，包含解压数据、结果、日志、报告 |
| `prepared/` | 规则私有中间数据，按 owner 规则隔离，不进入 API 契约 |
| `rules/` | 规则契约结果，单规则单文件，支持原地更新 |

生命周期：

- 任务和结果长期保留，不自动清理。
- 删除任务必须级联删除 `uploads/<task_id>/` 和 `output/<task_id>/`。

## 6. 包分类与解压

### 6.1 分类规则

分类优先依据文件名、目录名、扩展名和业务名称规律，规则表在：

```text
deploy/config/classify_rules.yaml
```

当前类别：

- `log`
- `kpi`
- `traffic`
- `alarm`
- `config`
- `resource`
- `other`

规则表支持通配符和中文别名，例如：

- `*log*` → 日志
- `*kpi*` → KPI
- `*alarm*` / `*告警*` → 告警
- `*config*` / `*配置*` → 配置
- `*service*` / `*日志*` → 日志

名称无法判定时，可解压后做内部文件名或内容嗅探；仍无法判定归入 `other/`。

### 6.2 嵌套包

- 嵌套包按类别解压到 `<category>/<subpackage>/`。
- 保留包内相对路径，便于 `Finding.source_file` 追溯。
- 主包解压时只登记嵌套包，不立即解压。
- `EXTRACT` 阶段执行全部需要的 `pkg.extract.{category}`，并等待所有解压准备到达终态后才进入 `PREPARE`。
- 解压清单为 `.patrolx-extracted.json`。
- 清单记录 checksum、目标目录、文件数；同 checksum 或同路径已解压时复用。

### 6.3 安全限制

所有解压必须防：

- 路径穿越。
- 符号链接攻击。
- 文件数超限。
- 单文件超限。
- 总解压体积超限。
- 嵌套深度超限。

超限或异常文件不应中断任务，应记录到解压规则结果或执行日志。

### 6.4 真实样例

真实包结构基准见：

```text
docs/example/real-package-structure.md
```

典型映射：

- `alarm_history.csv` / `alarm_summary.json` → 告警。
- `system_info.ini` / `version.ini` → 配置。
- `kpi_*.csv` → KPI。
- `pod_cpu_mem_*.txt` → 资源。
- `call_stat_*.txt` → 话统。
- `ServiceLog_*.zip` → 日志。

`ServiceLog_*.zip` 解压后按 `ServiceLog_*/<service>/logs/<node>/*.log` 组织。服务名取
`ServiceLog_*` 之后的业务目录，节点名取 `logs/` 后的目录。日志过滤必须递归读取 `.log`
和 `.log.gz`，并记录 service、node、source_file。

## 7. 规则模型与执行编排

### 7.1 优先级

| 优先级 | 职责 | 示例 |
| --- | --- | --- |
| P0 | 数据准备、解析、过滤、标准化 | `pkg.extract.*`、`log.filter` |
| P1 | 单维度阈值、统计、完整性检查 | `log.error_density`、`kpi.threshold` |
| P2 | 跨维度关联、趋势、根因分析 | `traffic.compare`、`resource.trend` |

规则执行按优先级升序分组；组内按规则编码排序。

### 7.2 依赖

规则只声明：

```text
source_patterns[]  使用 re.fullmatch() 匹配任务目录内 POSIX 相对路径的正则
outputs.metrics[]  声明的指标契约
可选 prepare       规则私有预处理声明
```

执行器维护 `EXTRACT → PREPARE → INSPECT` 阶段屏障，但不维护普通规则依赖图。普通规则只能读取自己的匹配文件或自己的 prepared 数据；`pkg.extract.*` 是隐藏解压基础设施，prepare 是隐藏规则私有准备单元，都不作为普通规则展示。

### 7.3 Rule Contract

注册规则必须声明：

- `code`
- `name`
- `category`
- `severity`
- `priority`
- `rule_version`
- `hidden`
- `description`
- `recommendation`
- `source_patterns[]`
- `outputs.metrics[]`
- 可选 `params[]`

校验要求：

- 描述和建议非空。
- metric key 与 unit 必须稳定。
- `pass` / `warn` / `fail` 必须满足输出契约。
- `skip` / `error` 豁免输出契约校验，但必须有原因或异常信息。

### 7.4 规则私有 prepare

- 一个普通规则最多声明一个 prepare；prepare 代码必须唯一。
- prepare 不声明 priority、severity、outputs 或公共 artifact。
- prepared 路径固定为 `output/<task_id>/prepared/<owner_code>/`。
- 缓存 marker 是 `.prepare.sha256`，内容为当前 owner 规则 Python 文件内容的 SHA-256。
- marker 不存在或不一致时重建；一致时复用；prepare 失败不写 marker。
- 不做输入 checksum、输出 manifest 或单个 prepared 文件缺失检查。
- prepare 执行顺序为 `owner priority → owner code → prepare code`。
- 第一版顺序执行 prepare；prepare 之间保持无依赖。

### 7.5 状态语义

| 状态 | 含义 | 展示 |
| --- | --- | --- |
| `pass` | 通过 | 绿 |
| `warn` | 告警 | 黄 |
| `fail` | 失败 | 红 |
| `error` | 执行异常 | 灰 |
| `skip` | 跳过 | 蓝，展示原因 |

`skip` 必须填写 `skip_reason`。无数据、格式不适用或解析失败时使用 `skip`，
不得静默通过或抛出任务级异常。

### 7.6 单规则重跑

- 只执行目标规则私有 prepare或复用其缓存。
- 再按目标规则 `source_patterns` 重新匹配文件并执行目标规则。
- 只重写目标规则 JSON，再重建任务摘要和 HTML 报告。
- 不自动补跑其他普通规则，不建立规则间依赖图。
- 规则逻辑变化必须升级 `rule_version`。

### 7.7 日志处理

- 日志规则递归匹配 `.log` 和 `.log.gz`。
- 物理落位目录是 `logs/`；契约类别仍然是 `log`。
- 日志规则解析文件路径时提取 service、node、source_file 等上下文。

## 8. 接口与前端

### 8.1 API 契约

OpenAPI 契约文件：

```text
docs/api/openapi.yaml
```

原则：

- 接口路径使用 `/api/v2`。
- 资源接口直接返回资源 JSON，不套壳。
- 创建/重跑类操作返回 `202 + Location`。
- 错误响应统一为 `{code, message, detail}`。
- 列表使用 `page` / `page_size` 并返回总数。
- 破坏性变更进入新版本，避免改变既有字段语义。

后端使用 Pydantic 和 FastAPI 保证契约一致；前端 API 客户端由 OpenAPI 生成：

```bash
make gen-web-api
```

禁止手写与契约不一致的调用代码。

### 8.2 页面结构

| 路由 | 页面 |
| --- | --- |
| `/` | 任务列表 |
| `/tasks/:taskId` | 任务详情 |
| `/tasks/:taskId/rules/:ruleCode` | 规则详情 |
| `/tasks/:taskId/report` | 报告预览 |
| `/tasks/:taskId/logs` | 执行日志 |
| `/inspectors` | 规则管理 |
| `/dicts` | 数据字典 |

前端原则：

- 桌面优先，不做移动端适配。
- 卡片化、留白充足、信息密度适中。
- 状态徽标使用统一语义色。
- 规则详情优先渲染指标图表；无图表结构时使用通用表格兜底。
- 发现列表展示 severity、evidence、source_file、recommendation。
- 单规则重跑后只增量刷新该规则；任务执行中可轮询刷新摘要。

## 9. 数据模型

数据模型细节见：

```text
docs/data-model.md
```

核心层级：

```text
InspectionTask
└── SystemInspection
    └── RuleResult
        ├── Metric[]
        └── Finding[]
```

持久化原则：

- 任务、系统、规则、发现使用契约 Schema 定义。
- 本地 CLI 和在线 API 返回同一套结构。
- 规则结果独立落盘，支持单规则更新。
- `metric.key` 是跨任务稳定标识，不可随意变更。

## 10. 存储策略

默认存储：

- SQLite：任务元数据和轻量状态。
- 文件：原始包、解压数据、规则结果、报告、执行日志。
- 结果文档按任务 → 规则平铺组织。

默认不引入：

- PostgreSQL
- Redis
- Kafka
- 分布式执行器
- 外部对象存储

可选演进：

- 多人/大规模场景可切换 PostgreSQL。
- 契约和业务代码不应绑定具体数据库实现。
- 性能优化在功能稳定后按需引入。

## 11. 可观测性

- 健康检查：`GET /healthz`。
- Prometheus 指标：`GET /metrics`。
- 结构化日志：structlog。
- 任务执行日志：`output/<task_id>/execution.log`。
- 日志应覆盖任务创建、解压、子包处理、分类落位、规则执行、异常和报告生成。
- 业务异常必须有统一错误码，禁止静默吞掉。

## 12. 测试与验收

最低质量门槛：

```bash
make lint
make test
```

本地流水线变更还需要：

```bash
make verify
```

契约变更：

```bash
make contract
make gen-web-api
```

关键测试类型：

- 规则单元测试：每个巡检规则必须有测试和样例数据。
- 编排测试：优先级、依赖推导、循环依赖、artifact 版本。
- 安全测试：路径穿越、链接、解压炸弹防护。
- 契约测试：Pydantic/OpenAPI 一致性。
- 双模式测试：CLI 与 API 结果一致性，除 id/时间戳外逐字段比对。
- 前端构建：`make web-build` 或等效命令。
