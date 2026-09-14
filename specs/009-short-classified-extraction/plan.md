# 实现计划：分类短路径解压、长路径防护与准备状态展示

**分支**：`009-short-classified-extraction` | **日期**：2026-09-15 | **规格**：[spec.md](./spec.md)

**输入**：`specs/009-short-classified-extraction/spec.md`

## 摘要

本功能调整共享解压现场的分类落位：主包证据现场继续保留在 `.main/`，但日志、KPI、配置、告警、流量、资源和未分类工作文件直接落到对应分类根目录，不再额外插入来源子压缩包目录层。解压 manifest 升级为 v4，记录普通文件、子包和日志 gzip 的来源、目标、状态、冲突与路径限制明细。

在 Windows 传统 MAX_PATH 限制环境下，系统在创建目录或写入文件前检查解析后的完整目标路径；长度达到或超过 `260` 时按 `path_too_long` 提前拒绝，并清理该项半成品，不使用 `\\?\` 前缀改写，也不缩短 `task_id`。

在线 API 为任务列表和任务详情增加可选 `preparation` 读取模型。前端在任务列表页对应任务卡片内展示可折叠“数据准备”区域：成功默认折叠，失败、冲突或长路径默认展开。任务删除失败返回结构化 `task_delete_failed` 错误；前端完整提示展示 5 秒后收起，但任务卡片保留可重新展开的失败状态并支持重试。

## 技术上下文

**语言/版本**：Python 3.11+；Node.js 使用仓库当前前端工具链版本

**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、React、TypeScript、Vite、Ant Design

**存储**：文件现场 `uploads/<task_id>/` 与 `output/<task_id>/`；在线任务元数据使用 SQLite

**测试**：`pytest`；前端通过 `npm run build` 或后续关键交互测试验证

**目标平台**：macOS / Linux 开发与验证；Windows 用于传统路径限制行为，测试通过注入路径策略模拟

**项目类型**：离线巡检的 FastAPI + React Web 应用，同时提供本地 CLI 入口

**性能目标**：任务列表页准备状态组装不引入额外网络请求；单页 20 个任务的读取组装不重复扫描仓库

**约束条件**：

- 不连接被检系统、不做在线采集。
- 不修改 `task_id` 生成和既有任务身份。
- 不修改原始上传包。
- 不破坏 `RuleResult`、`Metric`、`Finding`、任务统计和 `/api/v2` 既有字段语义。
- 长路径不静默改写；完整路径 `>= 260` 时在传统限制环境下提前失败。
- 解压继续执行路径穿越、链接、重复路径、深度、文件数和总量防护。

**规模/范围**：单任务解压和状态展示，不新增规则，不扩展采集方式，不迁移历史任务现场。

## 宪法检查

*阶段 0 前检查*

| 原则 | 结论 | 说明 |
| --- | --- | --- |
| 离线优先 | 通过 | 只处理本地上传包或 `local_run/` 包，不新增外部连接。 |
| 一个包、一个任务 | 通过 | 只调整 `output/<task_id>/` 内部布局，`task_id` 和包隔离模型不变。 |
| 契约驱动 | 通过 | 先更新 `docs/api/openapi.yaml`，再更新 Pydantic、测试和生成客户端；新增字段可选。 |
| 模式同构 | 通过 | 解压、路径检查、manifest 和准备读取模型由 CLI/API 共享服务实现。 |
| 巡检器插件架构 | 通过 | 不新增普通规则；`pkg.extract.*` 仍是 hidden 前置规则，prepare 和普通规则依赖关系不变。 |
| 安全解压 | 通过 | 保留并强化既有预算、穿越、链接、重复路径与深度防护。 |
| 存储位置 | 通过 | 上传包、证据现场、结果、日志仍按 `task_id` 存储。 |
| 普通结果口径 | 通过 | `preparation` 是派生读取模型，不进入 `TaskStats` 或 `SystemInspection.rules`。 |
| 语言策略 | 通过 | 规划产物使用中文，字段和错误码使用英文。 |

*阶段 1 设计后复查*：新增 `preparation` 为可选公共字段，manifest 为内部模型；删除失败新增错误响应，不改变 `204/404/409` 既有语义。未发现宪法违规。

## 项目结构

### 文档（本功能）

```text
specs/009-short-classified-extraction/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
├── checklists/
│   └── requirements.md
├── demo/
│   ├── data-preparation-demo.html
│   ├── task-list-preparation-mockup.html
│   └── task-list-preparation-mockup.png
└── tasks.md              # 后续 speckit-tasks 生成
```

### 源代码（计划涉及的真实路径）

```text
app/
├── api/
│   └── router.py                       # 任务响应组装与删除失败异常映射
├── core/
│   └── archive.py                      # 保持安全解压；必要时补充路径限制错误转换
├── models/
│   ├── db.py                           # 删除失败后保证在线任务记录仍在，视设计细节可能调整列表读取
│   └── schemas.py                      # 新增 DataPreparation / PreparationItem / PreparationIssue 模型
├── services/
│   ├── extraction/
│   │   ├── layout.py                   # manifest v4、分类路径、路径限制与冲突 helper
│   │   ├── manifest.py                 # v4 读取、校验、复用
│   │   ├── nested.py                   # 子包、gzip、普通文件直接分类落位
│   │   └── site.py                     # 主包证据现场与分类现场编排
│   ├── preparation.py                  # 新增：manifest + hidden 结果组装数据准备读取模型
│   ├── tasks.py                        # 删除失败结构化、删除顺序与任务列表准备状态
│   └── store.py                        # 仅在需要时补充隐藏规则结果读取 helper
└── inspectors/
    └── pkg.py                          # hidden 解压结果细节保持与 manifest v4 对齐

web/
├── src/
│   ├── api/
│   │   ├── client.ts                   # 由 OpenAPI 重新生成
│   │   └── http.ts                     # 结构化删除错误 detail 解析
│   └── pages/
│       └── TaskListPage.tsx            # 数据准备折叠区与删除失败行内状态

tests/
├── test_extraction_site.py
├── test_extraction_policy.py
├── test_extraction_package.py
├── test_api.py
├── test_delete_race.py
└── test_contract.py
```

**结构决策**：沿用现有 `app` + `web` 前后端结构。新增逻辑放在 `app/services/preparation.py`，避免把展示组装塞进 API 路由或巡检器；解压细节继续收敛在 `app/services/extraction/`。

## 设计方案

### 1. 分类现场布局

- 主包先安全解压到 `.main/`，证据现场不变。
- 从 `.main/` 稳定排序处理证据文件：
  - 普通文件按分类写入 `<category>/<原始内部相对路径>`。
  - `.log.gz` 解压到 `<category>/<原始内部相对去后缀路径>`。
  - 子压缩包解压到 `<category>/<子包内部相对结构>`，不再插入来源包名或来源目录层。
- 嵌套子包成员继续按分类规则落入同一个分类根，不新增父包目录层。
- 目标路径已存在时不覆盖：
  - 普通文件和日志 gzip 记录 `conflict`，并保留可读冲突上下文。
  - 子压缩包根目录冲突记录 `conflict`，不再生成 checksum 后缀目录。
- 相同 checksum 子包仍按 `duplicate` 跳过。

### 2. manifest v4 与解压策略

- `MANIFEST_VERSION` 从 `3` 升级为 `4`。
- 新增 `files[]` 记录普通分类文件成功、冲突、拒绝状态。
- 子包、日志 gzip、普通文件统一补充 `error_code`、可选 `path_length` 和 `path_limit`。
- manifest 校验不通过或版本不匹配时重建整个分类现场；不迁移历史布局。
- `.main/` 证据现场继续保留，主包 checksum 不匹配时替换证据现场。
- 继续加载 `deploy/config/extract_policy.yaml`，保留 `nested.skip_all`、`nested.skip_paths`、白名单路径、白名单关键词和 policy fingerprint。
- manifest 复用判断比较主包 checksum、policy fingerprint 和路径限制上下文/指纹；任一变化时按 v4 重建。
- 被策略跳过的子包和日志 gzip 继续使用 `skipped` 语义，数据准备展示为 `skip`；被白名单恢复的来源保留策略上下文。

### 3. Windows 长路径前置防护

- 新增路径限制策略对象，检查解析后的完整目标路径长度；路径限制上下文参与 manifest 复用指纹。
- 仅在 Windows 且长路径支持未启用时强制 `260`；注册表不可读时保守按传统限制处理。
- 非 Windows 平台不启用该阈值；单元测试通过注入策略模拟 `path_length=279`。
- 检查时机：
  - 主包 `.main/` 证据目标创建或复制前；主包证据现场长路径失败作为主包解压失败并阻断后续 prepare/巡检；
  - 普通文件 copy 前；
  - 日志 gzip 创建目标前；
  - 子压缩包目标目录创建前；
  - 子压缩包 staging 成员 rename 到最终分类现场前。
- 失败记录 `error_code=path_too_long`、实际长度、上限、来源和目标，并清理 staging 或未写入目标。
- 不使用 `\\?\` 前缀，不缩短文件名，不修改 `task_id`。

### 4. 数据准备读取模型

- 新增 `app/services/preparation.py`。
- 输入：
  - `.patrolx-extracted.json`；
  - `rules/pkg.extract.*.json` 中的 hidden 结果耗时；
  - 任务状态。
- 输出 `DataPreparation`：
  - 主包项 + 七个分类项；
  - 分类无来源时为 `skip`；
  - 有冲突为 `warn`；
  - 有失败或写入前拒绝为 `fail`；
  - 主包失败或 manifest 损坏为 `error`。
- `GET /api/v2/tasks` 和 `GET /api/v2/tasks/{task_id}` 返回可选 `preparation`。
- `TaskStats`、`SystemInspection.rules` 和报告中的普通规则列表不变。

### 5. 任务删除失败

- `TaskService.delete()` 优先删除文件现场；数据库记录在两个现场都删除成功后才删除。
- 删除失败抛出 `TaskDeleteError`，包含任务 ID、尝试位置、失败路径、可选路径长度和上限。
- API 映射为 `500 task_delete_failed`；`409 task_busy` 与 `404 not_found` 保持不变。
- 本地任务失败后恢复 `task.json`，保证任务仍能出现在列表。
- 在线任务失败时数据库记录仍在；列表 fallback 不再只覆盖 pending/running，确保完成态任务在部分删除后仍可见。
- 前端保存当前页面的删除错误状态：
  - 完整 Alert 展示 5 秒；
  - 收起后保留“删除失败”状态；
  - 可重新展开；
  - 重试成功后清除状态并刷新列表。

## 宪法复杂度

未发现需要豁免的架构复杂度。数据库 fallback 仅调整现有任务列表读取条件，不新增第二套存储模型。

## 验证策略

- **单元测试**：
  - 分类落位不再包含来源子包目录层；
  - 内部相对结构保留；
  - 目标冲突不覆盖且顺序稳定；
  - checksum 重复跳过；
  - 长路径前置拒绝和半成品清理；
  - manifest v4 读写与失效重建。
- **契约测试**：
  - OpenAPI 包含新增可选字段和 `task_delete_failed`；
  - Pydantic 与 OpenAPI 一致；
  - 生成客户端包含新类型。
- **API 测试**：
  - 任务列表和详情返回 `preparation`；
  - 历史任务可返回 `null`；
  - 删除成功仍为 `204`；
  - 删除失败返回结构化 detail 且任务仍可列出。
- **前端验证**：
  - TaskListPage 不把 `pkg.extract.*` 加入普通规则统计；
  - 成功折叠、失败展开；
  - 删除失败 5 秒收起、状态可展开、重试成功后清除。
- **全流程**：`python build.py verify`。

## 质量门禁

实现分支内至少执行：

```bash
python build.py contract
python build.py gen-web-api
python build.py lint
python build.py test
python build.py verify
cd web && npm run build
```
