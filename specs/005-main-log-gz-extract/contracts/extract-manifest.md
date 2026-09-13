# 内部契约：解压 manifest v3

本契约只约束 PatrolX 任务输出目录内的解压状态文件，不修改 HTTP API。

## 文件

```text
output/<task_id>/.patrolx-extracted.json
```

## 顶层结构

```json
{
  "version": 3,
  "main": {
    "checksum": "sha256",
    "count": 0,
    "evidence_path": ".main",
    "reused": false
  },
  "subpackages": [],
  "log_gz": [],
  "rejected": []
}
```

- `version` 必须是 `3`；旧版本、损坏或缺字段时不信任，整体重建现场。
- `main.count` 是主包内登记的原始文件数。
- `main.reused` 表示本次执行是否复用既有现场；整体重建后必须为 `false`。

## SubpackageState

```json
{
  "source": ".main/path/to/ServiceLog.zip",
  "parent": null,
  "category": "logs",
  "classification_reason": "self:name",
  "depth": 1,
  "checksum": "sha256",
  "target": "logs/ServiceLog_20260901011314",
  "status": "extracted",
  "error": null
}
```

`category` 使用实际工作目录名：`logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other`。

`status` 允许值：

| 值 | 含义 |
| --- | --- |
| `extracted` | 已成功展开到分类工作现场 |
| `duplicate` | checksum 重复，已复用既有展开结果 |
| `failed` | 解压失败；不阻断任务 |
| `rejected` | 因安全预算、路径风险或不支持格式拒绝 |

原始子压缩包在 `.main/` 内永久保留。分类工作现场中的中间子压缩包在成功展开后移除。

## LogGzipState

```json
{
  "source_evidence": ".main/path/to/ServiceLog.zip#/AppService/logs/node/app.log.gz",
  "source_relative_path": "logs/ServiceLog_20260901011314/AppService/logs/node/app.log.gz",
  "target": "logs/ServiceLog_20260901011314/AppService/logs/node/app.log",
  "depth": 1,
  "status": "extracted",
  "error": null
}
```

`source_evidence` 可以指向 `.main/` 内原始文件或原始父压缩包成员；`source_relative_path` 和 `target` 使用任务目录内相对路径。

`status` 允许值：

| 值 | 含义 |
| --- | --- |
| `extracted` | 已生成 `logs/` 中的 `.log`，工作现场的 `.log.gz` 不保留 |
| `conflict` | 目标 `.log` 已存在，未覆盖；`.log.gz` 保留在工作现场 |
| `failed` | 解压失败；`.log.gz` 保留在工作现场，不生成半成品 `.log` |
| `rejected` | 因安全预算或路径风险拒绝 |

原始 `.log.gz` 在 `.main/` 内永久保留。

## RejectedState

```json
{
  "source": "config/version.ini",
  "category": "config",
  "reason": "任务累计文件数超限",
  "depth": 1
}
```

预算、目标冲突、路径风险或不支持格式可写入 `rejected`；同一项也可同时保留在 `subpackages` 或 `log_gz` 的对应状态中。

## 状态一致性

1. `main.checksum` 与 `uploads/<task_id>/` 中原始上传包一致且 manifest 结构有效时才可复用现场。
2. `subpackages[].target`、`log_gz[].target` 必须位于当前任务目录内。
3. `status != extracted` 时 `error` 或 `reason` 必须非空；`duplicate` 可以使用机器可读原因。
4. `log_gz[].status == extracted` 时，规则文件匹配必须排除 `source_relative_path`。
5. `logs/` 最终不应存在 `*.zip`、`*.tar.gz`、`*.tgz`、`*.tar` 或已成功展开的 `*.log.gz`。
6. 任务生命周期内不得删除 `.main/`；普通规则匹配入口必须排除 `.main/` 和 manifest。
