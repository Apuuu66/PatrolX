# 数据模型：任务重建重跑

## RebuildMode

枚举：

- `full`：全量重建重跑。
- `incremental`：增量重建重跑。

## RebuildRequest

| 字段 | 类型 | 约束 | 语义 |
| --- | --- | --- | --- |
| `mode` | `full` / `incremental` | 必填 | 重建范围 |
| `confirmed` | boolean | 必填且为 `true` | 用户确认破坏性重建 |
| `rule_codes` | string[] | 增量必填、去重、非空 | 目标普通规则 |
| `trigger_source` | `ui` / `api` | 默认 `ui` | 记录触发来源 |

全量请求的 `rule_codes` 必须为空或不填。

## 任务现场

路径保持：

```text
uploads/<task_id>/<package_file>
output/<task_id>/
├── task.json
├── system.json
├── rules/<rule_code>.json
├── report.html
├── execution.log
├── kpi/kpi_catalog_snapshot.json
├── prepared/<owner_code>/
└── 解压分类目录 / manifest
```

### 全量重建

- `output/<task_id>` 被删除后重建。
- KPI 快照由当前基础数据和分类数据库重新生成。
- 全部普通规则结果重新生成。
- 原始上传包字节不变。

### 增量重建

- 保留 `task.json` 中原任务标识、创建时间、客户元数据。
- 保留未选择规则结果、既有 KPI 快照和 `prepared/<owner_code>/`。
- 删除并重建解压 manifest 与工作分类目录。
- 只覆盖目标规则结果、汇总和报告。
- 原始上传包字节不变。

## 执行日志

`LogEntry.detail` 增加或复用结构化字段：

- `operation: rebuild`
- `mode: full | incremental`
- `rule_codes: string[]`
- `trigger_source: ui | api`

日志消息必须能区分重建重跑与普通重跑。
