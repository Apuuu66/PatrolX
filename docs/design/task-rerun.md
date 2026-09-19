# 任务重跑与重建重跑数据刷新说明

本文说明任务普通重跑与显式重建重跑会刷新、复用或不触碰哪些数据。接口契约以
[`docs/api/openapi.yaml`](../api/openapi.yaml) 为准；执行编排在
`app/services/tasks.py`、`app/services/executor.py` 和 `app/cli.py`。

## 1. 普通重跑模式

`POST /api/v2/tasks/{task_id}/rerun` 支持两种模式：

| 请求 | 语义 |
| --- | --- |
| 不传 `rule_codes`，或 `rule_codes=null` | 全量重跑 |
| `rule_codes=["a", "b"]` | 指定规则重跑，多个目标按列表顺序串行执行 |
| `rule_codes=[]` | 当前实现等同于全量重跑 |

重跑不新建 `task_id`，仍然使用同一个原始包、任务目录和输出目录。
受理后任务会先进入 `pending`，清空 `completed_at`，随后进入执行队列。

## 2. 数据分类

### 2.1 全量重跑

| 数据 | 行为 |
| --- | --- |
| `task_id`、原始包位置 | 保留 |
| `uploads/<task_id>/` 原始包 | 不修改；重新计算 checksum 用于解压复用判断 |
| 任务状态 | 刷新：`pending → running → completed/failed` |
| `task.json` | 刷新：状态、统计、系统结果、`created_at` 和 `completed_at` 按本次执行重写 |
| `system.json` | 重写：规则列表、状态摘要、包名、checksum 和任务元数据 |
| 所有可见规则 `rules/<rule_code>.json` | 重写：重新执行并覆盖 `status`、指标、发现、耗时和执行时间 |
| 所有隐藏 `pkg.extract.*` 结果 JSON | 重写：即使解压现场复用，也会根据当前 manifest 重新生成检查结果 |
| `report.html` | 重写 |
| `execution.log` | 追加；不清理历史日志 |
| SQLite 任务状态 | 刷新 `status` 和 `completed_at` |
| 任务名、mode、trigger、customer、version | 沿用既有任务元数据，重跑不修改 |

### 2.2 解压现场

解压现场是否重建由 manifest、原始包 checksum 和路径限制快照共同决定。

| 条件 | 行为 |
| --- | --- |
| manifest v4 有效、`.main/` 存在、checksum 相同、路径限制快照相同 | 复用 `.main/`、分类工作目录和 manifest |
| manifest 缺失/损坏/版本不匹配，或 checksum、路径限制快照变化 | 重建 `.main/`、分类工作目录和 manifest |

“复用”不代表隐藏解压规则结果不刷新；`pkg.extract.*` 的 JSON 结果仍会重写，
只是其中的解压数据来源不变。

### 2.3 规则私有 prepare

prepare 是规则私有基础设施，缓存 marker 位于
`prepared/<owner_code>/.prepare.sha256`，当前校验值是 owner 规则 Python 文件内容 SHA-256。

| 条件 | 行为 |
| --- | --- |
| marker 存在且等于当前 owner 规则文件 SHA-256 | 复用 `prepared/<owner_code>/`，不重跑 prepare |
| marker 缺失、不匹配，或 owner 规则文件变化 | 删除 owner 私有目录并重建 prepare，再写入 marker |
| prepare 没有匹配源文件 | 本轮 prepare 状态为 `SKIP`，不执行规则 |
| prepare 执行失败 | owner 规则返回 `skip`，不阻断其他规则 |

prepare 缓存不是按原始包内容校验的全量缓存；它只做 owner 规则文件内容的轻量校验。
因此 marker 命中时，即使重跑，prepared 中间数据也不会重建。

### 2.4 KPI 任务快照

`kpi/kpi_catalog_snapshot.json` 是任务级不可变快照，记录该任务启动/首次需要 KPI 配置时的
有效 KPI 拆分配置和规则集合。它保存的是配置，不保存 KPI 检查结果或 CSV 数据。

“有效快照”指该文件存在，且能被 `KpiTaskCatalogSnapshot` 契约模型解析并用于构建任务级
KPI 配置。重跑不会校验其 `base_data_version` 或 `classification_version` 是否仍是当前最新版本。

主要字段：

| 字段 | 内容 |
| --- | --- |
| `schema_version` | 快照结构版本，当前为 `1` |
| `base_data_version` | 生成快照时拆分配置集的内容指纹 |
| `classification_version` | 生成快照时的 KPI 业务域分类版本 |
| `captured_at` | 快照生成时间，UTC |
| `metrics[]` | 任务可用的 KPI 指标定义，含 `key`、`resource_id`、中英文名、业务域 `domain` 和计算规则 `rule` |
| `rules` | 任务 KPI 规则集合，含 `common`、`metric_rules`、`thresholds`、`capacity_rules`、`display_rules` |

其中 `rules.common` 通常包含输入时区、文件数和记录数预算；`metric_rules` 描述指标类型、
语义分组、展示角色、单位、聚合方式和公式；`thresholds` 保存阈值方向、单位、默认值和周期阈值；
`capacity_rules` 保存容量指标语义；`display_rules` 保存展示规则。

| 条件 | 行为 |
| --- | --- |
| 快照存在且可解析 | 复用快照，不因拆分配置或数据库分类状态后来变化而重建 |
| 快照缺失 | 从拆分配置 + 数据库分类状态补写 |
| 快照损坏 | 重跑失败，不回退当前拆分配置，也不静默重建 |

## 3. 指定规则重跑

指定一个或多个规则时，执行器只处理目标规则；多个目标不会合并成一次全量运行。

### 3.1 会刷新的数据

| 数据 | 行为 |
| --- | --- |
| 目标规则 JSON | 重新匹配 `source_patterns`、执行目标 inspect，并原子覆盖结果 |
| 目标规则私有 prepare | 先执行缓存校验；未命中时重建 |
| `system.json` | 用磁盘上全部规则结果重建状态摘要和规则列表 |
| `task.json` | 刷新统计、系统结果和 `completed_at` |
| `report.html` | 用当前全部规则结果重写 |
| `execution.log` | 追加执行与重跑日志 |
| SQLite 任务状态 | 刷新执行状态和完成时间 |

如果解压 manifest 缺失或不可复用，指定规则重跑会先重建解压现场；
否则不会重跑解压，也不会重写 `pkg.extract.*` 结果。

### 3.2 不会刷新的数据

| 数据 | 行为 |
| --- | --- |
| 未指定的普通规则 JSON | 不执行、不重写 |
| 其他规则私有 prepare 目录 | 不执行、不重建 |
| 有效解压现场和 manifest | 复用 |
| 有效 KPI 任务快照 | 复用 |
| `task_id`、原始包、任务名、mode、trigger、customer、version、`created_at` | 保留 |
| 历史执行日志 | 保留，新日志追加 |

## 4. 语义边界

- 全量重跑会重新执行所有可见规则，但底层的解压现场、prepare 和 KPI 快照仍可能命中既有缓存。
- 指定规则重跑不是事务级快照：除目标规则外，`system.json` 和 HTML 报告会使用其他规则当前落盘结果重建。
- 规则逻辑变化必须升级 `rule_version`；如果变化影响私有 prepare，也要保证 owner 规则文件内容变化，从而使 prepare marker 失效。
- 全量重跑中主包解压失败会阻断 prepare 和 inspect，任务标记为失败；已有报告不会在本次失败路径中重写。
- 任务执行/重跑期间规则结果使用原子 JSON 写入，并发读取不应看到截断内容。

## 5. 重建重跑

`POST /api/v2/tasks/{task_id}/rebuild` 是独立的显式重建入口，不复用历史解压现场。
它用于配置变化、解压现场损坏或需要强制重算的场景；普通重跑行为保持不变。

### 5.1 全量重建

请求使用 `mode=full` 且 `confirmed=true`。预检通过后删除 `output/<task_id>/`，
再调用与新建任务相同的完整流程：

| 数据 | 行为 |
| --- | --- |
| 原始上传包 | 只读；不移动、不修改、不删除 |
| `.main/`、分类工作目录、manifest | 删除后从原始包完整重建，不复用历史解压数据 |
| 所有规则私有 prepare | 删除后重建 |
| 所有普通规则 JSON | 按当前代码和当前有效配置重算 |
| `system.json`、`task.json`、统计、报告 | 重建 |
| KPI 任务快照 | 删除后按当前拆分配置和数据库分类状态生成新快照 |
| `task_id`、任务元数据、`created_at` | 保留；`completed_at` 更新为本次完成时间 |
| 历史输出和执行日志 | 随输出目录重建；新执行日志记录 `operation=rebuild`、`mode=full` |

全量重建会在清理输出前校验任务状态、原始包和当前 KPI 拆分配置。
预检失败时不会删除或修改既有输出。

### 5.2 增量重建

请求使用 `mode=incremental`、`confirmed=true` 和非空去重的普通 `rule_codes`。

| 数据 | 行为 |
| --- | --- |
| 原始上传包 | 只读 |
| `.main/`、分类工作目录、manifest | 删除 manifest 和分类现场后强制重建解压 |
| 目标普通规则 JSON | 只重算并覆盖指定规则 |
| 目标规则私有 prepare | 强制删除并重建，不命中 owner 文件内容缓存 |
| 未指定普通规则 JSON、其他规则 prepared 目录 | 保留不变 |
| KPI 任务快照 | 预检通过后读取、备份并在解压后原样恢复；不生成新快照 |
| `system.json`、`task.json`、统计、报告 | 使用保留结果加本次结果重建 |
| `task_id`、任务元数据、`created_at` | 保留；`completed_at` 更新为本次完成时间 |
| 执行日志 | 追加；记录 `operation=rebuild`、`mode=incremental`、`rule_codes` |

增量重建要求既有 KPI 快照存在且可解析。快照缺失或损坏、目标规则不存在、
目标规则是隐藏规则、任务忙或原始包缺失时，在执行前拒绝。

### 5.3 与普通重跑的差异

| 操作 | 解压现场 | prepare | 规则范围 | KPI 快照 |
| --- | --- | --- | --- | --- |
| 普通全量重跑 | 有效时复用 | 有效缓存时复用 | 全部普通规则 | 有效时复用 |
| 普通指定规则重跑 | 有效时复用 | 目标规则有效缓存时复用 | 指定普通规则 | 有效时复用 |
| 全量重建 | 强制完整重建 | 全部强制重建 | 全部普通规则 | 生成新快照 |
| 增量重建 | 强制完整重建 | 仅目标规则强制重建 | 指定普通规则 | 保留既有快照 |
