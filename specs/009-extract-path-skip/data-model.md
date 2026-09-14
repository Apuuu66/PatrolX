# 数据模型：压缩项解压跳过与白名单策略

## 1. ExtractPolicyConfig

项目级解压策略配置，来自 `deploy/config/extract_policy.yaml`。

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `version` | integer | 是 | 固定 `1` | 配置契约版本。 |
| `nested.skip_all` | boolean | 否 | 默认 `false` | 全局保留主包内所有非白名单嵌套压缩项。 |
| `nested.skip_paths` | array[string] | 否 | 默认 `[]` | 目录前缀跳过作用域。 |
| `whitelist.paths` | array[string] | 否 | 默认 `[]` | 目录前缀白名单作用域。 |
| `whitelist.name_keywords` | array[string] | 否 | 默认 `[]` | 名称关键字白名单。 |

### 校验规则

- 文件缺失或为空时使用默认配置，行为与 007 兼容。
- 顶层未知键拒绝；`version` 不是 `1` 拒绝。
- 路径必须可归一化为任务内相对目录前缀。
- `/0/`、`/xx/0/` 分别归一化为 `0/`、`xx/0/`。
- 空串、`/`、`.`、`..`、越界路径、空段非法。
- 名称关键字必须是非空字符串；匹配时使用大小写无关子串。
- 交付配置必须包含初始关键字 `alarm`。
- 配置加载失败时任务不得以默认策略静默继续。
- 配置是部署侧静态项目级文件；不提供在线修改接口、任务级覆盖、配置中心或热更新契约。

## 2. ExtractionPolicyDecision

单个压缩项在 `EXTRACT` 阶段的策略决策。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `action` | enum | `normal`、`skip`、`whitelist`。 |
| `reason` | string | 稳定的机器可读原因，如 `global_retain`、`skip_path`、`whitelist_path`、`whitelist_keyword`。 |
| `scope` | string / null | 命中的路径作用域；名称关键字命中时为 null。 |
| `keyword` | string / null | 名称关键字命中时的原始配置关键字。 |

### 状态关系

```text
压缩项入口
  → whitelist 命中 → normal extract
  → 非白名单且 skip_all 命中 → skipped
  → 非白名单且 skip_paths 命中 → skipped
  → 其他 → normal extract
```

主包本身不进入该状态机，始终执行主包解压。

## 3. Manifest policy 节

`.patrolx-extracted.json` 新增可选 `policy` 节。旧 manifest 没有该节点时仍有效。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `fingerprint` | string | 归一化策略字段的 SHA-256 摘要，用于审计识别配置内容。 |
| `skip_all` | boolean | 当次执行使用的全局保留设置。 |
| `skip_paths` | array[string] | 当次归一化后的跳过前缀。 |
| `whitelist_paths` | array[string] | 当次归一化后的白名单前缀。 |
| `whitelist_keywords` | array[string] | 当次使用的名称关键字。 |
| `counters` | object | 聚合计数，见下表。 |

### counters

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `skipped_subpackages` | integer | 按策略成功保留的嵌套压缩归档数量。 |
| `skipped_log_gz` | integer | 按策略成功保留的 `.log.gz` 数量。 |
| `whitelisted_subpackages` | integer | 白名单恢复解压的压缩归档数量。 |
| `whitelisted_log_gz` | integer | 白名单恢复解压的 `.log.gz` 数量。 |
| `whitelisted_files` | integer | 名称或路径命中白名单并正常拷贝的普通文件数量。 |

## 4. Manifest 子项扩展

### subpackages

既有字段保留。`status` 新增 `skipped`：

| 字段 | 约束 |
| --- | --- |
| `status` | `extracted`、`duplicate`、`skipped`、`failed`、`rejected` 之一。 |
| `source` | 以 `.main/` 开头的来源证据路径，或嵌套现场内相对路径。 |
| `target` | `skipped` 时必填，且必须是被保留的 category 现场文件路径。复制失败、目标冲突或预算拒绝不得使用 `skipped`，应记录为 `failed` 或 `rejected`。 |
| `policy` | 可选对象，包含 `action`、`reason`、`scope`、`keyword`。 |
| `error` | `failed` / `rejected` 必填；`skipped` 必须为 null 或省略。 |

### log_gz

既有字段保留。`status` 新增 `skipped`：

| 字段 | 约束 |
| --- | --- |
| `status` | `extracted`、`conflict`、`skipped`、`failed`、`rejected` 之一。 |
| `target` | `skipped` 时必填，且必须是被保留的 `.log.gz` 现场路径。复制失败或目标冲突不得使用 `skipped`，应记录为 `failed`、`rejected` 或既有冲突语义对应的状态。 |
| `policy` | 可选对象，包含策略决策字段。 |
| `error` | `failed` / `rejected` / `conflict` 保持既有语义；`skipped` 必须为 null 或省略。 |

### 普通文件

普通文件不逐项写入 manifest。命中白名单并正常拷贝的文件通过结构化日志事件记录，事件至少包含任务 ID、来源相对路径、目标相对路径、原因和关键字；`policy.counters.whitelisted_files` 汇总数量。

## 5. 任务工作现场

| 位置 | 内容 | 策略影响 |
| --- | --- | --- |
| `uploads/<task_id>/` | 原始上传包 | 永不修改。 |
| `output/<task_id>/.main/` | 主包原始解压现场 | 永不删除被跳过项。 |
| `output/<task_id>/<category>/` | 最终可巡检文件 | 被跳过压缩项保留为最终文件；其内部文件不出现。 |
| `output/<task_id>/.patrolx-extracted.json` | 解压审计 | 新增策略快照和逐压缩项决策。 |
| `output/<task_id>/execution.log` | 结构化执行日志 | 记录普通文件白名单命中和策略操作。 |

## 6. 与 TaskFileCatalog 的关系

- 清单仍只扫描 `logs/`、`kpi/`、`traffic/`、`alarm/`、`config/`、`resource/`、`other/` 七个 category 根。
- 非白名单且按策略成功跳过的压缩项保留在 category 根下，因此进入清单。
- 被跳过压缩项的内部内容不存在于工作现场，因此天然不进入清单。
- `.main/`、manifest、`prepared/`、规则结果和报告继续排除。
- 规则仍只能通过 `source_patterns[]` 对清单做完整匹配。
