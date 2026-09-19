# PatrolX 契约数据模型

本文档说明巡检输出的四层契约结构和持久化文件组织。机器可读契约以
[`docs/api/openapi.yaml`](api/openapi.yaml) 为准。

## 1. 层级结构

```text
InspectionTask
└── SystemInspection
    └── RuleResult
        ├── Metric
        └── Finding[]
```

| 层级 | 模型 | 说明 |
| --- | --- | --- |
| 任务 | `InspectionTask` | 一次巡检执行，对应一个压缩包 |
| 系统 | `SystemInspection` | 一个包的完整巡检上下文 |
| 规则 | `RuleResult` | 一条规则的结果、指标和发现 |
| 发现 | `Finding` | 具体问题点，含证据、影响和建议 |

## 2. InspectionTask

核心字段：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 任务 ID |
| `name` | 任务名 |
| `mode` | `local` / `online` |
| `status` | `pending` / `running` / `completed` / `failed` |
| `trigger` | `api` / `cli` / `rerun` |
| `created_at` | 创建时间，UTC |
| `completed_at` | 完成时间，UTC |
| `stats` | 跨系统状态汇总 |
| `system` | 单系统巡检结果；当前模型为 1:1 |

状态机：

```text
pending → running → completed
                 ↘ failed
```

`InspectionTask.stats.systems` 表示系统数量。单系统任务下，其余状态统计与系统
`summary` 一致。

## 3. SystemInspection

核心字段：

| 字段 | 说明 |
| --- | --- |
| `package_file` | 原始包文件名 |
| `package_checksum` | 原始包校验和 |
| `version` | 可选版本信息 |
| `status` | `completed` / `failed` |
| `summary` | 规则状态统计 |
| `rules[]` | 规则结果列表 |
| `customer{}` | 可选省份/运营商/产品形态等扩展字典 |

统计口径：

```text
summary.total = pass + warn + fail + error + skip
```

`total` 包含 hidden 规则和 `skip` 状态规则。

## 4. RuleResult

核心字段：

| 字段 | 说明 |
| --- | --- |
| `code` | 规则 code，如 `log.error_density` |
| `name` | 展示名 |
| `category` | `log` / `kpi` / `traffic` / `alarm` / `config` / `resource` / `other` |
| `priority` | P0=0，P1=1，P2=2 |
| `execution_order` | 实际执行顺序 |
| `status` | `pass` / `warn` / `fail` / `error` / `skip` |
| `severity` | 规则严重程度 |
| `summary` | 一句话结果 |
| `skip_reason` | `status=skip` 时必填 |
| `executed_at` | 执行时间，UTC |
| `duration_ms` | 执行耗时 |
| `metrics[]` | 指标列表 |
| `findings[]` | 发现列表 |
| `metadata{}` | 规则自定义扩展数据 |

状态语义：

| 状态 | 语义 | 前端色 |
| --- | --- | --- |
| `pass` | 通过 | 绿 |
| `warn` | 告警 | 黄 |
| `fail` | 失败 | 红 |
| `error` | 执行异常 | 灰 |
| `skip` | 跳过 | 蓝 |

输出契约要求：

- `pass` / `warn` / `fail` 必须产出声明中的 metrics。
- `skip` / `error` 豁免输出契约校验。
- `skip` 必须提供原因。
- `error` 应尽量记录异常和错误码。
- 规则逻辑变化必须升级 `rule_version`。

## 5. Metric

| 字段 | 说明 |
| --- | --- |
| `key` | 契约级稳定标识 |
| `label` | 展示名 |
| `value` | 当前值 |
| `unit` | 单位 |
| `threshold{}` | 阈值，如 `max` / `min` |
| `baseline` | 基线 |
| `series[]` | 趋势数据 |

约束：

- `key` 必须稳定，跨任务、跨系统趋势聚合依赖它。
- 修改 metric 含义属于破坏性契约变更。
- 单位变化必须同步契约与展示层。

## 6. Finding

| 字段 | 说明 |
| --- | --- |
| `finding_id` | 单规则结果内唯一 |
| `title` | 问题标题 |
| `severity` | 问题严重程度 |
| `source_file` | 来源文件或包内路径 |
| `evidence` | 截断后的证据 |
| `details` | 详细说明 |
| `recommendation` | 处理建议 |
| `metrics[]` | 关联指标 |

要求：

- 必须能通过 `source_file` 和 `evidence` 追溯。
- evidence 默认截断，完整上下文保留在源文件。
- 告警、错误、资源异常等结论应尽量携带触发值或阈值。

## 7. Source Patterns 与 Prepared Data

规则不消费中间产物契约，也不依赖其他规则实现。

- `source_patterns[]` 是 Python regex，执行器对 `TaskFileCatalog` 中的 `/` 归一化相对路径执行 `re.fullmatch()`。
- 路径分隔符统一为 `/`，模式不得造成路径穿越或逃逸任务目录。
- 执行器把匹配到的相对路径交给规则；示例为 `^logs/.*\.(log|log\.gz)$`、`^kpi/.*$`。
- 物理日志目录是 `logs/`，规则类别仍然是 `log`。
- 普通规则可以声明至多一个私有 prepare；prepare 继承 owner 的 `source_patterns` 和 priority。
- prepared 数据只保存在 `output/<task_id>/prepared/<owner_code>/`，只有 owner 规则可读取，不写入规则契约，也不作为公共输入。
- 无匹配文件、格式不适用或解析失败时必须返回 `skip` 和非空原因。

## 8. TaskFileCatalog

`TaskFileCatalog` 是执行期内存清单，不属于 API、SQLite 或磁盘契约。

- 构建时机：全部 `pkg.extract.*` 到达终态后；单规则重跑先确保解压现场可复用。
- 扫描范围：`logs/`、`kpi/`、`traffic/`、`alarm/`、`config/`、`resource/`、`other/`。
- 路径形式：相对 `output/<task_id>/` 的 POSIX 路径，去重并按字典序稳定排序。
- 排除范围：`.main/`、manifest、`prepared/`、任务元数据、规则结果、报告和执行日志。
- 安全约束：拒绝符号链接、越界路径、非法正则和路径穿越。

## 9. 文件组织

```text
output/<task_id>/
├── task.json
├── system.json
├── logs/
├── kpi/
├── traffic/
├── alarm/
├── config/
├── resource/
├── other/
├── rules/<rule_code>.json
├── report.html
├── execution.log
└── .patrolx-extracted.json
```

规则结果文件：

```text
output/<task_id>/rules/<code>.json
```

支持单规则重跑后原地更新。

规则私有 prepared 数据目录：

```text
output/<task_id>/prepared/<owner_code>/
```

该目录属于内部运行时数据，不进入公共 API 契约。

## 10. 示例

```json
{
  "task_id": "task-20260909-001",
  "status": "completed",
  "stats": {
    "systems": 1,
    "pass": 8,
    "warn": 2,
    "fail": 1,
    "error": 0,
    "skip": 1
  },
  "system": {
    "package_file": "customer_a.tar.gz",
    "version": "R12",
    "status": "completed",
    "summary": {
      "total": 12,
      "pass": 8,
      "warn": 2,
      "fail": 1,
      "error": 0,
      "skip": 1
    },
    "rules": [
      {
        "code": "log.error_density",
        "name": "日志错误密度",
        "category": "log",
        "priority": 1,
        "execution_order": 3,
        "status": "warn",
        "severity": "medium",
        "summary": "错误日志密度超限",
        "metrics": [
          {
            "key": "error_count",
            "label": "错误条数",
            "value": 152,
            "unit": "条",
            "threshold": {"max": 100}
          }
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

## 11. KPI Catalog

PatrolX 将 KPI 数据拆为权威基础数据、分类状态和任务快照三层。

### 拆分配置

路径：`deploy/data/kpi/`。

```text
base/metrics.json
base/units.json
```

`base/metrics.json` 保存完整基础指标快照；`base/units.json` 只保存 `UNIT_*` 预留单位。
两个基础资源文件要求 UTF-8、LF、严格 JSON 和 `schema_version: 1`；加载器不回退旧
`deploy/data/kpi_catalog.json`。指标规则、公式、阈值、容量规则、展示规则和公共配置保存在 SQLite，
`deploy/data/kpi/rules/*.json` 不再被运行时读取，仅可作为过渡期备份。

约束：

- `metrics[].resource_id` 必须以 `ME_` 开头；`units[].resource_id` 必须以 `UNIT_` 开头。
- 稳定 key 是资源 ID 的小写形式；`resource_id` 和 `key` 全局唯一。
- `metrics[].unit_key` 当前必须是 `null`；单位解析是预留能力，不进入运行时。
- SQLite 动态口径只能引用 `metrics` 中存在的 key，派生公式不得循环。
- 资源 CSV 离线导入是基础资源完整替换；被移除指标仍被 SQLite 动态配置引用时导入失败，两个基础文件都不替换。
- 文件不做业务域分类；分类状态只在数据库中维护。
### DB 分类模型

| 表 | 说明 |
| --- | --- |
| `kpi_classifications` | `metric_key` 主键；`domain` 为空表示未分类；保存 UTC 创建/更新时间。 |
| `kpi_classification_revisions` | 单行修订表；每次批量原子提交递增 `classification_version`。 |
| `kpi_classification_audits` | 保存 `metric_key`、操作、操作人、前后域、结果和 UTC 操作时间。 |

分类只改变业务域，不改变拆分配置文件。被公式、阈值或容量规则引用的指标受引用保护；批量分类任一指标失败时整批回滚。

### 任务快照

路径：`output/<task_id>/kpi/kpi_catalog_snapshot.json`。

```json
{
  "schema_version": 2,
  "base_data_version": "sha256:...",
  "classification_version": 1,
  "rule_config_version": 3,
  "captured_at": "2026-09-19T00:00:00Z",
  "base_metrics": [],
  "metrics": [],
  "rules": {}
}
```

快照在主包解压完成后生成，之后不可变。普通 KPI 规则只读取快照；单规则重跑优先复用。快照缺失时从基础资源 + SQLite 原子重建，损坏或当前配置校验失败时抛出错误并让任务失败。

全量重建会删除旧快照并按当前基础资源、分类和动态口径生成新快照；增量重建在预检时要求既有快照可解析，重建解压现场后原样保留快照。

### 动态口径配置

SQLite 保存分类之外的 KPI 动态配置：指标规则与受控 ratio 公式、阈值（默认值和 5/15/30/60 分钟周期）、容量规则、展示规则、公共配置、配置修订和配置审计。每次原子保存或删除会记录审计并递增 `rule_config_version`。分类线索只读展示，不改变规则状态；配置或分类变更后必须手动重跑受影响的 KPI 规则。

## 11. 扩展规则

新增能力时：

- 新增规则使用新 `code`。
- 新增指标使用新 `metric.key`。
- 规则私有结构放入 `metadata{}`。
- 不修改既有字段语义。
- 新类别必须同步：
  - Pydantic 模型。
  - OpenAPI 契约。
  - 前端生成客户端。
  - 分类规则表。
  - 目录处理逻辑。
  - 测试样例。
