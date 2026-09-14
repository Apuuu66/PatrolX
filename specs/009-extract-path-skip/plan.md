# 实现计划：压缩项解压跳过与白名单策略

**分支**：`feature/extract-path-skip`（tasks review 后创建） | **日期**：2026-09-15 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/009-extract-path-skip/spec.md` 的功能规格。

## 摘要

在 007 的统一 `EXTRACT → PREPARE → INSPECT` 现场上增加项目级解压策略。主包仍必须安全解压；主包内的嵌套压缩项可按目录前缀或全局设置保留不展开，白名单例外优先于跳过策略并恢复普通解压或分类拷贝行为。被跳过的压缩项保留为最终证据文件，写入对应 category 现场，并通过 manifest 与结构化日志审计；普通规则仍只依赖统一 `TaskFileCatalog` 和 `source_patterns[]`。

方案使用独立的 `deploy/config/extract_policy.yaml` 承载策略，执行逻辑从配置读取白名单关键字；交付配置预置 `alarm`，代码不硬编码业务关键字。既有公共 API 和 `RuleResult` 契约保持兼容。

## 技术上下文

**语言/版本**：Python 3.11+

**主要依赖**：FastAPI、Pydantic v2、PyYAML、pytest；继续复用现有安全解压、分类、manifest、预算和文件清单能力。

**存储**：本地文件系统；原始包保留在 `uploads/<task_id>/`，解压现场和审计写入 `output/<task_id>/`。不新增数据库表。

**测试**：pytest、`python build.py lint`、`python build.py test`、`python build.py verify`。

**目标平台**：macOS / Linux 本地 CLI 与在线 API 共用同一执行服务。

**项目类型**：FastAPI 后端 + React 前端的离线巡检应用；本功能不新增前端交互。

**性能目标**：不新增响应时间指标；通过减少不必要嵌套解压降低耗时和输出体积。

**约束条件**：
- 一个包、一个任务、一个输出目录。
- 原始上传包不可修改。
- 主包必须解压；只有主包内的压缩项可被策略保留。
- 路径作用域和白名单必须防越界、防链接、防资源超限。
- `extract_policy.yaml` 是部署侧静态项目级配置，不提供在线修改接口、任务级覆盖或热更新契约。
- 未配置策略时行为与 007 兼容。
- 本地 CLI 与在线 API 的解压策略语义一致。

**规模/范围**：仅调整解压策略、解压现场、解压审计和任务文件清单输入；不改普通规则实现、OpenAPI、前端页面或数据库模型。

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后复核通过。*

| 原则 | 结论 | 说明 |
| --- | --- | --- |
| 离线优先 | 通过 | 策略只作用于已上传归档，不引入外部采集或连接。 |
| 一个包、一个任务 | 通过 | 策略是项目级配置；输出仍按 `task_id` 隔离。 |
| 契约驱动 | 通过 | 不修改 OpenAPI 和公共 `RuleResult` 字段；只扩展内部解压配置和 manifest 审计契约，并同步架构文档。 |
| 模式同构 | 通过 | CLI 与 API 共用 `extract_main_site()` 和同一策略加载器。 |
| 巡检器插件架构 | 通过 | 普通规则不感知策略实现，核心调度不新增业务规则。 |
| 源文件显式匹配 | 通过 | `TaskFileCatalog` 仍只扫描 category 根；规则仍用 `re.fullmatch()` 匹配最终文件。 |
| 增量重跑 | 通过 | 单规则重跑先复用有效解压现场；不因项目策略变更自动重建旧任务。 |
| 解压先行 | 通过 | 主包仍先解压；命中策略的嵌套压缩项作为最终文件保留。 |
| 幂等与可追溯 | 通过 | manifest 记录策略快照、状态、来源和目标；现场有效时复用。 |
| 轻量默认 | 通过 | 无新外部依赖；配置文件缺省时保持现有解压行为。 |
| 容错 | 通过 | 被跳过的损坏压缩项不展开、不阻断任务；真实局部失败仍单独留痕。 |
| 安全解压 | 通过 | 白名单内容仍走既有预算、路径和链接防护；跳过路径不能绕过任务边界。 |

## 项目结构

### 文档（本功能）

```text
specs/009-extract-path-skip/
├── plan.md              # 本文件
├── research.md          # 阶段 0 决策与备选方案
├── data-model.md        # 策略、决策和 manifest 数据模型
├── quickstart.md        # 端到端验证指南
├── contracts/
│   └── manifest-policy-contract.md
└── tasks.md             # 后续由 $speckit-tasks 生成
```

### 源代码（仓库根目录）

```text
app/services/extraction/
├── policy.py            # 新增：策略加载、归一化、前缀与关键字匹配
├── manifest.py          # 扩展：策略快照、skipped 状态与校验
├── nested.py            # 扩展：压缩项决策、保留落位、白名单恢复
├── site.py              # 扩展：加载策略、注入执行、策略摘要
└── __init__.py          # 导出策略与查询入口

deploy/config/
└── extract_policy.yaml  # 新增：项目级策略和初始 alarm 关键字

tests/
├── test_extract_policy.py       # 新增：配置加载、归一化、校验和白名单匹配
├── test_extraction_policy.py    # 新增：manifest 策略契约、审计和幂等
├── test_archive.py              # 扩展：主包/嵌套包/log.gz 的策略行为
├── test_rule_execution.py       # 扩展：策略导致无匹配时的 skip 原因
├── test_observability.py        # 扩展：策略相关结构化日志
├── test_archive_robustness.py   # 扩展：安全预算和路径穿越回归
└── test_baseline_consistency.py # 扩展：CLI 与 API 同策略结果一致性

docs/
├── architecture.md      # 更新解压策略与 manifest 说明
└── design/mechanisms.md # 更新 EXTRACT 决策顺序与审计说明
```

**结构决策**：策略属于解压基础设施，放在 `app/services/extraction/policy.py`，不放入 `core/` 调度或规则目录；配置文件与分类规则分离，避免把安全解压策略混入文件分类规则。

## 设计

### 1. 配置模型

新增 `deploy/config/extract_policy.yaml`。该文件是部署侧静态项目级配置，不提供在线修改接口、任务级覆盖或热更新契约；文件缺失或为空时等价于：

```yaml
version: 1
nested:
  skip_all: false
  skip_paths: []
whitelist:
  paths: []
  name_keywords: []
```

交付配置预置：

```yaml
version: 1
nested:
  skip_all: false
  skip_paths: []
whitelist:
  paths: []
  name_keywords:
    - alarm
```

- `nested.skip_all=true` 表示保留主包内全部非白名单嵌套压缩项，不继续展开。配置结构由 `ExtractPolicyConfig` 和策略加载测试约束，不新增 JSON Schema。
- `nested.skip_paths[]` 是任意深度目录前缀。
- `whitelist.paths[]` 是优先于跳过策略的路径前缀。
- `whitelist.name_keywords[]` 按文件名或任一目录段子串匹配，忽略大小写。
- `alarm` 只作为交付配置中的初始关键字；修改配置无需改执行代码。

### 2. 路径匹配语义

所有作用域先按任务内 POSIX 相对路径归一化：

- `/0/` → `0/`
- `/xx/0/` → `xx/0/`
- 前缀目录及其全部子路径命中。
- 空字符串、`/`、`.`、`..`、越界路径、空段非法。
- 前缀必须以 `/` 结尾归一化，避免 `0/` 误匹配 `0a/file`。

名称关键字匹配：

- 对相对路径的每个目录段和最终文件名分别做大小写无关子串匹配。
- 任一段命中即白名单命中。
- `AlarmFiles/x.log`、`service_ALARM.zip`、`node/alarm.txt` 均命中。
- 不读取被跳过压缩包内部名称来判断白名单。

### 3. EXTRACT 决策顺序

对主包内每个待处理条目按以下顺序决策：

1. 主包本身始终解压，不参与跳过和白名单判断。
2. 普通文件保持现有分类拷贝行为。
3. 对 `.log.gz` 和嵌套压缩归档先判断白名单。
4. 白名单命中 → 恢复既有解压、预算、分类和递归展开流程。
5. 未命中白名单时判断全局保留或路径跳过。
6. 命中跳过 → 不读取内部内容、不递归展开，把压缩项保留为 category 现场文件。
7. 未命中 → 执行既有子包或 gzip 解压流程。

跳过分类只使用来源文件名和父级分类，不通过读取压缩包成员内容嗅探分类。

### 4. 落位与幂等

- 来源在 `.main/` 的非白名单被跳过压缩项复制到对应 category 目录，保留相对路径。
- 来源已在 category 子现场的嵌套压缩项原地保留，不复制、不展开。
- 只有成功保留的压缩项才能记录为 `skipped`；复制失败、目标冲突或预算拒绝时记录局部 `failed` 或 `rejected`，不覆盖既有文件，任务可安全继续时继续。
- 被跳过压缩项复制或保留时计入资源预算。
- manifest 有效时复用现有现场；不比较项目策略是否变化，也不自动重建旧任务。
- 现场缺失或损坏必须重建时，按当时项目级策略执行。

### 5. 审计与任务文件清单

manifest `policy` 节保存配置快照摘要、fingerprint 和计数器；`subpackages` 与 `log_gz` 条目新增 `skipped` 状态和白名单/跳过决策原因。普通文件的白名单命中通过结构化日志记录，避免把大量文件路径复制进 manifest。

被跳过压缩项是 category 根下最终文件，进入 `TaskFileCatalog`；其内部内容不进入清单。普通规则无匹配时，executor 可结合同 category 的策略跳过记录在 `skip_reason` 中补充可读原因；普通规则继续只依赖自身 `source_patterns[]` 和 `TaskFileCatalog`，不得读取 manifest，也不得建立规则间依赖。

## 复杂度跟踪

无需声明宪法违规。策略模块、manifest 审计和 category 落位是满足可追溯与安全跳过的最小设计；无额外架构分层。
