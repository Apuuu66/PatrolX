# Manifest 策略契约

本契约只约束任务内部解压审计文件 `.patrolx-extracted.json` 的扩展，不修改 OpenAPI 或 `RuleResult` 公共契约。

## 版本与兼容

- manifest 版本保持 `3`。
- `policy` 节是可选节点；旧 manifest 没有该节点时仍可复用。
- 新写入的 manifest 必须包含 `policy` 节。
- `skipped` 是策略有意保留状态，不是失败或拒绝。

## policy 节

```text
policy:
  fingerprint: string
  skip_all: boolean
  skip_paths: string[]
  whitelist_paths: string[]
  whitelist_keywords: string[]
  counters:
    skipped_subpackages: integer
    skipped_log_gz: integer
    whitelisted_subpackages: integer
    whitelisted_log_gz: integer
    whitelisted_files: integer
```

`fingerprint` 对归一化后的策略字段计算，不包含配置文件注释和无关空白。

`skipped_*` 计数只统计成功保留的压缩项或 gzip 文件；复制失败、目标冲突或预算拒绝不计入。

## subpackages 条目

既有字段不变。`status` 扩展：

| 状态 | 含义 | `target` | `error` |
| --- | --- | --- | --- |
| `extracted` | 正常解压 | 必填 | null |
| `duplicate` | checksum 去重 | 可复用既有字段 | 既有说明 |
| `skipped` | 按策略成功保留 | 必填 | null |
| `failed` | 局部解压失败 | 既有语义 | 必填 |
| `rejected` | 安全或格式拒绝 | 既有语义 | 必填 |

复制失败、目标冲突或预算拒绝不得记录为 `skipped`；必须按既有 `failed` 或 `rejected` 语义记录，并包含错误信息。

新增可选 `policy` 字段：

```text
policy:
  action: skip | whitelist
  reason: global_retain | skip_path | whitelist_path | whitelist_keyword
  scope: string | null
  keyword: string | null
```

## log_gz 条目

既有字段不变。`status` 扩展 `skipped`。被跳过的 `.log.gz` 必须成功保留在 `logs/` 现场中并填写目标路径，不生成同名 `.log` 文件；复制失败或目标冲突必须按既有失败语义记录。`policy` 字段语义与 `subpackages` 一致。

## 普通文件白名单

普通文件不逐项进入 manifest。结构化日志事件至少包含：

```text
event = extract.policy.whitelist
task_id = string
source = task-relative source path
target = task-relative category path
reason = whitelist_path | whitelist_keyword
scope = string | null
keyword = string | null
```

## 查询语义

- `category_failures()` 继续只返回 `failed` / `rejected` / `conflict`，不得把 `skipped` 当作失败。
- 新增策略查询只返回同 category 的 `skipped` 压缩项或 `.log.gz` 摘要，用于无匹配规则时补充 `skip_reason`。
- 查询不得暴露 `.main/` 以外的新越界路径，也不得引导规则读取 manifest 内部数据。
