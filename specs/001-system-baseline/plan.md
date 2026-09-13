# 实现计划：系统基线

**分支**：`001-system-baseline` | **日期**：2026-09-12 | **规格**：[spec.md](spec.md)

**输入**：来自 `specs/001-system-baseline/spec.md` 的功能规格

## 摘要

PatrolX 已实现了核心离线巡检流程。因此本基线计划不引入新的产品能力。它将既有业务基线正式化，并定义验证、加固和文档化该流程的技术方案：一个包名唯一的预收集包成为一个任务；`task_id` 来自包名；归档内容被安全分类和解压；规则通过 `source_patterns` 直接读取已解压任务文件；结果、发现、日志和报告保留在可追溯的任务目录中；本地和在线体验共享相同的巡检语义。

实现方案是延续而非重写。保留既有架构，任务阶段的工作将验证契约一致性、双模式行为、重跑行为、解压安全性、证据可追溯性和报告可用性是否符合本基线规格。

## 技术上下文

**语言/版本**：Python 3.11+（当前本地执行使用 Python 3.12）

**主要依赖**：FastAPI、Pydantic v2、React 18+、TypeScript、Vite、Ant Design、ECharts、Jinja2、structlog、pytest、Ruff

**存储**：SQLite 用于轻量任务元数据；`uploads/` 和 `output/` 下的文件用于包、解压数据、规则结果、日志和报告

**测试**：pytest 用于后端和契约测试；Ruff 用于 lint 和格式检查；通过 `make verify` 验证本地流水线；通过 `make web-build` 验证前端构建

**目标平台**：内部桌面浏览器用户和单节点本地/服务器部署

**项目类型**：模块化单体，包含本地 CLI 流水线、FastAPI 服务和 React Web UI

**性能目标**：基线正确性优先。受支持的本地包应能在无人工干预的情况下完成完整流水线。本基线不引入新的并发或吞吐量目标。

**约束条件**：

- 仅离线巡检：不连接被检系统。
- 一个包 = 一个任务；系统信息只作为任务内嵌元数据。
- 本地和在线模式共享巡检行为和契约输出。
- 单节点顺序执行是基线。
- SQLite + 文件是默认存储。
- 普通规则仅通过 `source_patterns` 读取任务目录内已解压文件，规则之间不交互。
- 解压必须强制路径、链接、深度、数量、大小和总大小安全限制。
- 发现必须保留来源位置和证据。
- 任务删除必须同时移除保留输入和生成输出。
- 契约版本策略：本基线通过 `/api/v2` 提供干净契约；迁移期保留 `/api/v1` 既有字段兼容；消费者迁移完成后先废弃再删除 `/api/v1`，最终以 `/api/v2` 为唯一公开契约。契约同步先于模型和接口实现。

**规模/范围**：内部团队使用；多个顺序任务；基线覆盖既有离线流水线、在线 API/Web 界面、七个巡检类别、规则重跑、报告、日志和任务生命周期。跨任务趋势分析、在线规则编辑、PDF 导出、报告下载、分布式执行和移动端支持不在范围内。

## 宪法检查

*门禁：必须在阶段 0 研究前通过。阶段 1 设计后重新检查。*

| 原则 | 状态 | 证据/影响 |
| --- | --- | --- |
| 离线优先 | PASS | 基线仅消费预收集包。 |
| 一包一任务 | PASS | 包名任务 ID 和任务目录隔离得以保持。 |
| 契约驱动 | PASS | 以 `/api/v2` 提供干净基线契约，迁移期保留 `/api/v1` 兼容，迁移完成后废弃并删除 `/api/v1`；契约同步先于实现。 |
| 模式同构 | PASS | CLI/API 一致性仍是必须验证项。 |
| 巡检器插件架构 | PASS | 规则仍基于注册表；未添加调度器硬编码。 |
| 源文件显式匹配 | PASS | 普通规则仅消费 `source_patterns` 匹配的文件。 |
| 增量重跑 | PASS | 目标规则重跑只替换目标结果并刷新摘要/报告。 |
| 解压先行 | PASS | 普通规则只读取安全解压后的任务文件。 |
| 幂等与可追溯 | PASS | 解压清单、来源位置、证据和规则元数据得以保留。 |
| 轻量默认 | PASS | SQLite + 文件和顺序执行保持为默认。 |
| 容错 | PASS | 按文件/类别的失败产生跳过/异常结果或结构化日志。 |
| 安全解压 | PASS | 解压防护和资源限制为强制项。 |

本计划未引入宪法违规。不添加外部依赖、新持久化模型、在线采集能力、规则间依赖图或并行/分布式调度器。

## 项目结构

### 文档（本功能）

```text
specs/001-system-baseline/
├── plan.md              # 本文件
├── research.md          # 阶段 0 输出
├── data-model.md        # 阶段 1 输出
├── quickstart.md        # 阶段 1 输出
├── contracts/           # 阶段 1 输出
└── tasks.md             # 阶段 2 输出；非 $speckit-plan 创建
```

### 源代码（仓库根目录）

```text
app/
├── main.py
├── cli.py
├── api/
├── core/
│   ├── archive.py
│   ├── classify.py
│   ├── config.py
│   ├── dicts.py
│   ├── logging.py
│   └── metrics.py
├── models/
├── services/
│   ├── executor.py
│   ├── report.py
│   ├── store.py
│   └── tasks.py
├── inspectors/
│   ├── base.py
│   ├── registry.py
│   ├── pkg.py
│   ├── log/
│   ├── kpi/
│   ├── traffic/
│   ├── alarm/
│   ├── config/
│   └── resource/
└── reports/

web/
└── src/
    ├── api/
    ├── components/
    ├── hooks/
    ├── layouts/
    └── pages/

deploy/
└── config/
    ├── classify_rules.yaml
    └── dicts.yaml

tests/
├── fixtures/
├── test_api.py
├── test_archive.py
├── test_contract.py
├── test_consistency.py
├── test_executor.py
├── test_pipeline.py
├── test_rules.py
└── ...
```

**结构决策**：保持既有模块化单体。后端逻辑保留在 `app/`，前端在 `web/`，配置在 `deploy/config/`，测试和样例在 `tests/`。本基线不引入新的顶层项目、服务或包边界。

## 复杂度跟踪

未引入宪法违规或未证明的复杂度。

| 违规项 | 为什么需要 | 被拒绝的更简单替代方案及原因 |
| --- | --- | --- |
| 不适用 | 不适用 | 不适用 |
