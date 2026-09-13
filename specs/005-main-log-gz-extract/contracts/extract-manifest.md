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

`status` 允许值：

| 值 | 含义 |
| --- | --- |
| `extracted` | 已成功展开到分类工作现场 |
| `duplicate` | checksum 重复，已复用既有展开结果 |
| `failed` | 解压失败；不阻断任务 |
| `rejected` | 因安全预算、路径风险或不支持格式拒绝 |

## LogGzipState

```json
{
  "source_evidence": ".main/path/to/ServiceLog.zip#/AppService/logs/node/app.log.gz",
  "source_relative_path": "logs/ServiceLog_20260901011314/AppService/logs/node/app.log.gz",
  "target": "logs/ServiceLog_20260901011314/AppService/logs/node/app.log",
  "status": "extracted",
  "error": null
}
```

`status` 允许值：

| 值 | 含义 |
| --- | --- |
| `extracted` | 已生成 `logs/` 中的 `.log`，`.log.gz` 不保留在工作现场 |
| `conflict` | 目标 `.log` 已存在，未覆盖 |
| `failed` | 解压失败；不阻断任务 |
| `rejected` | 因安全预算或路径风险拒绝 |

## 状态一致性

1. `main.checksum` 与 `uploads/<task_id>/` 中原始上传包一致时才可复用现场。
2. `subpackages[].target`、`log_gz[].target` 必须位于当前任务目录内。
3. `status != extracted` 时 `error` 或 `reason` 必须非空；`duplicate` 可以使用机器可读原因。
4. `log_gz[].status == extracted` 时，规则文件匹配必须排除 `source_relative_path`。
5. `logs/` 最终不应存在 `*.zip`、`*.tar.gz`、`*.tgz`、`*.tar` 或已成功展开的 `*.log.gz`。
