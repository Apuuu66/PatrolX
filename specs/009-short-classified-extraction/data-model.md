# 数据模型：009 分类短路径解压与准备状态

## 1. 内部解压 manifest v4

文件：`output/<task_id>/.patrolx-extracted.json`

`version` 升级为 `4`。v3 manifest 不迁移；manifest 不匹配当前 checksum 或版本时重建现场。

### 顶层字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `version` | integer | 是 | 固定为 `4` |
| `main` | object | 是 | 主包证据现场摘要 |
| `files` | array | 是 | 普通分类文件落位记录 |
| `subpackages` | array | 是 | 子压缩包处理记录 |
| `log_gz` | array | 是 | 日志 gzip 处理记录 |
| `rejected` | array | 是 | 兼容既有拒绝汇总 |
| `policy` | object | 是 | 继承既有解压策略快照、指纹和计数器 |

### `main`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `checksum` | string | 主包 SHA-256 |
| `count` | integer | 证据现场文件数 |
| `evidence_path` | string | 固定为 `.main` |
| `reused` | boolean | 本次是否复用既有现场 |

### 通用处理项字段

以下字段适用于 `files[]`、`subpackages[]` 和 `log_gz[]` 中的记录。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source` | string | 是 | 证据现场或嵌套来源的相对路径 |
| `target` | string \| null | 是 | 分类现场内目标相对路径；拒绝较早时可为 `null` |
| `category` | string | 是 | `logs` / `kpi` / `traffic` / `alarm` / `config` / `resource` / `other` |
| `status` | string | 是 | `extracted`、`conflict`、`duplicate`、`skipped`、`failed`、`rejected` |
| `error` | string \| null | 是 | 人类可读原因 |
| `error_code` | string \| null | 否 | `path_too_long`、`target_conflict`、`duplicate`、`budget_exceeded` 等 |
| `path_length` | integer \| null | 否 | `error_code=path_too_long` 时的完整路径长度 |
| `path_limit` | integer \| null | 否 | `error_code=path_too_long` 时的上限，一般为 `260` |
| `depth` | integer | 否 | 嵌套深度 |

### 状态语义

| 状态 | 含义 | 数据准备展示 |
| --- | --- | --- |
| `extracted` | 成功落位 | `pass` |
| `conflict` | 目标已存在且未覆盖 | `warn` |
| `duplicate` | 相同 checksum 已处理 | `skip` |
| `skipped` | 解压策略显式跳过 | `skip` |
| `failed` | 处理过程中失败，半成品已清理 | `fail` |
| `rejected` | 写入前拒绝、安全规则拒绝或策略拒绝 | `fail` / `skip` |

## 2. 数据准备读取模型

### `DataPreparation`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | `pass` / `warn` / `fail` / `skip` / `error` | 是 | 汇总状态 |
| `items` | `PreparationItem[]` | 是 | 主包和各分类准备项 |
| `total` | integer | 是 | 准备项总数 |
| `success_count` | integer | 是 | `pass` 数量 |
| `warning_count` | integer | 是 | `warn` 数量 |
| `failure_count` | integer | 是 | `fail` + `error` 数量 |
| `skip_count` | integer | 是 | `skip` 数量 |

### `PreparationItem`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 是 | `pkg.extract.main` 或 `pkg.extract.<category>` |
| `name` | string | 是 | 展示名，例如“KPI 分类解压” |
| `category` | string | 是 | `main`、`logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other` |
| `status` | `pass` / `warn` / `fail` / `skip` / `error` | 是 | 准备项状态 |
| `summary` | string | 是 | 摘要说明 |
| `duration_ms` | integer \| null | 否 | 优先读取隐藏规则耗时 |
| `extracted_count` | integer | 是 | 成功数量 |
| `total_count` | integer | 是 | 应处理数量；无来源时为 `0` |
| `issues` | `PreparationIssue[]` | 是 | 默认展开展示的问题明细 |

### `PreparationIssue`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | `conflict` / `duplicate` / `skipped` / `failed` / `rejected` | 是 | 问题类型 |
| `source` | string \| null | 否 | 来源路径 |
| `target` | string \| null | 否 | 目标相对路径 |
| `reason` | string | 是 | 可读原因 |
| `path_length` | integer \| null | 否 | 完整路径长度 |
| `path_limit` | integer \| null | 否 | 路径上限 |

无匹配来源的分类准备项状态为 `skip`，`reason` 说明“未发现该分类来源”。该 `skip` 不进入普通规则摘要。

## 3. 任务契约扩展

`TaskSummaryV2` 继承 `InspectionTaskV2` 后已随任务摘要返回。新增可选字段：

```yaml
InspectionTaskV2:
  properties:
    preparation:
      nullable: true
      allOf:
        - $ref: '#/components/schemas/DataPreparationV2'
```

约束：

- 字段可选且可为 `null`，不破坏既有客户端。
- `preparation` 不参与 `TaskStatsV2`。
- `SystemInspectionV2.rules` 继续不包含 hidden 规则。
- 历史 manifest v3 任务可返回 `null` 或低精度摘要，但不得伪造明细。

## 4. 删除失败读取模型

任务实体本身不新增持久化公共字段。删除失败通过响应错误传递：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 是 | `task_delete_failed` |
| `message` | string | 是 | 可读失败原因 |
| `detail.task_id` | string | 是 | 任务标识 |
| `detail.locations` | string[] | 是 | 尝试删除的 output/uploads 现场路径 |
| `detail.failed_path` | string \| null | 否 | 操作系统报告的失败路径 |
| `detail.path_length` | integer \| null | 否 | 失败路径长度 |
| `detail.path_limit` | integer \| null | 否 | 路径上限 |

删除成功仍返回 `204`。`409 task_busy` 与 `404 not_found` 语义不变。

## 5. 身份与目录不变量

- `task_id` 继续由归档包名称派生，禁止缩短、哈希化、重命名或迁移。
- 原始上传包仍保存在 `uploads/<task_id>/`，内容不得修改。
- 主包证据现场仍是 `output/<task_id>/.main/`。
- 分类工作现场根固定为 `output/<task_id>/<category>/`。
- 本地 `local_run/` 与在线 `uploads/` 只影响主包来源，不改变共享解压和输出模型。
