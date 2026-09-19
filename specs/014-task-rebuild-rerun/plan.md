# 实现计划：任务重建重跑

**分支**：`feature/014-task-rebuild-rerun` | **日期**：2026-09-19 | **规格**：[spec.md](spec.md)

**输入**：`specs/014-task-rebuild-rerun/spec.md` 定义的全量/增量重建重跑能力。

## 摘要

为既有任务新增显式“重建重跑”能力，并与普通重跑保持语义分离。全量重建在预检通过后清除任务输出目录，从原始上传包重新执行解压、KPI 快照、规则准备和全部普通规则；增量重建强制重建解压现场，但备份并恢复既有任务 KPI 快照，只重跑指定普通规则并保留未选择规则结果。接口使用独立 `/api/v2/tasks/{task_id}/rebuild`，前端提供全量重建确认和规则级增量重建入口。

## 技术上下文

**语言/版本**：Python 3.11+，TypeScript 5.x  
**主要依赖**：FastAPI、Pydantic v2、SQLAlchemy、pandas/pyarrow、React 18、Ant Design 5、Vite  
**存储**：`uploads/` 原始包、`output/<task_id>/` 任务现场、SQLite 任务元数据  
**测试**：pytest、OpenAPI/Pydantic 契约校验、Vitest/Node test、Vite build；涉及全流程时使用 `python build.py verify`  
**目标平台**：桌面浏览器访问的在线 API + 本地/在线双模式 Python 服务  
**性能目标**：不新增常驻轮询；重建吞吐继承既有解压和规则执行性能  
**约束条件**：离线巡检；原始包不可修改；一个包、一个任务、一个输出目录；规则结果契约字段语义不变  
**规模/范围**：单任务单次重建，不做定时、批量或在线采集

## 宪法检查

- 离线优先：通过。重建只读取既有原始上传包，不连接被检系统。
- 一个包、一个任务、一个输出目录：通过。重建仍使用同一 `task_id` 和同一输出目录。
- 契约驱动：通过。先更新 `docs/api/openapi.yaml`，再同步 Pydantic、API、生成客户端和前端调用。
- 模式同构：通过。重建执行器复用 `app/cli.py` 和共享 `Executor`；本地与在线共用输出契约。
- 巡检器插件架构：通过。不新增规则间依赖；增量重建只执行用户指定普通规则及其私有 prepare。
- 安全解压：通过。复用安全解压、路径限制、资源预算和 manifest。
- 观测性：通过。重建开始/完成/失败写入 `execution.log`，并携带模式和目标规则。
- UTC 存储：通过。新增日志字段不新增时间格式；时间继续使用 `*_at` / `ts`。

## 设计决策

### API 与请求

新增：

```http
POST /api/v2/tasks/{task_id}/rebuild
202
Location: /api/v2/tasks/{task_id}
```

请求：

```json
{
  "mode": "full",
  "confirmed": true,
  "trigger_source": "ui"
}
```

增量：

```json
{
  "mode": "incremental",
  "rule_codes": ["log.error_density"],
  "confirmed": true,
  "trigger_source": "ui"
}
```

约束：

- `mode` 只允许 `full` / `incremental`。
- `confirmed` 必须为 `true`；这是 API 层的破坏性动作门槛。
- `trigger_source` 默认 `ui`，允许 `api`，用于任务日志追踪。
- 全量请求不得携带规则列表；增量请求规则列表必须去重且全部为普通规则。
- 既有 `/api/v2/tasks/{task_id}/rerun` 请求和响应契约不变。

### 状态与预检

重建受理前校验：

1. 任务存在于 `output/<task_id>/task.json` 且包含系统结果。
2. 任务状态为 `completed` 或 `failed`；`pending`、`running` 拒绝。
3. 任务未处于活跃执行或删除取消集合。
4. 原始包存在、可读且非空。
5. 规则 code 存在且不是隐藏规则。
6. 增量重建的任务 KPI 快照存在且可解析。
7. 全量重建依赖的当前 KPI 基础配置可加载。

预检失败不清理输出。

### 全量重建流程

1. 读取旧任务元数据和包信息，完成预检。
2. 删除 `output/<task_id>`；不删除 `uploads/<task_id>`。
3. 记录“全量重建重跑开始”。
4. 调用共享 `run_task`；解压后由 `load_task_kpi_config` 按当前配置生成新快照。
5. 执行全部规则私有 prepare 和普通规则。
6. 更新规则结果、`system.json`、`task.json`、摘要和报告。
7. 任务完成/失败状态由 `TaskService` 统一更新。

### 增量重建流程

1. 读取旧任务元数据和包信息，完成预检。
2. 读取并备份 `kpi/kpi_catalog_snapshot.json`。
3. 删除解压 manifest 和工作分类目录，强制从原始包重新解压。
4. 解压完成后恢复既有 KPI 快照，防止 `load_task_kpi_config` 意外按当前配置重建。
5. 对每个目标普通规则执行其私有 prepare 与规则；不执行其他 prepare。
6. 保留未选择规则 JSON、`system.json` 中未选择结果和既有快照。
7. 重新汇总任务摘要、系统结果、`task.json` 和报告。
8. 失败时任务呈现失败；不把目标规则部分执行展示为完成。

## 项目结构

```text
app/
├── api/router.py                     # 新增 rebuild 端点与错误映射
├── cli.py                            # 新增共享重建规则执行函数
├── models/schemas.py                 # 新增 RebuildMode/RebuildRequest
├── services/
│   ├── executor.py                   # 新增强制重建解压现场能力
│   ├── kpi_catalog.py                # 新增快照只读校验/恢复辅助
│   └── tasks.py                      # 新增 rebuild 预检、入队与执行分支
docs/
└── api/openapi.yaml                  # 契约先行的 rebuild API
tests/
└── test_task_rebuild.py              # 服务、契约、保护语义测试
web/src/
├── api/http.ts                       # 类型化 rebuild 调用
├── pages/TaskListPage.tsx            # 全量重建入口
└── pages/TaskDetailPage.tsx          # 增量重建入口
```

**结构决策**：沿用现有分层 `api → services → cli/inspectors/models`，不新增独立重建子系统。

## 复杂度跟踪

无宪法违规。
