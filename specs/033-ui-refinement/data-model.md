# 数据模型：界面降噪与一致性精修

本功能不引入契约数据实体，只定义展示层模型。所有字段均来自既有 OpenAPI 响应，不新增、不修改字段含义。

## 1. 状态分布段（StatusSegment）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| key | `pass \| warn \| fail \| error \| skip` | 状态键，沿用既有契约 |
| label | string | 中文状态名 |
| value | number | 计数；为 0 时不渲染 |
| percent | number | `value / total × 100`，Tooltip 展示为整数百分比 |
| color | string | 填充色：标准状态色或概览条弱化色 |
| emphasis | `attention \| normal \| quiet` | 视觉权重；概览条 pass/skip 为 quiet，任务摘要按 `getStatusStatEmphasis` 推导 |

**排序规则**：`fail → warn → error → skip → pass`（全站一致）。
**校验规则**：`value` 为非负整数；`total > 0` 才渲染分段与计数；五态全 0 时渲染空文案。

## 2. 概览指标（OverviewMetric）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| key | string | `task_count / registered_rule_count / rule_result_count / finding_count` |
| label | string | 界面名称 |
| description | string | 口径说明（Tooltip 文案） |
| scope | string | 统计范围，本轮固定为"全部任务" |

**口径定义**：规则结果 = 全部任务中已执行规则条目数（pass/warn/fail/error/skip 之和）；发现问题数 = 全部规则输出中的 finding 条目数，一条规则可产生多条 finding。

## 3. 发现条目视图（FindingView）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| title | string | 发现标题 |
| severity | string | `low / medium / high / critical` |
| severityDisplay | `{ label, tone }` | 轻量表达：色点 + 文字，不使用描边标签 |
| sourceFile | string \| null | 来源路径，可复制 |
| evidence | EvidencePart[] \| string | 结构化后的证据；解析失败保留原始字符串 |
| details | string \| null | 详情 |
| recommendation | string \| null | 建议 |
| collapsed | boolean | 超过 4 行时默认折叠 |

**EvidencePart**：`{ label?: string; value: string; highlights: string[] }`。
**解析规则**：按 `；` 拆段；识别 `键：值` / `键 值`；数字、次数、时长标记 `highlights`；解析失败降级为整段文本，不丢信息。

## 4. 显示偏好（DisplayPreference）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| tableDensity | `compact \| comfortable` | 默认 `compact`；持久化 key `patrolx.tableDensity` |
| source | `local \| default` | 本地读取失败或非法值时回退默认 |

**校验规则**：读取失败、JSON 非法或值不在枚举内时使用默认值且不报错；切换不重置筛选、分页与滚动位置。

## 5. 上传预检（UploadPrecheck）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| fileName | string | 用户选择的文件名 |
| sizeBytes | number | 文件大小 |
| taskIdPreview | string | 与后端 `clean_task_id` 同规则派生 |
| formatValid | boolean | 扩展名校验结果 |
| sizeValid | boolean | 空文件与上限校验结果 |
| messages | string[] | 具体原因与下一步动作 |
| conflict | `none \| same_checksum \| different_checksum` | 同名冲突状态 |

**派生规则**（与后端一致）：去 `zip/tar.gz/tgz/tar` 扩展名 → 小写 → 非 `[a-z0-9]` 连续字符替换为 `_` → 去首尾 `_` → 空串回退 `task` → 前缀 `task-`。
**校验规则**：非法格式、超长文件名、空文件、超过上限时禁用提交并给出具体原因；同名且 checksum 相同提示"将打开已有任务"，checksum 不同提示"修改文件名或查看已有任务"。

## 6. 术语表（Glossary）

| 术语 | 定义 |
| --- | --- |
| 规则结果 | 一条规则一次执行的 pass / warn / fail / error / skip 结论 |
| 发现 | 一条规则输出中的单条问题记录（finding） |
| 问题条目 | 概览指标中"发现问题数"的计数单位，等于全部发现之和 |
| 状态分布 | 五态规则结果的计数与占比表达 |
| 任务 | 一个数据包对应的一次巡检及其输出目录 |

## 状态转换

本功能不涉及业务状态机；仅展示偏好在上传/密度切换时读写本地存储，失败即回退默认，无持久化副作用。
