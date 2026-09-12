# CLI 契约：系统基线

CLI 是规则开发和离线验证的本地模式入口。

## 命令

| 命令 | 用途 | 基线结果 |
| --- | --- | --- |
| `make verify` | 通过 `main.py` 运行完整本地流水线 | 扫描包输入、创建/隔离任务、运行规则、写入结果/日志/报告。 |
| `make verify-one RULE=<rule_code>` | 重跑一条目标规则 | 刷新目标结果并确保过时/缺失依赖被处理。 |
| `make verify-one RULE=<rule_code> SYSTEM=<system_id>` | 为一个系统重跑一条规则 | 将重跑限定到指定的系统上下文。 |
| `make contract` | 从实现模型导出/验证 OpenAPI | 实现与契约不一致时失败。 |
| `make test` | 运行后端测试 | 验证规则、执行器、归档安全、API、Schema 和一致性。 |
| `make lint` | 运行 Ruff check/format 验证 | 强制代码风格和静态检查。 |

## 环境输入

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `PACKAGE_DIR` | 替代离线包输入目录 | `uploads/` 根目录 |
| `PATROLX_PACKAGE_DIR` | 规则文件直接运行的包来源 | 无包可用时回退到样例 fixture |

## 本地模式不变量

1. 离线模式不需要数据库设置。
2. 放置在配置输入目录根部的包被发现并顺序处理。
3. 每个包产生一个任务和一个系统巡检。
4. 本地输出结构与在线契约结构匹配。
5. 规则结果按规则写入，使单独重跑可以原地更新。
6. 缺失类别或依赖在适当情况下产生 `skip` 并附带可见原因。
7. 任何命令不得连接被检系统。

## 预期本地输出

```text
uploads/<task_id>/<package>              # 保留的原始包
output/<task_id>/<system_id>/            # 按类别组织的包内容
output/<task_id>/<system_id>/artifacts/  # 中间准备数据
output/<task_id>/<system_id>/rules/      # 每条规则的契约 JSON
output/<task_id>/report.html             # 可读报告
output/<task_id>/execution.log           # 结构化任务执行日志
```
