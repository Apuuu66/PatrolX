# 实现计划：解压与规则扫描解耦

**分支**：`feature/decouple-extract-scan` | **日期**：2026-09-14 | **规格**：[spec.md](spec.md)

**输入**：来自 [`spec.md`](spec.md) 的功能规格。

## 摘要

本次重构不改变离线巡检边界和公共 API 契约，而是把“安全解压、任务文件扫描、规则上下文、规则私有 prepare”整理成单向依赖的内部职责边界。

- `EXTRACT` 继续作为唯一通用解压入口：大主包、小分类包、嵌套子包和 `.log.gz` 都在该阶段完成安全展开与分类落位。
- 解压完成后构建一次任务级内存文件清单 `TaskFileCatalog`；普通规则和 owner 私有 prepare 只能通过该清单做 `source_patterns[]` 的 `re.fullmatch()` 匹配。
- prepare 不再拥有通用文件扫描能力，也不再执行通用解压；它只消费 owner 的匹配文件，并把中间数据写入 `prepared/<owner_code>/`。
- 解压服务拆分为 manifest、预算、落位、递归展开和主包编排模块；扫描服务拆分为目录清单构建和模式匹配模块。
- 公共任务、规则结果、指标、发现、证据和来源路径字段语义保持兼容；本地 CLI 与在线 API 继续使用同一执行契约。

## 技术上下文

**语言/版本**：Python 3.11+

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、structlog、PyYAML；本次不新增运行时依赖。

**存储**：`uploads/<task_id>/` 保留原始包；`output/<task_id>/` 保存解压现场、规则结果、执行日志和报告；SQLite 只保存在线任务元数据。`TaskFileCatalog` 不持久化。

**测试**：pytest、Ruff、本地全流程验证 `make verify`、单规则重跑 `make verify-one RULE=<rule_code>`。

**目标平台**：本地 CLI 和 FastAPI 单节点服务；默认单线程顺序执行，不引入外部队列或分布式依赖。

**项目类型**：离线巡检系统，后端与执行器重构，不新增用户界面能力。

**性能目标**：不设新的性能指标；通过消除每规则重复 `rglob()` 和重复解压，减少扫描开销并保持资源预算可控。

**约束条件**：一个数据包对应一个任务和一个输出目录；原始包不可修改；解压必须防护路径穿越、不安全链接和资源炸弹；规则间不得建立依赖；单文件失败不得在任务可安全继续时中止任务。

**规模/范围**：仅重构解压、扫描、上下文、prepare 和执行器协同；不新增巡检规则，不扩展 OpenAPI，不新增前端交互。

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 离线边界 | 通过 | 只读取用户上传包，不新增被检系统连接或在线采集。 |
| 任务隔离 | 通过 | 继续使用 `uploads/<task_id>/` 与 `output/<task_id>/`，不引入跨任务共享现场。 |
| 原始包不可变 | 通过 | 主包只解压到 `.main/`，分类现场通过复制/移动展开，不重写原始包。 |
| 安全解压 | 通过 | 继承并集中维护路径穿越、链接、深度、文件数、单文件和总量预算防护。 |
| 规则隔离 | 通过 | 普通规则只接收自己的 `source_patterns[]` 匹配结果；prepare 数据只属于 owner。 |
| prepare 边界 | 通过 | prepare 是隐藏的 owner 私有基础设施，不展示为普通规则，不执行通用解压。 |
| 调度器无业务硬编码 | 通过 | 执行器只维护阶段屏障、优先级和 catalog 注入，不引入具体业务规则分支。 |
| 容错与证据 | 通过 | 主包失败阻断后续；子包、`.log.gz`、单文件、单规则失败结构化留痕并隔离。 |
| 契约兼容 | 通过 | 不修改 OpenAPI 和 Pydantic 公共契约；结果字段语义保持兼容。 |
| 双模式一致 | 通过 | CLI 与 API 继续调用同一 `Executor` 与解压/扫描服务。 |
| 技术基线 | 通过 | Python/FastAPI/Pydantic v2/SQLite/文件存储/Ruff 不变，不新增运行时依赖。 |
| 语言与时间 | 通过 | 规划与注释使用中文；标识符与字段使用英文；持久化时间继续使用 UTC 与 `*_at`。 |

**阶段 1 复查结论**：设计未引入公共契约破坏、跨规则依赖或通用解压下沉到 prepare；安全边界与失败语义满足宪法要求。

## 项目结构

### 文档（本功能）

```text
specs/007-decouple-extract-scan/
├── plan.md                       # 本文件
├── research.md                   # 技术决策与被拒绝方案
├── data-model.md                 # 解压现场、manifest、catalog、匹配集与 prepare 状态
├── quickstart.md                 # 重构验证场景
└── contracts/
    └── internal-extraction-scan.md # 内部边界契约
```

### 源代码（仓库根目录）

```text
app/
├── core/
│   ├── archive.py                # 继续承担 zip/tar/gzip 的底层安全解压
│   ├── classify.py               # 继续承担分类规则匹配
│   └── checksum.py               # 继续提供 SHA-256
├── inspectors/
│   ├── base.py                   # Inspector、PrepareSpec 与 source_patterns 注册校验
│   ├── registry.py               # 规则与 owner prepare 注册、排序
│   └── pkg.py                    # 隐藏的 pkg.extract.* 结果包装
├── models/
│   └── schemas.py                # 公共契约模型，本计划不修改语义
└── services/
    ├── extraction/               # 高层安全解压编排
    │   ├── __init__.py           # 兼容现有 import 的稳定 facade
    │   ├── budget.py             # 任务级累计预算与常量
    │   ├── layout.py             # 主包/分类目录、安全目标路径与落位
    │   ├── manifest.py           # manifest v3 读取、写入、校验、复用
    │   ├── nested.py             # 子包与 .log.gz 递归展开
    │   └── site.py               # 主包解压、原子替换与最终落位编排
    ├── scanning/
    │   ├── __init__.py           # 扫描服务稳定入口
    │   ├── catalog.py            # TaskFileCatalog 构建与只读访问
    │   └── matcher.py            # source_patterns 防御校验与 fullmatch
    ├── prepare.py                # owner 私有 prepared 目录、缓存 marker 与规则文件 SHA
    └── executor.py               # EXTRACT → PREPARE → INSPECT 屏障与 catalog 注入
```

### 测试结构

```text
tests/
├── test_extraction_site.py       # 主包、小包、递归、安全预算、manifest 幂等
├── test_scanning_catalog.py      # 新增：目录白名单、排序、排除物、匹配契约
├── test_scanning_matcher.py      # 新增：非法 pattern、绝对路径、穿越、稳定排序
├── test_executor.py              # catalog 注入、匹配文件、skip/error 行为
├── test_prepare_cache.py         # owner 私有缓存与失效
├── test_prepare_pipeline.py      # prepare 只消费 catalog 匹配文件
├── test_baseline_rerun.py        # 单规则重跑不影响无关规则
└── test_baseline_pipeline.py     # CLI/API 行为与契约兼容
```

**结构决策**：把现有多职责的 `app/services/extraction.py` 和 `app/services/prepare.py` 拆成服务包。底层压缩算法仍留在 `app/core/archive.py`；高层解压编排和任务文件扫描分别归入 `services/extraction` 与 `services/scanning`。`services/prepare.py` 只保留 owner 私有 prepare 基础设施。

## 技术方案

### 1. 统一 EXTRACT 阶段

`pkg.extract.main` 触发 `extraction.site.extract_main_site()`，继续作为唯一通用入口：

```text
上传包（大主包或小分类包）
→ 计算 SHA-256 并检查可复用 manifest
→ 安全解压到 .main.staging/
→ 原子替换 .main/
→ 清空并重建分类根目录
→ 遍历 .main/ 中的普通文件
→ 分类、复制到 <category>/...
→ 递归展开子包和 .log.gz
→ 写入 .patrolx-extracted.json
→ 输出 pkg.extract.main 与 pkg.extract.{category} 隐藏结果
```

小主包不需要单独入口；它只是成员分类集中到一个 category 的主包。嵌套子包和 `.log.gz` 在 `EXTRACT` 内有界递归展开，禁止下沉到 prepare。

### 2. 解压模块边界

- `manifest.py` 负责 v3 结构、checksum 匹配、损坏重建、原子写和复用判断。
- `budget.py` 负责任务累计文件数、总字节、嵌套深度和底层 `UnpackLimit` 协同。
- `layout.py` 负责类别目录映射、相对目标推导、目标路径防穿越和防链接。
- `nested.py` 负责子包 checksum 去重、staging、失败/拒绝/冲突状态和 `.log.gz` 展开。
- `site.py` 只做主包编排：staging → `.main/` → 清理分类现场 → 遍历落位 → manifest。
- `__init__.py` 继续导出 `extract_main_site`、`category_failures`、manifest 函数和常量，保证内部调用与既有测试迁移成本可控。

### 3. 统一任务文件扫描

`EXTRACT` 完成后，`Executor` 调用 `TaskFileCatalog.build(ctx.data_dir)` 构建一次内存清单。catalog 不落盘，不复制文件，只保存 `/` 归一化后的相对 `Path` 列表。

扫描范围采用 category 白名单：`logs`、`kpi`、`traffic`、`alarm`、`config`、`resource`、`other`。因此任务元数据、执行日志、报告、规则结果、`.main/`、manifest 和 `prepared/` 天然不会进入普通规则可见范围。

catalog 不变量：

- 只包含最终可巡检文件，不包含目录、原始证据和中间压缩包。
- 路径是相对 `output/<task_id>/` 的 POSIX 风格路径。
- 列表按 `path.as_posix()` 字典序稳定排序。
- 不跟踪符号链接；发现越界或链接时立即拒绝并保留原因。
- `match(source_patterns)` 对每个路径执行 `re.fullmatch()`，结果去重并保持稳定排序。

### 4. 规则上下文与 prepare

`RuleContext` 增加 owner 执行期间共享的 catalog 引用；`Executor._matched_files()` 改为调用 catalog，不再遍历整个任务目录。prepare 的输入是 owner 规则 `source_patterns[]` 的匹配结果，而不是其他规则结果。

`app/services/prepare.py` 保留：

- `prepared_dir(ctx, owner_code)`
- `marker_path(ctx, owner_code)`
- `rule_python_path(rule)`
- `rule_file_sha256(rule)`

通用 `match_relative_files()` 从 prepare 模块删除，调用方和测试迁移到 `app.services.scanning`。prepare 缓存 marker 继续使用 owner 规则 Python 文件 SHA-256 做轻量失效判断；不增加手动刷新命令或全局开关。

### 5. 执行屏障与单规则重跑

全量执行保持：

```text
EXTRACT 主包优先
→ 主包失败阻断 PREPARE/INSPECT
→ 全部解压隐藏规则到达终态
→ 构建一次 TaskFileCatalog
→ PREPARE 按 owner priority / owner code / prepare code 执行
→ INSPECT 按 priority / code 执行
```

单规则重跑先确保 manifest 和解压现场就绪；缺失或不可复用时执行主包解压，再构建 catalog。随后只执行或复用目标规则私有 prepare，最后只执行目标规则并更新目标结果、任务摘要和报告。

### 6. 失败与安全策略

| 场景 | 策略 |
| --- | --- |
| 主包解压失败 | 删除 staging，`pkg.extract.main` 为 `error`，阻断 PREPARE/INSPECT，任务失败。 |
| 子包失败/拒绝/超限 | 写入 manifest `subpackages` 和必要时 `rejected`，可安全继续时不中止任务。 |
| `.log.gz` 冲突/失败/拒绝 | 写入 manifest `log_gz`，保留可用的失败原因；日志规则按实际文件决定 skip/inspect。 |
| 普通文件目标冲突 | 记录 rejected 与警告日志，不覆盖已有文件。 |
| 单文件解析失败 | 由规则统一捕获为 `error`，其他规则继续。 |
| prepare 失败 | owner 规则 `skip`，原因“预处理未就绪”；其他规则继续。 |
| `source_patterns` 无匹配 | 普通规则 `skip`，`skip_reason` 列出模式；prepare 状态为 `SKIP`。 |
| 非法/越界 pattern | 注册时拒绝；catalog 匹配时防御性拒绝并记录原因。 |

### 7. 兼容与迁移

- 不修改 `docs/api/openapi.yaml`、公共 Pydantic 模型和前端生成客户端。
- `RuleResult`、`Metric`、`Finding`、状态、`skip_reason`、evidence、来源路径语义不变。
- `pkg.extract.*` 仍为隐藏规则；`execution_order`、任务摘要和报告行为保持兼容。
- 旧 manifest v3 可复用；损坏、版本不匹配或 checksum 不一致时整体重建。
- `app.services.extraction` 包 facade 保持既有导入；`prepare.match_relative_files` 不保留混合入口，实现时同步更新内部调用与测试。

## 复杂度跟踪

> 本节说明设计中被有意接受的复杂度。

| 违规/复杂度 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 引入 `TaskFileCatalog` 内存抽象 | 统一是实现“唯一扫描来源”和消除每规则重复遍历的最小机制 | 继续每规则 `rglob()` 会保留解压与扫描耦合，无法证明只扫描最终可巡检文件 |
| 解压服务拆为五个模块 | manifest、预算、落位、递归和主包编排变化频率不同，混合文件会继续扩大 | 只拆两个文件无法解决职责边界和递归安全集中测试问题 |
| category 白名单扫描 | 输出根目录同时包含任务产物与解压现场，白名单能可靠排除非源文件 | 黑名单需要持续维护 `.main/`、manifest、prepared、rules、报告、日志等产物，漏排风险更高 |

## 交付门禁

实现分支合入前至少执行：

```bash
make lint
make test
make verify
```

若实现过程中意外触及 OpenAPI 或公共模型，必须先回到 Speckit review，并执行 `make contract` 与 `make gen-web-api`；本计划默认不触达。
