# 实现计划：KPI-only 规则库收缩

**分支**：`feature/037-kpi-only-rule-library` | **日期**：2026-11-01 | **规格**：[spec.md](./spec.md)

**输入**：来自 `/specs/037-kpi-only-rule-library/spec.md` 的功能规格

## 摘要

将活动普通巡检规则硬收缩为唯一的 `kpi.measurement_units`：删除告警、配置、日志、资源和话统规则模块，最小化 `scan_rules.yaml`，同时保留隐藏的 `pkg.extract.*` 解压基础设施、文件分类、设备台账、SQLite 历史结果和任务现场读取能力。读取历史非 KPI 规则结果不再依赖活动注册表；重跑或增量重建已删除规则仍明确返回未注册错误。KPI 判定逻辑、结果契约、Schema、API 版本和 `rule_version` 保持不变。

## 技术上下文

**语言/版本**：Python 3.11+；TypeScript/React（Vite）

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy/SQLite、Ant Design、pytest、Vitest、Playwright

**存储**：`output/<task_id>/` 任务现场；SQLite 任务、规则状态、台账与 KPI 历史数据

**测试**：pytest；前端 Vitest；Playwright E2E；`build.py verify` 全流程验证

**目标平台**：离线 Linux 服务端与桌面优先 Web 界面

**项目类型**：FastAPI 后端 + React 前端的离线巡检 Web 应用

**性能目标**：不新增运行时开销；删除模块后规则扫描和执行计划规模下降，KPI 路径性能不得回退

**约束条件**：不得修改原始上传包；不得迁移或清理真实历史数据；不得改变 `RuleResult`/`Metric`/`Finding` 契约；不得将历史分类枚举用于创建活动规则；不得让非 KPI 文件触发普通规则；不使用真实包作为 Git 测试数据

**规模/范围**：删除 5 个规则包目录；活动普通规则从多类收缩到 1 条；配置仅保留 `kpi_all`；同步受影响的测试、E2E 和权威文档

## 宪法检查

*门禁：阶段 0 研究前通过；阶段 1 设计后再次检查。*

| 原则 | 设计结论 | 状态 |
| --- | --- | --- |
| 离线优先 | 仅删除本地规则与调整包内执行计划，不引入任何在线采集 | PASS |
| 一个包、一个任务 | 保留既有任务隔离、解压和输出目录模型 | PASS |
| 真实数据隔离 | 只使用固定合成 fixtures；不读取、修改、删除或暂存真实包/台账 | PASS |
| 契约驱动 | 不改变 API Schema 或版本；仅按现有字段语义调整历史读取行为并同步 OpenAPI 描述 | PASS |
| 模式同构 | CLI 与 API 继续共享注册表、执行器和结果契约 | PASS |
| 巡检器插件架构 | KPI 仍通过注册表加载；不向调度器硬编码业务逻辑 | PASS |
| 源文件显式匹配 | KPI 保留 `source_refs: [kpi_all]` 与展开后的 `source_patterns` | PASS |
| 增量重跑 | KPI 单规则重跑语义不变；已删除规则在注册表预检处拒绝 | PASS |
| 解压先行 | `pkg.extract.*` 全部保留为 hidden P0 基础设施 | PASS |
| 规则私有预处理 | 只保留 KPI 自身的 prepare（如存在）；不引入规则依赖 | PASS |
| 幂等与可追溯 | 历史规则 JSON 与 SQLite 行保持可读且不迁移；原包校验和不变 | PASS |

**阶段 1 后复审**：设计仅收缩注册与执行范围，不改变数据模型、调度阶段、解压安全策略或历史记录格式，宪法检查仍全部通过。

## 项目结构

### 文档（本功能）

```text
specs/037-kpi-only-rule-library/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── rule-library.md
└── tasks.md
```

### 源代码（仓库根目录）

```text
app/
├── inspectors/
│   ├── base.py                    # 保留
│   ├── registry.py                # 保留自动注册机制
│   ├── pkg.py                     # 保留 hidden pkg.extract.*
│   └── kpi/measurement.py         # 唯一活动普通规则
├── api/router.py                  # 历史结果读取与未注册规则行为
├── services/
│   ├── executor.py                # 继续由注册表生成执行计划
│   ├── tasks.py                   # 重跑/重建预检
│   ├── rule_states.py             # 只管理活动普通规则
│   └── inventory/                 # 台账链路不变
└── models/schemas.py              # 历史分类枚举与契约字段不变

deploy/config/
├── scan_rules.yaml                # 只保留 kpi_all，disabled_rules 为空
└── classify_rules.yaml            # 分类规则不变

tests/                             # KPI-only 契约、历史兼容、全流程回归
web/src/、web/e2e/                 # 历史详情兼容与 KPI-only 展示回归
docs/                              # 活动能力文档同步
```

**结构决策**：沿用现有单仓库后端/前端结构，不做目录迁移。硬删除 `app/inspectors/{alarm,config,log,resource,traffic}/`，不保留可导入的旧规则实现；历史能力仅由持久化数据和现有通用展示组件承载。

## 实现策略

1. **先写失败测试**：活动普通规则集合、注册表、API 目录、任务执行计划、历史读取、重跑拒绝和配置完整性。
2. **收缩注册与配置**：删除旧规则目录，最小化扫描组，更新历史读取路由。
3. **调整测试与样例语义**：活动路径改用 KPI；非 KPI 代码只出现在历史任务、注入式 executor 测试或分类/解压测试中。
4. **同步权威文档和 OpenAPI 描述**：明确 KPI-only 活动范围、隐藏解压规则和历史读取语义，不改 Schema。
5. **完整验证**：lint、test、verify、前端构建与相关 E2E；确认原包摘要、台账和 KPI 结果。

## 复杂度跟踪

无宪法违例，无额外复杂度。删除规则是比“停用配置/隐藏入口”更简单的实现，并直接满足 FR-002。
