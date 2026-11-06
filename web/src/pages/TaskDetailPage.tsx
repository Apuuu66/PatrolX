import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, App, Button, Card, Collapse, Descriptions, Flex, Tag, Tabs, Typography } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type DataPreparation,
  type KpiTaskSummaryV6,
  type PreparationItem,
  type RuleStatus,
} from "../api/http";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { DensitySegmented } from "../components/DensitySegmented";
import { useTableDensity } from "../hooks/useTableDensity";
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
import { categoryLabel, getPreparationDisplay } from "../utils/preparationDisplay";
import { latestTaskFailure } from "../utils/taskFailure";
import {
  filterRuleResults,
  getSortedAttentionRules,
  sortRuleResultsByFocus,
  type RuleSortMode,
} from "../utils/ruleResults";
import { countByStatus, filterByStatus, toggleStatusFilter } from "../utils/taskFilter";
import type { TaskDetailTab } from "../utils/taskDetailFilters.ts";

/** 「重点关注」默认可见条数，其余折叠（FR-016）。 */
const ATTENTION_PREVIEW_LIMIT = 5;

const PREPARATION_STATUS_LABELS: Record<PreparationItem["status"], string> = {
  pass: "通过",
  warn: "警告",
  fail: "失败",
  error: "错误",
  skip: "跳过",
};

const PREPARATION_STATUS_COLORS: Record<PreparationItem["status"], string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
  error: "default",
  skip: "blue",
};

function PreparationUnits({ preparation }: { preparation: DataPreparation }) {
  const display = getPreparationDisplay(preparation);
  return (
    <div className="task-preparation-units" data-testid="preparation-units">
      {display.items.map((item) => (
        <div
          key={item.code}
          className="task-preparation-unit"
          data-testid={`preparation-${item.code}`}
        >
          <Flex align="center" gap={8} wrap>
            <Typography.Text strong>{categoryLabel(item.category)}</Typography.Text>
            <Tag color={PREPARATION_STATUS_COLORS[item.status]}>{PREPARATION_STATUS_LABELS[item.status]}</Tag>
            {item.total_count > 0 && (
              <Typography.Text type="secondary">
                {item.extracted_count}/{item.total_count}
              </Typography.Text>
            )}
          </Flex>
          <Typography.Text>{item.summary}</Typography.Text>
          {(item.issues ?? []).map((issue, index) => (
            <Typography.Text key={`${issue.type}-${index}`} type="secondary" className="task-preparation-issue">
              {issue.reason}
            </Typography.Text>
          ))}
        </div>
      ))}
    </div>
  );
}

export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const { filters, updateFilters } = useTaskDetailFilters();
  const [attentionExpanded, setAttentionExpanded] = useState(false);
  const [kpiSummary, setKpiSummary] = useState<KpiTaskSummaryV6 | null>(null);
  const [kpiLoading, setKpiLoading] = useState(false);
  const [kpiError, setKpiError] = useState<{ code?: string; message: string } | null>(null);
  const { density, tableSize, setDensity } = useTableDensity();

  const { data, loading, busy, reload } = useTaskDetailData(taskId);
  const task = data?.task.status === "ready" ? data.task.data : null;
  const taskError = data?.task.status === "error" ? data.task.message : null;
  const system = data?.system.status === "ready" ? data.system.data : null;
  const systemError = data?.system.status === "error" ? data.system.message : null;
  const logEntries = data?.logs.status === "ready" ? data.logs.data : [];
  const logError = data?.logs.status === "error" ? data.logs : null;
  const hidden = data?.hiddenRuleCodes ?? new Set<string>();

  const actions = useTaskActions(taskId, reload);
  const canRebuild = task?.status === "completed" || task?.status === "failed";
  const statusFilter = filters.status;

  const loadKpiSummary = useCallback(async () => {
    if (!user) {
      setKpiSummary(null);
      setKpiError(null);
      setKpiLoading(false);
      return;
    }
    setKpiLoading(true);
    setKpiError(null);
    try {
      setKpiSummary(await api.getKpiTaskSummaryV6(taskId));
    } catch (error) {
      setKpiSummary(null);
      setKpiError({
        code: error instanceof ApiError ? error.code : undefined,
        message: error instanceof Error ? error.message : "KPI 巡检结果加载失败",
      });
    } finally {
      setKpiLoading(false);
    }
  }, [taskId, user]);

  useEffect(() => {
    if (task?.status !== "completed" && task?.status !== "failed") {
      setKpiSummary(null);
      setKpiError(null);
      return;
    }
    if (!user) {
      setKpiSummary(null);
      setKpiError(null);
      setKpiLoading(false);
      return;
    }
    void loadKpiSummary();
  }, [loadKpiSummary, task?.status, user]);

  const confirmKpiRebuild = useCallback(() => {
    modal.confirm({
      title: "重建该任务？",
      content:
        "将删除并重建任务输出，重新解压并重算全部规则和 KPI 快照；该操作不可撤销。原始上传包只读，不会被修改。",
      okText: "重建",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await api.rebuildTask(taskId, {
            mode: "full",
            confirmed: true,
            trigger_source: "ui",
          });
          message.success("已受理重建");
          await reload();
          await loadKpiSummary();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "重建失败");
          throw error;
        }
      },
    });
  }, [loadKpiSummary, message, modal, reload, taskId]);

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
  const sortedRules = useMemo(
    () => sortRuleResultsByFocus(filteredRules, filters.category, filters.sort),
    [filteredRules, filters.category, filters.sort],
  );
  const attentionRules = useMemo(() => getSortedAttentionRules(rules), [rules]);
  const attentionRuleCodes = useMemo(
    () => attentionRules.map((rule) => rule.code),
    [attentionRules],
  );
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
  const kpiScopeNotice =
    kpiSummary && !kpiSummary.rule_scope.has_executable_rules
      ? kpiSummary.network_element_type === null
        ? "未选择规则适用网元类型"
        : kpiSummary.rule_scope.notice || "当前网元类型未配置可执行业务规则"
      : null;

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
        scopeNotice={kpiScopeNotice}
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

      {kpiError?.code === "task_result_requires_rebuild" ? (
        <Alert
          type="warning"
          showIcon
          className="task-detail-alert"
          data-testid="task-kpi-rebuild-required"
          message="任务结果需要重建"
          description={
            <span>
              task_result_requires_rebuild：{kpiError.message}。旧任务不迁移结果，需按当前规则和 KPI 配置全量重建。
            </span>
          }
          action={
            <Button danger onClick={confirmKpiRebuild}>
              重建任务
            </Button>
          }
        />
      ) : kpiError ? (
        <Alert
          type="error"
          showIcon
          className="task-detail-alert"
          data-testid="task-kpi-load-error"
          message="KPI 巡检结果加载失败"
          description={kpiError.message}
          action={
            <Button size="small" loading={kpiLoading} onClick={() => void loadKpiSummary()}>
              重试
            </Button>
          }
        />
      ) : kpiSummary ? (
        <Card
          title="KPI 巡检结果"
          className="task-detail-panel task-kpi-entry"
          data-testid="task-kpi-entry"
          extra={
            <Button type="primary" onClick={() => navigate(`/tasks/${taskId}/kpi`)}>
              查看 KPI 巡检结果
            </Button>
          }
        >
          <Flex align="center" gap={20} wrap>
            <Tag color={kpiSummary.network_element_type ? "blue" : "default"}>
              {kpiSummary.network_element_type ?? "未选择规则适用网元类型"}
            </Tag>
            <Typography.Text type="secondary">
              数据日期 {kpiSummary.data_date ?? "暂无"}
            </Typography.Text>
            <Typography.Text>启用测量单元 {kpiSummary.counts.enabled_measurement_unit_count}</Typography.Text>
            <Typography.Text>全部指标 {kpiSummary.counts.all_metric_count}</Typography.Text>
            <Typography.Text>团队关注 {kpiSummary.counts.team_focus_count}</Typography.Text>
            <Typography.Text strong>需要处理 {kpiSummary.counts.needs_attention_count}</Typography.Text>
          </Flex>
          {kpiScopeNotice ? (
            <Typography.Paragraph type="secondary" className="task-kpi-scope-notice">
              {kpiScopeNotice}。未执行普通业务规则，不生成通过或跳过结论。
            </Typography.Paragraph>
          ) : null}
        </Card>
      ) : null}

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
                <Flex align="center" gap={12} wrap>
                  <DensitySegmented value={density} onChange={setDensity} />
                  {(attentionHiddenCount > 0 || attentionExpanded) && (
                    <Button type="link" size="small" onClick={() => setAttentionExpanded((value) => !value)}>
                      {attentionExpanded ? "收起" : `展开其余 ${attentionHiddenCount} 条`}
                    </Button>
                  )}
                </Flex>
              }
            >
              <RuleResultTable
                rules={visibleAttentionRules}
                density={density}
                tableSize={tableSize}
                onOpenRule={openRule}
                onRerunRule={(ruleCode) => void actions.rerunOne(ruleCode)}
              />
            </Card>
          )}

          <RuleBrowser
            sortedRules={sortedRules}
            attentionRuleCodes={attentionRuleCodes}
            categorySourceRules={rules}
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
                      children: task.preparation ? <PreparationUnits preparation={task.preparation} /> : "-",
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
        error={actions.device.error}
        onChange={actions.device.setValue}
        onCancel={actions.device.closeModal}
        onSave={() => void actions.device.save()}
      />
    </div>
  );
}
