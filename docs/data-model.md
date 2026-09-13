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

## 7. Source Patterns

规则不消费中间产物契约，也不依赖其他规则实现。

- `source_patterns[]` 是匹配 `output/<task_id>/` 内相对路径的正则。
- 执行器把匹配到的相对路径交给规则。
- 物理日志目录是 `logs/`，规则类别仍然是 `log`。
- 无匹配文件、格式不适用或解析失败时必须返回 `skip` 和非空原因。

## 8. 文件组织

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

## 9. 示例

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

## 10. 扩展规则

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
