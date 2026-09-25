import { useCallback, useMemo } from "react";
import { Alert, Button, Card, Tabs } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import type { RuleStatus } from "../api/http";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { useAuth } from "../auth/AuthContext";
import { useTaskDetailData } from "../hooks/useTaskDetailData";
import { useTaskDetailFilters } from "../hooks/useTaskDetailFilters";
import { useTaskActions } from "../hooks/useTaskActions";
import { TaskDetailBreadcrumb, TaskDetailHeader } from "../components/task-detail/TaskDetailHeader";
import { TaskHealthPanel } from "../components/task-detail/TaskHealthPanel";
import { TaskMetaPanel } from "../components/task-detail/TaskMetaPanel";
import { RuleBrowser } from "../components/task-detail/RuleBrowser";
import { TaskLogsPanel } from "../components/task-detail/TaskLogsPanel";
import { TaskReportPanel } from "../components/task-detail/TaskReportPanel";
import { DeviceModal, RebuildModal } from "../components/task-detail/TaskActionModals";
import { latestTaskFailure } from "../utils/taskFailure";
import {
  filterRuleResults,
  getAttentionDisplayRules,
  getRuleCategoryOptions,
  sortRuleResultsByFocus,
  type RuleSortMode,
} from "../utils/ruleResults";
import { countByStatus, filterByStatus, toggleStatusFilter } from "../utils/taskFilter";
import type { TaskDetailTab } from "../utils/taskDetailFilters.ts";

export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();
  const { filters, updateFilters } = useTaskDetailFilters();

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
  const attention = useMemo(() => getAttentionDisplayRules(rules, 5), [rules]);
  const failure = useMemo(() => latestTaskFailure(logEntries), [logEntries]);

  if (loading && !task) {
    return <PageSkeleton rows={5} />;
  }

  if (!task) {
    if (taskError) {
      return <LoadErrorState description={taskError} onRetry={() => void reload()} retrying={loading} />;
    }
    return <EmptyState description="任务不存在" />;
  }

  return (
    <div>
      <TaskDetailBreadcrumb />
      <TaskDetailHeader
        task={task}
        busy={busy}
        canRebuild={!!canRebuild}
        rebuilding={actions.rebuild.rebuilding}
        onOpenReport={() => navigate(`/tasks/${taskId}/report`)}
        onOpenLogs={() => navigate(`/tasks/${taskId}/logs`)}
        onRerunAll={() => void actions.rerunAll()}
        onOpenRebuild={actions.rebuild.openModal}
        onBack={() => navigate("/tasks")}
      />

      <Card className="task-detail-panel">
        <TaskHealthPanel
          stats={task.stats}
          statusCounts={statusCounts}
          activeStatus={statusFilter}
          attentionTotal={attention.rules.length + attention.hiddenCount}
          attentionHiddenCount={attention.hiddenCount}
          onStatusClick={handleStatusClick}
        />
        <TaskMetaPanel
          task={task}
          system={system}
          deviceEditable={isAdmin && !busy}
          onEditDevice={actions.device.openModal}
        />
      </Card>

      {task.status === "failed" && failure && (
        <Alert type="error" showIcon message={`任务失败：${failure}`} className="task-detail-alert" />
      )}
      {systemError && (
        <Alert
          type="warning"
          showIcon
          message="系统结果加载失败"
          description={systemError}
          action={
            <Button size="small" loading={loading} onClick={() => void reload()}>
              重试
            </Button>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      <Tabs
        activeKey={filters.tab}
        onChange={handleTabChange}
        items={[
          {
            key: "rules",
            label: "规则结果",
            children: (
              <RuleBrowser
                attentionRules={attention.rules}
                attentionHiddenCount={attention.hiddenCount}
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
            ),
          },
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
            key: "report",
            label: "报告预览",
            children: <TaskReportPanel taskId={taskId} />,
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
