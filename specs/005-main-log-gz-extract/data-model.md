# 数据模型：解压现场与展开状态

## 1. 任务现场

### MainEvidenceSite

主包原始解压证据现场。

| 字段 | 类型 | 说明 | 约束 |
| --- | --- | --- | --- |
| path | path | `.main/` 任务内路径 | 固定为 `output/<task_id>/.main/` |
| package_checksum | string | 上传包 checksum | 判断是否复用或重建 |
| original_paths | path[] | 上传包内文件在 `.main/` 中的相对路径 | 与上传包内部结构一致 |
| retained | boolean | 是否保留 | 任务生命周期内必须为 true |

约束：

- 不被普通规则作为数据源。
- 不被解压、分类、prepare 或 inspect 阶段删除。
- 只有用户显式删除任务时随任务目录级联清理。

### CategoryWorkSite

分类后的规则输入现场。

| 字段 | 类型 | 说明 | 约束 |
| --- | --- | --- | --- |
| category | enum | `logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other` | 与现有分类目录一致 |
| path | path | `output/<task_id>/<category>/` | 每个任务一份 |
| files | path[] | 可被普通规则匹配的最终文件 | 不包含原始或中间压缩包 |
| source_relative_path | path | 文件在原始结构中的来源路径 | 记录在展开状态或 manifest 中 |

约束：

- `logs/` 中只保留最终解压结果，不保留日志子压缩包或 `.log.gz`。
- 普通规则只读取分类工作现场。

## 2. 解压状态

### SubpackageState

一个子压缩包的展开状态。

| 字段 | 类型 | 说明 | 约束 |
| --- | --- | --- | --- |
| source | path/reference | 原始子包在证据现场或原始父包中的位置 | 必填 |
| parent | reference \| null | 父压缩包或父证据路径 | 顶层子包为 null |
| category | enum | 业务分类 | 允许与父分类不同 |
| classification_reason | string | 自身特征分类、继承父级或未识别 | 必填 |
| depth | integer | 相对主包的嵌套层级 | 从 1 开始，不得超过安全预算 |
| checksum | string | 子包 checksum | 用于去重 |
| target | path | 分类工作现场目标目录 | 必须位于任务目录内 |
| status | enum | `extracted`、`duplicate`、`failed`、`rejected` | 必填 |
| error | string \| null | 失败或拒绝原因 | 非成功状态必填 |

状态迁移：

```text
registered → extracted
registered → duplicate
registered → failed
registered → rejected
```

约束：

- 相同 checksum 的子包只展开一次。
- `failed` 与 `rejected` 不阻断其他子包。
- 成功状态对应的分类工作现场不保留原始压缩包。

### LogGzipState

一个 `.log.gz` 的展开状态。

| 字段 | 类型 | 说明 | 约束 |
| --- | --- | --- | --- |
| source_evidence | path/reference | 原始 `.log.gz` 的证据位置 | 可指向 `.main/` 内原始文件或原始父包成员 |
| source_relative_path | path | 在日志结构中的相对路径 | 保留服务、节点等层级 |
| target | path | `logs/` 中同名 `.log` 文件 | 必须同目录、同基础文件名 |
| status | enum | `extracted`、`conflict`、`failed`、`rejected` | 必填 |
| error | string \| null | 失败、冲突或拒绝原因 | 非成功状态必填 |

状态迁移：

```text
registered → extracted
registered → conflict
registered → failed
registered → rejected
```

约束：

- `extracted` 状态不得再让普通规则读取对应 `.log.gz`。
- `conflict` 不得覆盖已有 `.log`。
- `failed`、`conflict`、`rejected` 不中断任务。
- `logs/` 成功处理完成后不保留 `.log.gz`。

## 3. 解压 manifest

文件：`output/<task_id>/.patrolx-extracted.json`

### 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| version | integer | manifest 结构版本，本功能使用 `3` |
| main | object | 主包证据现场状态 |
| subpackages | SubpackageState[] | 子压缩包展开状态 |
| log_gz | LogGzipState[] | `.log.gz` 展开状态 |
| rejected | object[] | 因安全预算或不支持格式拒绝的项 |

### MainState

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| checksum | string | 上传包 checksum |
| count | integer | 主包内登记的原始文件数量 |
| evidence_path | path | 固定为 `.main` |
| reused | boolean | 本次执行是否复用既有现场 |

### 兼容策略

- 旧 manifest 只包含 `main` 和 `subpackages` 时，系统应视为旧版本并触发安全重建。
- 旧字段不作为新版递归状态的信任依据。
- 新字段只影响内部解压阶段，不改变任务 API 返回结构。

## 4. 一致性规则

1. 上传包 checksum 变化时，必须重建 `.main/` 和分类工作现场。
2. manifest 声明 `extracted` 的 `.log.gz`，在 `logs/` 中不得作为规则输入重复消费。
3. manifest 声明 `failed` 或 `conflict` 的项必须包含可读原因。
4. 所有路径必须位于当前任务目录内；禁止路径穿越和链接逃逸。
5. 安全预算拒绝必须同时出现在 `rejected` 或对应状态中，并写入执行日志。
