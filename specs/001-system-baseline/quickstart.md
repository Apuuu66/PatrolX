# 快速开始：系统基线验证

本指南在不约束实现变更的前提下验证基线业务流程。

## 前置条件

- 仓库检出。
- 仓库工具链准备的 Python 环境。
- 前端构建或 Web 审查所需的 Node.js/npm。
- 至少一个受支持的样例包。

仓库样例 fixture 位于：

```text
tests/fixtures/sample/sample.zip
```

真实格式验证时，使用脱敏的内部包并对照
[`docs/example/real-package-structure.md`](../../docs/example/real-package-structure.md) 比较其结构。

## 1. 验证环境

```bash
make lint
make test
make contract
```

预期：

- Ruff check/format 通过。
- 所有后端测试通过。
- OpenAPI 契约与实现一致。

## 2. 运行离线基线流程

将一个受支持的包放入默认离线输入区域：

```bash
cp /path/to/package.zip uploads/
make verify
```

或者指定其他包目录：

```bash
PACKAGE_DIR=/path/to/packages make verify
```

预期：

1. 该包被识别为一个任务。
2. 恰好产生一个系统巡检上下文。
3. 包内容被安全分类和解压。
4. 适用规则执行。
5. 创建规则 JSON 结果、执行日志和 HTML 报告。
6. 无适用数据的类别以原因跳过。

## 3. 检查结果

检查任务输出布局：

```bash
find output/<task_id> -maxdepth 3 -type f | sort
```

确认：

- 原始包保留在 `uploads/` 下。
- 规则结果存在于 `output/<task_id>/rules/` 下。
- 执行日志存在于 `output/<task_id>/execution.log`。
- 报告存在于 `output/<task_id>/report.html`。

打开报告并验证其展示：

- 整体状态计数。
- 规则结果。
- 含来源/证据的发现。
- 建议。
- 适用时的跳过原因。

## 4. 验证单任务隔离

向输入目录添加第二个不同名称的受支持包并运行：

```bash
make verify
```

预期：

- 创建第二个任务。
- 每个任务有自己的任务输出目录。
- 一个任务的结果、发现、日志和报告不与另一个合并。

## 5. 验证规则重跑

从已有任务输出中选择一个规则代码：

```bash
make verify-one RULE=<rule_code>
```

预期：

- 请求的规则结果被刷新。
- 规则按其 `source_patterns` 重新匹配任务目录内文件。
- 无匹配文件时产生带原因的 `skip`。
- 无关规则结果文件保持可用。

## 6. 验证本地/在线语义

启动在线服务：

```bash
python run_online.py
```

然后通过 Web UI 上传同一受支持的包并与本地运行比较。

预期：

- 任务/系统/规则/发现结构具有相同业务含义。
- 同一包名生成相同 `task_id` 和相同任务目录布局。
- 同一包的规则结果一致（执行标识和时间除外）。
- 报告和规则详情在浏览器中保持可审查。

## 7. 验证删除

通过在线任务流程或等效 API 操作删除一个已完成任务。

预期：

- `uploads/<task_id>/` 下的任务输入被移除。
- `output/<task_id>/` 下的任务输出被移除。
- 无残留的部分任务。

## 8. 故障处理检查

使用包含格式错误/不可识别内容的 fixture 或临时副本。

预期：

- 处理可继续时，格式错误的文件不中止整个任务。
- 问题在规则结果或结构化执行日志中可见。
- 不受影响的类别和规则仍产生结果。
- 不支持/无数据的类别以原因跳过。
