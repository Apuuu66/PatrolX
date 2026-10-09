import { useCallback, useMemo, useState } from "react";
import { Alert, Button, Card, Collapse, Descriptions, Tabs, Typography } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import type { RuleStatus } from "../api/http";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { useAuth } from "../auth/AuthContext";
import { useTaskDetailData } from "../hooks/useTaskDetailData";
import { useTaskDetailFilters } from "../hooks/useTaskDetailFilters";
import { useTaskActions } from "../hooks/useTaskActions";
import { ConclusionHero } from "../components/ConclusionHero";
import { RuleResultTable } from "../components/RuleResultTable";
import { TaskDetailBreadcrumb, TaskDetailMoreMenu } from "../components/task-detail/TaskDetailHeader";
import { TaskMetaPanel } from "../components/task-detail/TaskMetaPanel";
import { RuleBrowser } from "../components/task-detail/RuleBrowser";
import { TaskLogsPanel } from "../components/task-detail/TaskLogsPanel";
import { TaskReportPanel } from "../components/task-detail/TaskReportPanel";
import { TaskInventoryPanel } from "../components/task-detail/TaskInventoryPanel";
import { DeviceModal, RebuildModal } from "../components/task-detail/TaskActionModals";
import { getPreparationDisplay } from "../utils/preparationDisplay";
import { latestTaskFailure } from "../utils/taskFailure";
import {
  filterRuleResults,
  getRuleCategoryOptions,
  getSortedAttentionRules,
  sortRuleResultsByFocus,
  type RuleSortMode,
} from "../utils/ruleResults";
import { countByStatus, filterByStatus, toggleStatusFilter } from "../utils/taskFilter";
import type { TaskDetailTab } from "../utils/taskDetailFilters.ts";

/** 「重点关注」默认可见条数，其余折叠（FR-016）。 */
const ATTENTION_PREVIEW_LIMIT = 5;

export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();
  const { filters, updateFilters } = useTaskDetailFilters();
  const [attentionExpanded, setAttentionExpanded] = useState(false);

  const { data, loading, busy, reload } = useTaskDetailData(taskId);
  const task = data?.task.status === "ready" ? data.task.data : null;
  const taskError = data?.task.status === "error" ? data.task.message : null;
  const system = data?.system.status === "ready" ? data.system.data : null;
  const systemError = data?.system.status === "error" ? data.system.message : null;
  const logEntries = data?.logs.status === "ready" ? data.logs.data : [];
  const logError = data?.logs.status === "error" ? data.logs.message : null;
  const hidden = data?.hiddenRuleCodes ?? new Set<string>();

  const actions = useTaskActions(taskId, reload);
  const canRebuild = task?.status === "completed" || task?.status === "failed";
  const statusFilter = filters.status;

  const handleStatusClick = useCallback(
    (status: RuleStatus) => {
      updateFilters({ status: toggleStatusFilter(filters.status, status) });
    },
    [filters.status, updateFilters],
  );

  const handleTabChange = useCallback(
    (tab: string) => {
      updateFilters({ tab: tab as TaskDetailTab });
    },
    [updateFilters],
  );

  const openRule = useCallback(
    (ruleCode: string) => {
      navigate(`/tasks/${taskId}/rules/${ruleCode}`);
    },
    [navigate, taskId],
  );

  const rules = useMemo(
    () => (system?.rules ?? []).filter((rule) => !hidden.has(rule.code)),
    [system, hidden],
  );
  const statusCounts = useMemo(() => countByStatus(rules), [rules]);
  const filteredRules = useMemo(
    () => filterRuleResults(filterByStatus(rules, filters.status), { search: filters.search }),
    [rules, filters.status, filters.search],
  );
  const categoryCounts = useMemo(
    () => getRuleCategoryOptions(rules, filteredRules),
    [rules, filteredRules],
  );
  const sortedRules = useMemo(
    () => sortRuleResultsByFocus(filteredRules, filters.category, filters.sort),
    [filteredRules, filters.category, filters.sort],
  );
  const attentionRules = useMemo(() => getSortedAttentionRules(rules), [rules]);
  const failure = useMemo(() => latestTaskFailure(logEntries), [logEntries]);

  if (loading && !task) {
    return <PageSkeleton rows={5} />;
  }

  if (!task) {
    if (taskError) {
      return <LoadErrorState description={taskError} onRetry={() => void reload()} retrying={loading} />;
    }
    return (
      <EmptyState
        description="任务不存在"
        action={
          <Button type="primary" onClick={() => navigate("/tasks")}>
            返回任务列表
          </Button>
        }
      />
    );
  }

  // 主包解压失败等场景不会生成规则结果，此时不展示空规则表格（边界情况、FR-019）。
  const rulesUnavailable = task.status === "failed" && rules.length === 0;
  const visibleAttentionRules = attentionExpanded
    ? attentionRules
    : attentionRules.slice(0, ATTENTION_PREVIEW_LIMIT);
  const attentionHiddenCount = attentionRules.length - visibleAttentionRules.length;

  return (
    <div>
      <TaskDetailBreadcrumb />

      <ConclusionHero
        task={task}
        system={system}
        statusCounts={statusCounts}
        activeStatus={statusFilter}
        onStatusClick={handleStatusClick}
        failureReason={failure}
        onOpenReport={() => navigate(`/tasks/${taskId}/report`)}
        onOpenLogs={() => navigate(`/tasks/${taskId}/logs`)}
        extraActions={
          <TaskDetailMoreMenu
            busy={busy}
            canRebuild={!!canRebuild}
            rebuilding={actions.rebuild.rebuilding}
            onOpenLogs={() => navigate(`/tasks/${taskId}/logs`)}
            onRerunAll={() => void actions.rerunAll()}
            onOpenRebuild={actions.rebuild.openModal}
            onBack={() => navigate("/tasks")}
          />
        }
      />

      {systemError && !rulesUnavailable && (
        <Alert
          type="warning"
          showIcon
          message="系统结果加载失败"
          description={systemError}
          className="task-detail-alert"
          action={
            <Button size="small" loading={loading} onClick={() => void reload()}>
              重试
            </Button>
          }
        />
      )}

      {/* 解压失败等场景没有规则结果：失败阶段、原因与日志入口由结论 Hero 承担，
          规则区不渲染空表格，也不重复表达同一事实（FR-019、SC-005）。 */}
      {!rulesUnavailable && (
        <>
          {attentionRules.length > 0 && (
            <Card
              title={`重点关注（${attentionRules.length}）`}
              className="task-detail-panel"
              data-testid="attention-panel"
              extra={
                attentionHiddenCount > 0 || attentionExpanded ? (
                  <Button type="link" size="small" onClick={() => setAttentionExpanded((value) => !value)}>
                    {attentionExpanded ? "收起" : `展开其余 ${attentionHiddenCount} 条`}
                  </Button>
                ) : null
              }
            >
              <RuleResultTable
                rules={visibleAttentionRules}
                onOpenRule={openRule}
                onRerunRule={(ruleCode) => void actions.rerunOne(ruleCode)}
              />
            </Card>
          )}

          <RuleBrowser
            categoryCounts={categoryCounts}
            sortedRules={sortedRules}
            statusFilter={statusFilter}
            search={filters.search}
            sort={filters.sort}
            category={filters.category}
            onSearchChange={(search) => updateFilters({ search })}
            onSortChange={(sort) => updateFilters({ sort: sort as RuleSortMode })}
            onCategoryChange={(category) => updateFilters({ category })}
            onOpenRule={openRule}
            onRerunRule={(ruleCode) => void actions.rerunOne(ruleCode)}
          />
        </>
      )}

      <Tabs
        className="task-detail-tabs"
        activeKey={filters.tab === "rules" ? "" : filters.tab}
        onChange={handleTabChange}
        items={[
          {
            key: "logs",
            label: "执行日志",
            children: (
              <TaskLogsPanel
                logs={logEntries}
                error={logError}
                onRetry={() => void reload()}
                retrying={loading}
              />
            ),
          },
          {
            key: "inventory",
            label: "设备台账",
            children: <TaskInventoryPanel task={task} />,
          },
          {
            key: "report",
            label: "报告预览",
            children: <TaskReportPanel taskId={taskId} />,
          },
        ]}
      />

      <Collapse
        className="task-technical-collapse"
        data-testid="technical-collapse"
        items={[
          {
            key: "technical",
            label: "执行与技术信息",
            children: (
              <div className="task-technical-body">
                <Descriptions
                  size="small"
                  column={3}
                  items={[
                    {
                      key: "task_id",
                      label: "任务 ID",
                      children: (
                        <Typography.Text copyable={{ text: task.task_id }}>{task.task_id}</Typography.Text>
                      ),
                    },
                    {
                      key: "preparation",
                      label: "数据准备",
                      children: task.preparation ? getPreparationDisplay(task.preparation).summary : "-",
                    },
                    {
                      key: "stats",
                      label: "规则统计",
                      children: `共 ${task.stats.total} 条 · 通过 ${task.stats.pass} · 告警 ${task.stats.warn} · 失败 ${task.stats.fail} · 异常 ${task.stats.error} · 跳过 ${task.stats.skip}`,
                    },
                  ]}
                />
                <TaskMetaPanel
                  task={task}
                  system={system}
                  deviceEditable={isAdmin && !busy}
                  onEditDevice={actions.device.openModal}
                />
              </div>
            ),
          },
        ]}
      />

      <RebuildModal
        open={actions.rebuild.open}
        confirming={actions.rebuild.rebuilding}
        rules={rules}
        ruleCodes={actions.rebuild.ruleCodes}
        onRuleCodesChange={actions.rebuild.setRuleCodes}
        onCancel={actions.rebuild.closeModal}
        onConfirm={() => void actions.rebuild.rebuild()}
      />
      <DeviceModal
        open={actions.device.open}
        value={actions.device.value}
        saving={actions.device.saving}
        onChange={actions.device.setValue}
        onCancel={actions.device.closeModal}
        onSave={() => void actions.device.save()}
      />
    </div>
  );
}
