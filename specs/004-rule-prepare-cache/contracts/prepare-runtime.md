# 运行时契约：规则私有 prepare

## 1. 范围

本契约描述后端执行器与规则之间的内部运行时约定。它不是 HTTP API 契约，也不改变 `docs/api/openapi.yaml`。

## 2. 阶段契约

```text
EXTRACT
  → 所有 pkg.extract.* 规则到达终态
  → 主包成功

PREPARE
  → 所有已声明 prepare 执行或命中缓存
  → prepare 结果为 HIT / REBUILT / SKIP / FAILED

INSPECT
  → 普通规则执行
  → prepare 失败的 owner 规则直接 skip
```

- extract 完成前禁止任何 prepare 执行。
- prepare 完成前禁止任何普通 inspect 执行。
- prepare 之间没有隐式或显式依赖。

## 3. 规则声明契约

一条 prepare-enabled 普通规则必须具备：

1. 完整的现有 `Inspector` 元数据。
2. `source_patterns[]`，用于声明源数据范围；必须以 `re.fullmatch()` 匹配 `output/<task_id>/` 下以 `/` 归一化的相对路径。
3. 一个私有 `PrepareSpec`。
4. `PrepareSpec.owner_code` 与自身 `code` 相同。

prepare 可以写任意文件到 `output/<task_id>/prepared/<owner_code>/`，但不得写其他规则目录，不得写公共 `artifact` 或 `artifacts/inputs`。owner inspect 只读取自己的 prepared 目录和既有任务上下文。

## 4. 缓存契约

### Marker

```text
output/<task_id>/prepared/<owner_code>/.prepare.md5
```

- 内容：当前 owner 规则所在 Python 文件内容的 md5。
- marker 不存在：缓存 miss。
- marker 存在但内容不同：缓存 miss。
- marker 存在且内容相同：缓存 hit。
- 缓存 miss 时先清空 `prepared/<owner_code>/`。
- prepare 成功后写入新 marker。
- prepare 失败不得写入新 marker。
- 不检查 prepared 业务输出文件是否存在。
- 不扫描输入文件 checksum。
- 不检查共享 helper 文件变化。

### 缓存日志

- hit 记录 `prepare_cache_hit`。
- miss并重建成功记录 `prepare_cache_rebuild`。
- rebuild 失败记录 `prepare_error`。
- owner 被 skip 时记录 `inspect_skip_prepare_not_ready`。

## 5. 失败契约

| 场景 | prepare 状态 | owner inspect 状态 | 任务状态 |
| --- | --- | --- | --- |
| 主包解压失败 | 不执行 | 不执行 | 任务失败 |
| category 子包部分失败且仍有可用源文件 | 可成功处理可用部分 | 正常执行 | 任务继续 |
| category 子包失败导致无可用源文件 | `SKIP` | `skip` | 任务继续 |
| prepare 抛出异常 | `FAILED` | `skip`，说明预处理未就绪 | 任务继续 |
| owner inspect 抛出异常 | 不适用 | `error` | 任务继续 |

prepare 的错误和 skip 必须有结构化日志；不得静默吞没。

## 6. 单规则重跑契约

对目标普通规则 `R`：

1. 确保 extract 数据就绪。
2. 只执行或复用 `R` 的 prepare。
3. 只执行 `R` 的 inspect。
4. 不执行其他普通 inspect。
5. 只更新 `R` 的规则结果、任务摘要和 HTML 报告。

如果 `R` 没有 prepare，行为与现有单规则重跑保持兼容。

## 7. API 契约影响

- 不新增、不修改 HTTP endpoint。
- 不新增、不修改 `RuleResult`、任务摘要或报告的公共字段。
- prepare 不作为普通规则返回。
- prepared 文件不通过 API 暴露。
- 若未来要把 prepare 元数据暴露到规则列表，必须先更新 OpenAPI 和生成客户端。
