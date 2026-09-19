# 研究记录：任务重建重跑

## 结论

1. **API 版本**：采用 `/api/v2/tasks/{task_id}/rebuild`。现有任务主资源已经是 `/api/v2`，新增端点不改变既有字段语义，也不需要 `/api/v1` 或 `/api/v3`。规格中的 `/api/v1` 是计划期修正。
2. **普通重跑边界**：`TaskService.rerun` 继续只设置规则计划并复用有效解压现场；不清理输出、不刷新有效 KPI 快照。
3. **全量重建**：预检后删除 `output/<task_id>`，再调用共享 `run_task`。`run_task` 已在解压后调用 `load_task_kpi_config`，快照缺失时会基于当前配置生成新快照。
4. **增量重建**：不能直接调用 `extract_main_site` 后继续执行，因为它会清空 `kpi/` 工作目录并删除快照。必须先备份快照，强制重建分类工作现场，解压完成后恢复快照。
5. **状态防护**：复用 `TaskService._active_task`、`_cancelled`、`_lock` 和任务状态判断。重建只允许 `completed` / `failed` 任务，`pending` / `running` 拒绝。
6. **规则选择**：只允许普通规则。隐藏规则 `pkg.extract.*` 由重建流程自动执行，不作为用户目标。
7. **KPI 快照**：全量快照重新生成；增量快照只读使用。损坏或缺失的增量快照在预检阶段拒绝。

## 代码证据

- `app/services/tasks.py` 当前普通重跑通过 `_rerun_plan` 调用 `run_single_rule`。
- `app/services/executor.py` 的 `run_rule_with_deps` 会复用有效 manifest。
- `app/services/extraction/site.py` 的解压流程会重建 `WORK_CATEGORIES`，包括 `kpi`。
- `app/services/kpi_catalog.py` 的 `load_task_kpi_config` 在快照缺失时按当前配置补写。
- `app/api/router.py` 已有 `/api/v2/tasks/{task_id}/rerun`，返回 `TaskCreated`。
