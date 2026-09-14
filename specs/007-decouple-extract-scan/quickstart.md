# 快速验证：解压与规则扫描解耦

日期：2026-09-14  
范围：实现完成后用于人工与自动化验证。

## 前置条件

```bash
make install
```

可选契约漂移检查（本功能默认不改契约）：

```bash
make contract
```

## 1. 自动化门禁

按顺序执行：

```bash
make lint
make test
make verify
```

预期：

- Ruff 无错误。
- pytest 全部通过。
- 本地全流程完成，生成 `task.json`、`system.json`、规则 JSON、报告和执行日志。
- `pkg.extract.main` 为 `pass`。
- 主包失败样例阻断后续阶段，其他样例不受影响。

## 2. 大主包 + 嵌套日志场景

准备包含以下内容的主包：

```text
ServiceLog_20260901011314.zip
  └── service.log.gz
kpi.csv
alarm.csv
```

执行：

```bash
make verify
```

检查：

1. `.main/` 保留原始 `ServiceLog_20260901011314.zip` 和原始 `.log.gz`。
2. `logs/` 只保留最终 `.log`；不保留已展开的 `.log.gz`。
3. `kpi/`、`alarm/` 包含对应最终文件。
4. `.patrolx-extracted.json` 中：
   - `subpackages` 有 `ServiceLog_20260901011314.zip` 且 `status=extracted`。
   - `log_gz` 对应目标 `.log` 且 `status=extracted`。
   - `rejected` 无该样例条目。
5. 日志规则匹配的路径以 `logs/` 开头，且不含 `.main/`、`prepared/`。

## 3. 小主包单一类别场景

准备只包含一个 `kpi.zip` 的主包，内部只有 KPI CSV。执行全量任务。

预期：

- 不走独立小包入口。
- `.main/` 保留小主包。
- `kpi/` 展开最终 CSV。
- KPI 规则匹配路径与全量大包路径模型一致。
- 不产生跨任务或跨 category 读取。

## 4. Catalog 匹配与无匹配 skip

用测试或临时样例构造：

```text
logs/
  app/service.log
  db/service.log
kpi/
  kpi.csv
prepared/
  some-rule/filtered.jsonl
.main/
  app/service.log
```

断言：

- `TaskFileCatalog.paths()` 只包含 category 根下文件。
- `.main/app/service.log` 不出现在 catalog。
- `prepared/some-rule/filtered.jsonl` 不出现在 catalog。
- `logs/app/service.log` 和 `logs/db/service.log` 按 POSIX 字典序排序。
- `re.fullmatch(r"logs/.*/service\.log", path.as_posix())` 只命中期望文件。
- 无匹配普通规则返回 `skip`，`skip_reason` 包含 `source_patterns`。

可直接运行：

```bash
pytest -q tests/test_scanning_catalog.py tests/test_scanning_matcher.py
```

## 5. 非法或危险 pattern 拒绝

注册对象中使用以下样例之一：

```text
""                      # 空模式
" /logs/app.log"        # 首尾空白
"/logs/app.log"         # 绝对路径
"logs/../../app.log"    # 路径穿越
"logs/["                # 非法正则
```

预期：

- `Inspector.validate()` 或 `RuleRegistry.register()` 抛出带 pattern 的 `ValueError`。
- catalog 匹配入口的防御测试同样拒绝并保留原因。
- 规则不会得到空匹配后的伪 `pass`。

## 6. Prepare 隔离与缓存

选择一个带 prepare 的规则，例如日志过滤链路中的 owner 规则。

```bash
make verify-one RULE=log.filter
```

检查：

1. `prepared/<owner_code>/` 只生成该 owner 的数据。
2. marker `.prepare.sha256` 等于 owner 规则 Python 文件 SHA-256。
3. 无匹配源文件时 prepare 状态为 `SKIP`，owner inspect 为 `skip`。
4. prepare 失败场景中 owner inspect 为 `skip`，`skip_reason=预处理未就绪`，其他规则继续。
5. 修改 owner 规则文件后重跑，marker 校验失败并重建 owner prepared 数据。
6. prepare 输出不出现在其他普通规则 `ctx.files`。

## 7. 单规则重跑兼容性

```bash
make verify
make verify-one RULE=kpi.call
```

检查：

1. 只有 `kpi.call.json`、任务摘要和报告更新。
2. 无关规则 JSON 的结果语义保持不变。
3. `execution_order` 不被单规则重跑破坏。
4. manifest 已存在且 checksum 一致时不重建 `.main/`。
5. `logs/`、`kpi/` 等最终文件不被重复解压。

## 8. 解压安全与幂等

构造或复用测试样例验证：

1. 路径穿越成员：拒绝并记录 `rejected`，不写出任务根。
2. 符号链接成员：拒绝，不跟踪。
3. 超过递归深度：子包标记 `rejected`，主包任务可继续。
4. 超过文件数或总字节预算：解压停止并记录原因。
5. 相同 checksum 子包：第二次出现状态为 `duplicate`，不重复展开。
6. 同一上传包重复执行：manifest 有效时复用现场；损坏 manifest 时重建。
7. staging 原子替换失败时恢复 `.main.previous/`。

## 9. CLI/API 一致性

使用同一上传包分别执行本地模式与在线模式：

- 本地：`make verify` 或 `python main.py`。
- 在线：启动 `make run` 后通过上传 API 创建任务。

比较除执行标识和时间戳外的规则结果：

- 状态、summary、metrics、findings、来源路径语义一致。
- 本地与在线不出现 catalog 排除范围或匹配排序差异。

## 10. 完成判据

以上全部通过后，本功能实现满足：

- 解压、扫描、上下文、prepare 职责边界清晰。
- 普通规则零感知解压落位变化。
- `TaskFileCatalog` 是唯一普通文件扫描来源。
- 主包、小包、嵌套包共用同一安全解压模型。
- 公共契约兼容，单规则重跑行为稳定。
