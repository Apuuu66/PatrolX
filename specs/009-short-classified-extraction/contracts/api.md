# API 契约增量：任务准备状态与删除失败

本文件是计划阶段契约设计。实现前必须先把以下变更同步到唯一契约源 `docs/api/openapi.yaml`，再更新 Pydantic、测试和生成客户端。

## 1. 任务响应扩展

影响接口：

- `GET /api/v2/tasks`
- `GET /api/v2/tasks/{task_id}`

### `InspectionTaskV2`

新增可选属性：

```yaml
preparation:
  nullable: true
  allOf:
    - $ref: '#/components/schemas/DataPreparationV2'
```

`TaskSummaryV2` 继承后自动获得该字段。

### `PreparationStatusV2`

```yaml
type: string
enum:
  - pass
  - warn
  - fail
  - skip
  - error
```

### `PreparationIssueTypeV2`

```yaml
type: string
enum:
  - conflict
  - duplicate
  - skipped
  - failed
  - rejected
```

### `PreparationIssueV2`

```yaml
type: object
required: [type, reason]
properties:
  type:
    $ref: '#/components/schemas/PreparationIssueTypeV2'
  source:
    type: string
    nullable: true
  target:
    type: string
    nullable: true
  reason:
    type: string
  path_length:
    type: integer
    nullable: true
  path_limit:
    type: integer
    nullable: true
```

### `PreparationItemV2`

```yaml
type: object
required:
  - code
  - name
  - category
  - status
  - summary
  - extracted_count
  - total_count
  - issues
properties:
  code:
    type: string
    example: pkg.extract.kpi
  name:
    type: string
    example: KPI 分类解压
  category:
    type: string
    example: kpi
  status:
    $ref: '#/components/schemas/PreparationStatusV2'
  summary:
    type: string
  duration_ms:
    type: integer
    nullable: true
  extracted_count:
    type: integer
  total_count:
    type: integer
  issues:
    type: array
    items:
      $ref: '#/components/schemas/PreparationIssueV2'
```

### `DataPreparationV2`

```yaml
type: object
required:
  - status
  - items
  - total
  - success_count
  - warning_count
  - failure_count
  - skip_count
properties:
  status:
    $ref: '#/components/schemas/PreparationStatusV2'
  items:
    type: array
    items:
      $ref: '#/components/schemas/PreparationItemV2'
  total:
    type: integer
  success_count:
    type: integer
  warning_count:
    type: integer
  failure_count:
    type: integer
  skip_count:
    type: integer
```

## 2. 删除失败错误

`DELETE /api/v2/tasks/{task_id}` 保留既有响应：

- `204`：删除成功。
- `404`：任务不存在。
- `409`：任务正在排队或执行。

新增 `500`：

```json
{
  "code": "task_delete_failed",
  "message": "任务删除失败：目录不为空或路径过长",
  "detail": {
    "task_id": "task-kpi_long_path_20260901",
    "locations": [
      "output/task-kpi_long_path_20260901",
      "uploads/task-kpi_long_path_20260901"
    ],
    "failed_path": "output/task-kpi_long_path_20260901/kpi/very-long-name.csv",
    "path_length": 279,
    "path_limit": 260
  }
}
```

`path_length` 和 `path_limit` 只在路径过长或可可靠计算时返回；其他 `OSError` 必须返回可读原因和现场位置。

## 3. 兼容性

- 新增字段全部可选，不改变既有字段语义。
- 不修改 `TaskStatusV2`、`TaskStatsV2`、`RuleResultV2`。
- 不修改 `task_id` 生成和返回语义。
- 前端必须重新执行 `python build.py contract` 和 `python build.py gen-web-api`。
