import { useEffect, useState, type KeyboardEvent } from "react";

import type {
  KpiCurrentHealthStatus,
  KpiMetricResultPageV6,
  KpiNeedsAttentionGroup,
  KpiResultView,
  KpiTaskSummaryV6,
  KpiTrendHealthStatus,
} from "../../api/http";
import { KpiMetricResultsTable } from "./KpiMetricResultsTable";

export interface KpiResultFilters {
  search: string;
  measurementUnitId: string | null;
  currentStatus: KpiCurrentHealthStatus | null;
  yesterdayTrend: KpiTrendHealthStatus | null;
  needsAttentionGroup: KpiNeedsAttentionGroup | null;
}

export const EMPTY_KPI_RESULT_FILTERS: KpiResultFilters = {
  search: "",
  measurementUnitId: null,
  currentStatus: null,
  yesterdayTrend: null,
  needsAttentionGroup: null,
};

const VIEW_ORDER: KpiResultView[] = ["needs_attention", "team_focus", "all"];

const CURRENT_STATUS_OPTIONS: { value: KpiCurrentHealthStatus; label: string }[] = [
  { value: "normal", label: "正常" },
  { value: "warn", label: "预警" },
  { value: "fail", label: "失败" },
  { value: "pending_config", label: "待配置" },
  { value: "unable_to_judge", label: "无法判定" },
  { value: "not_applicable", label: "不适用" },
];

const TREND_OPTIONS: { value: KpiTrendHealthStatus; label: string }[] = [
  { value: "improved", label: "改善" },
  { value: "stable", label: "稳定" },
  { value: "worsened", label: "恶化" },
  { value: "observe", label: "观察" },
  { value: "no_baseline", label: "无基线" },
];

const GROUP_OPTIONS: { value: KpiNeedsAttentionGroup; label: string }[] = [
  { value: "failure", label: "失败" },
  { value: "warning", label: "预警" },
  { value: "trend_degraded", label: "昨日恶化" },
  { value: "unjudgeable", label: "无法判定" },
  { value: "needs_config", label: "待配置" },
];

const VIEW_META: Record<
  KpiResultView,
  { label: string; count: (summary: KpiTaskSummaryV6) => number }
> = {
  needs_attention: {
    label: "需处理",
    count: (summary) => summary.counts.needs_attention_count,
  },
  team_focus: {
    label: "团队关注",
    count: (summary) => summary.counts.team_focus_count,
  },
  all: {
    label: "全部指标",
    count: (summary) => summary.counts.all_metric_count,
  },
};

function hasActiveFilters(filters: KpiResultFilters): boolean {
  return Boolean(
    filters.search.trim()
      || filters.measurementUnitId
      || filters.currentStatus
      || filters.yesterdayTrend
      || filters.needsAttentionGroup,
  );
}

function EmptyState({
  page,
  onClearFilters,
  onRefresh,
}: {
  page: KpiMetricResultPageV6;
  onClearFilters: () => void;
  onRefresh?: () => void;
}) {
  if (page.empty_state === "none") return null;

  const content = {
    team_focus_empty: {
      title: "当前网元类型的团队关注为空",
      description: "请从“管理团队关注”中手动加入需要持续关注的指标。",
    },
    no_task_metrics: {
      title: "当前任务没有 KPI 指标",
      description: "当前任务范围未冻结到 KPI 指标，请刷新结果或检查任务配置。",
    },
    no_matching_metrics: {
      title: "没有符合当前条件的指标",
      description: "可清除筛选后查看当前视图的全部指标。",
    },
  }[page.empty_state];

  return (
    <div className="kpi-results-empty" role="status">
      <h2>{content.title}</h2>
      <p>{content.description}</p>
      {page.empty_state === "no_matching_metrics" ? (
        <button type="button" className="kpi-workbench-button" onClick={onClearFilters}>
          清除筛选
        </button>
      ) : null}
      {page.empty_state === "no_task_metrics" ? (
        <button
          type="button"
          className="kpi-workbench-button"
          disabled={!onRefresh}
          onClick={onRefresh}
        >
          刷新当前结果
        </button>
      ) : null}
    </div>
  );
}

export interface KpiResultViewsProps {
  summary: KpiTaskSummaryV6;
  view: KpiResultView;
  filters: KpiResultFilters;
  page: KpiMetricResultPageV6;
  measurementUnitOptions: { value: string; label: string }[];
  onViewChange: (view: KpiResultView) => void;
  onFiltersChange: (filters: KpiResultFilters) => void;
  onClearFilters: () => void;
  onRefresh?: () => void;
  onOpenEvidence?: Parameters<typeof KpiMetricResultsTable>[0]["onOpenEvidence"];
  selectedMetricKey?: string | null;
}

export function KpiResultViews({
  summary,
  view,
  filters,
  page,
  measurementUnitOptions,
  onViewChange,
  onFiltersChange,
  onClearFilters,
  onRefresh,
  onOpenEvidence,
  selectedMetricKey,
}: KpiResultViewsProps) {
  const [searchDraft, setSearchDraft] = useState(filters.search);
  const activeFilters = hasActiveFilters(filters);

  useEffect(() => {
    setSearchDraft(filters.search);
  }, [filters.search]);

  const moveView = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = VIEW_ORDER.findIndex((item) => item === view);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % VIEW_ORDER.length;
    if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + VIEW_ORDER.length) % VIEW_ORDER.length;
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = VIEW_ORDER.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    onViewChange(VIEW_ORDER[nextIndex]);
    const tabList = event.currentTarget.parentElement;
    const nextTab = tabList?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex];
    nextTab?.focus();
  };

  return (
    <div className="kpi-result-views">
      <div className="kpi-result-view-toolbar">
        <div>
          <h2 id="kpi-results-title">巡检结果</h2>
          <p>汇总计数来自任务结果快照，不会随视图或筛选变化。</p>
        </div>
        <div className="kpi-result-view-tabs" role="tablist" aria-label="KPI 结果视图">
          {VIEW_ORDER.map((item) => {
            const meta = VIEW_META[item];
            const selected = item === view;
            return (
              <button
                key={item}
                type="button"
                role="tab"
                id={`kpi-result-tab-${item}`}
                aria-selected={selected}
                aria-controls="kpi-result-view-panel"
                tabIndex={selected ? 0 : -1}
                className={selected ? "is-active" : undefined}
                onClick={() => onViewChange(item)}
                onKeyDown={moveView}
              >
                {meta.label} <span>{meta.count(summary)}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="kpi-result-filter-row" role="group" aria-label="筛选指标">
        <label className="kpi-result-search">
          <span className="sr-only">搜索指标</span>
          <input
            type="search"
            aria-label="搜索指标"
            placeholder="搜索指标名称、指标 ID、测量单元"
            value={searchDraft}
            onChange={(event) => {
              const search = event.currentTarget.value;
              setSearchDraft(search);
              onFiltersChange({ ...filters, search });
            }}
          />
        </label>

        <label className="kpi-result-select">
          <span className="sr-only">测量单元筛选</span>
          <select
            aria-label="测量单元筛选"
            value={filters.measurementUnitId ?? ""}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                measurementUnitId: event.currentTarget.value || null,
              })
            }
          >
            <option value="">全部测量单元</option>
            {measurementUnitOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="kpi-result-select">
          <span className="sr-only">当前判定筛选</span>
          <select
            aria-label="当前判定筛选"
            value={filters.currentStatus ?? ""}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                currentStatus: (event.currentTarget.value || null) as KpiCurrentHealthStatus | null,
              })
            }
          >
            <option value="">全部判定</option>
            {CURRENT_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="kpi-result-select">
          <span className="sr-only">昨日趋势筛选</span>
          <select
            aria-label="昨日趋势筛选"
            value={filters.yesterdayTrend ?? ""}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                yesterdayTrend: (event.currentTarget.value || null) as KpiTrendHealthStatus | null,
              })
            }
          >
            <option value="">全部趋势</option>
            {TREND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {view === "needs_attention" ? (
          <label className="kpi-result-select">
            <span className="sr-only">需处理分组筛选</span>
            <select
              aria-label="需处理分组筛选"
              value={filters.needsAttentionGroup ?? ""}
              onChange={(event) =>
                onFiltersChange({
                  ...filters,
                  needsAttentionGroup: (event.currentTarget.value || null) as KpiNeedsAttentionGroup | null,
                })
              }
            >
              <option value="">全部分组</option>
              {GROUP_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <span className="kpi-result-visible-total" data-testid="kpi-result-visible-total">
          当前可见 {page.total} / 视图总计 {page.view_total} 项
        </span>
        <button
          type="button"
          className="kpi-workbench-clear-filter"
          disabled={!activeFilters}
          onClick={onClearFilters}
        >
          清除全部筛选
        </button>
      </div>

      <div
        id="kpi-result-view-panel"
        role="tabpanel"
        aria-labelledby={`kpi-result-tab-${view}`}
      >
        {page.empty_state === "none" ? (
          <KpiMetricResultsTable
            page={page}
            onRefresh={onRefresh}
            onOpenEvidence={onOpenEvidence}
            selectedMetricKey={selectedMetricKey}
          />
        ) : (
          <EmptyState page={page} onClearFilters={onClearFilters} onRefresh={onRefresh} />
        )}
      </div>
    </div>
  );
}
