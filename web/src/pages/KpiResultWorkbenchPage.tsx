import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  api,
  type KpiMetricResultV6,
  type KpiMetricResultPageV6,
  type KpiNeedsAttentionGroup,
  type KpiResultView,
  type KpiTaskSummaryV6,
} from "../api/http";
import { KpiEvidenceDrawer } from "../components/kpi-workbench/KpiEvidenceDrawer";
import { kpiMetricKey } from "../components/kpi-workbench/KpiMetricResultsTable";
import {
  EMPTY_KPI_RESULT_FILTERS,
  KpiResultViews,
  type KpiResultFilters,
} from "../components/kpi-workbench/KpiResultViews";
import { KpiSummaryHeader } from "../components/kpi-workbench/KpiSummaryHeader";
import { TeamFocusDrawer } from "../components/kpi-workbench/TeamFocusDrawer";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function requiresRebuild(error: unknown): boolean {
  return error instanceof ApiError && error.code === "task_result_requires_rebuild";
}

function WorkbenchLoading() {
  return (
    <div className="kpi-workbench-loading" aria-busy="true">
      <span className="kpi-workbench-loading-bar" aria-hidden="true" />
      <span>正在读取巡检结果…</span>
    </div>
  );
}

function WorkbenchError({
  description,
  onRetry,
}: {
  description: string;
  onRetry: () => void;
}) {
  return (
    <section className="kpi-workbench-error" role="alert">
      <div>
        <h2>KPI 工作台加载失败</h2>
        <p>{description}</p>
      </div>
      <button type="button" className="kpi-workbench-button" onClick={onRetry}>
        重试
      </button>
    </section>
  );
}

function RebuildRequired({ taskId }: { taskId: string }) {
  const navigate = useNavigate();
  return (
    <section className="kpi-workbench-rebuild" role="alert">
      <span className="kpi-workbench-rebuild-mark" aria-hidden="true">!</span>
      <div>
        <h2>当前任务需要重建</h2>
        <p>该任务没有 v6 KPI 结果快照。旧结果不迁移，也不参与本次判读。</p>
      </div>
      <button
        type="button"
        className="kpi-workbench-button is-primary"
        onClick={() => navigate(`/tasks/${encodeURIComponent(taskId)}`)}
      >
        返回任务详情并重建
      </button>
    </section>
  );
}

function WorkbenchPageContent({ taskId }: { taskId: string }) {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<KpiTaskSummaryV6 | null>(null);
  const [resultPage, setResultPage] = useState<KpiMetricResultPageV6 | null>(null);
  const [view, setView] = useState<KpiResultView>("needs_attention");
  const [filters, setFilters] = useState<KpiResultFilters>({ ...EMPTY_KPI_RESULT_FILTERS });
  const [measurementUnitOptions, setMeasurementUnitOptions] = useState<
    { value: string; label: string }[]
  >([]);
  const [selectedMetric, setSelectedMetric] = useState<KpiMetricResultV6 | null>(null);
  const [teamFocusOpen, setTeamFocusOpen] = useState(false);
  const [pageNumber, setPageNumber] = useState(1);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [resultsLoading, setResultsLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [resultsError, setResultsError] = useState<string | null>(null);
  const [rebuildRequired, setRebuildRequired] = useState(false);
  const summaryRequest = useRef(0);
  const resultsRequest = useRef(0);

  useEffect(() => {
    const requestId = ++summaryRequest.current;
    setSummaryLoading(true);
    setSummaryError(null);
    api
      .getKpiTaskSummaryV6(taskId)
      .then((nextSummary) => {
        if (requestId !== summaryRequest.current) return;
        setSummary(nextSummary);
        setRebuildRequired(false);
      })
      .catch((error: unknown) => {
        if (requestId !== summaryRequest.current) return;
        if (requiresRebuild(error)) {
          setSummary(null);
          setRebuildRequired(true);
          return;
        }
        setSummaryError(errorMessage(error));
      })
      .finally(() => {
        if (requestId === summaryRequest.current) setSummaryLoading(false);
      });
  }, [refreshVersion, taskId]);

  useEffect(() => {
    const networkElementType = summary?.network_element_type;
    if (!networkElementType) {
      setMeasurementUnitOptions([]);
      return;
    }

    let active = true;
    api
      .listKpiMeasurementUnitsV6({
        network_element_type: networkElementType,
        page: 1,
        page_size: 200,
      })
      .then((unitsPage) => {
        if (!active) return;
        setMeasurementUnitOptions(
          unitsPage.items.map((unit) => ({
            value: unit.measurement_unit_id,
            label: unit.name_zh,
          })),
        );
      })
      .catch(() => {
        if (active) setMeasurementUnitOptions([]);
      });
    return () => {
      active = false;
    };
  }, [refreshVersion, summary?.network_element_type]);

  useEffect(() => {
    const requestId = ++resultsRequest.current;
    setResultsLoading(true);
    setResultsError(null);
    api
      .listKpiTaskMetricsV6(taskId, {
        view,
        page: pageNumber,
        page_size: 20,
        search: filters.search.trim() || undefined,
        measurement_unit_id: filters.measurementUnitId ?? undefined,
        current_status: filters.currentStatus ?? undefined,
        yesterday_trend: filters.yesterdayTrend ?? undefined,
        needs_attention_group: filters.needsAttentionGroup ?? undefined,
      })
      .then((nextPage) => {
        if (requestId !== resultsRequest.current) return;
        setResultPage(nextPage);
        setRebuildRequired(false);
      })
      .catch((error: unknown) => {
        if (requestId !== resultsRequest.current) return;
        if (requiresRebuild(error)) {
          setResultPage(null);
          setRebuildRequired(true);
          return;
        }
        setResultsError(errorMessage(error));
      })
      .finally(() => {
        if (requestId === resultsRequest.current) setResultsLoading(false);
      });
  }, [filters, pageNumber, refreshVersion, taskId, view]);

  const refresh = useCallback(() => {
    setSelectedMetric(null);
    setRefreshVersion((version) => version + 1);
  }, []);

  const changeView = useCallback((nextView: KpiResultView) => {
    setSelectedMetric(null);
    setView(nextView);
    setPageNumber(1);
  }, []);

  const changeFilters = useCallback((nextFilters: KpiResultFilters) => {
    setSelectedMetric(null);
    setFilters(nextFilters);
    setPageNumber(1);
  }, []);

  const clearFilters = useCallback(() => {
    setSelectedMetric(null);
    setFilters({ ...EMPTY_KPI_RESULT_FILTERS });
    setPageNumber(1);
  }, []);

  const selectGroup = useCallback((group: KpiNeedsAttentionGroup) => {
    setSelectedMetric(null);
    setFilters((current) => ({
      ...current,
      needsAttentionGroup: current.needsAttentionGroup === group ? null : group,
    }));
    setView("needs_attention");
    setPageNumber(1);
  }, []);

  const closeEvidence = useCallback(() => {
    setSelectedMetric(null);
  }, []);

  const changePage = useCallback((nextPage: number) => {
    setSelectedMetric(null);
    setPageNumber(nextPage);
  }, []);

  const availableMeasurementUnits = useMemo(() => {
    const options = new Map(measurementUnitOptions.map((option) => [option.value, option.label]));
    resultPage?.items.forEach((item) => {
      if (!options.has(item.measurement_unit_id)) {
        options.set(item.measurement_unit_id, item.measurement_unit_name);
      }
    });
    if (filters.measurementUnitId && !options.has(filters.measurementUnitId)) {
      options.set(filters.measurementUnitId, filters.measurementUnitId);
    }
    return [...options].map(([value, label]) => ({ value, label }));
  }, [filters.measurementUnitId, measurementUnitOptions, resultPage?.items]);

  const pageHeading = (
    <header className="kpi-workbench-heading">
      <div>
        <nav className="kpi-workbench-breadcrumb" aria-label="面包屑">
          <Link to="/tasks">巡检任务</Link>
          <span aria-hidden="true">/</span>
          <Link to={`/tasks/${encodeURIComponent(taskId)}`}>{taskId}</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">KPI 巡检结果</span>
        </nav>
        <div className="kpi-workbench-title-line">
          <h2>KPI 巡检结果</h2>
          {summary?.network_element_type ? (
            <span className="kpi-workbench-network-tag">{summary.network_element_type}</span>
          ) : null}
          {resultPage?.empty_state === "none" && resultPage.items.length > 0 ? (
            <span className="kpi-workbench-ready-tag">结果已发布</span>
          ) : null}
        </div>
        <p>先看需处理项，再按测量单元与指标证据逐项核验。</p>
      </div>
      <div className="kpi-workbench-actions">
        {summary?.network_element_type ? (
          <button
            type="button"
            className="kpi-workbench-button"
            onClick={() => setTeamFocusOpen(true)}
          >
            管理团队关注
          </button>
        ) : null}
        <button
          type="button"
          className="kpi-workbench-button"
          onClick={() => navigate(`/tasks/${encodeURIComponent(taskId)}/report`)}
        >
          查看任务报告
        </button>
        <button
          type="button"
          className="kpi-workbench-button is-primary"
          disabled={summaryLoading || resultsLoading}
          onClick={refresh}
        >
          刷新当前结果
        </button>
      </div>
    </header>
  );

  if (rebuildRequired) {
    return (
      <div className="kpi-workbench-page">
        {pageHeading}
        <RebuildRequired taskId={taskId} />
      </div>
    );
  }

  if (summaryError && !summary) {
    return (
      <div className="kpi-workbench-page">
        {pageHeading}
        <WorkbenchError description={summaryError} onRetry={refresh} />
      </div>
    );
  }

  if (!summary && summaryLoading) {
    return (
      <div className="kpi-workbench-page">
        {pageHeading}
        <WorkbenchLoading />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="kpi-workbench-page">
        {pageHeading}
        <WorkbenchError description="未读取到工作台汇总" onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className={`kpi-workbench-page${selectedMetric ? " has-evidence" : ""}`}>
      {pageHeading}

      <KpiSummaryHeader
        summary={summary}
        selectedGroup={filters.needsAttentionGroup}
        onGroupSelect={selectGroup}
      />

      {summary.notices?.length ? (
        <div className="kpi-workbench-notice" role="note">
          {summary.notices.join("；")}
        </div>
      ) : null}

      <div className="kpi-workbench-results-layout">
        <section className="kpi-results-panel" aria-labelledby="kpi-results-title">
          {resultsError ? (
            <div className="kpi-results-error" role="alert">
              <span>{resultsError}</span>
              <button type="button" className="kpi-workbench-button" onClick={refresh}>
                重试
              </button>
            </div>
          ) : resultsLoading && !resultPage ? (
            <WorkbenchLoading />
          ) : resultPage ? (
            <div aria-busy={resultsLoading}>
              <KpiResultViews
                summary={summary}
                view={view}
                filters={filters}
                page={resultPage}
                measurementUnitOptions={availableMeasurementUnits}
                onViewChange={changeView}
                onFiltersChange={changeFilters}
                onClearFilters={clearFilters}
                onRefresh={refresh}
                onOpenEvidence={setSelectedMetric}
                selectedMetricKey={selectedMetric ? kpiMetricKey(selectedMetric) : null}
              />
              {resultPage.empty_state === "none" && resultPage.total > resultPage.page_size ? (
                <div className="kpi-results-pagination" aria-label="结果分页">
                  <button
                    type="button"
                    className="kpi-workbench-button"
                    disabled={pageNumber <= 1 || resultsLoading}
                    onClick={() => changePage(Math.max(1, pageNumber - 1))}
                  >
                    上一页
                  </button>
                  <span>
                    第 {pageNumber} / {Math.max(1, Math.ceil(resultPage.total / resultPage.page_size))} 页
                  </span>
                  <button
                    type="button"
                    className="kpi-workbench-button"
                    disabled={pageNumber >= Math.ceil(resultPage.total / resultPage.page_size) || resultsLoading}
                    onClick={() => changePage(pageNumber + 1)}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
        {selectedMetric ? (
          <KpiEvidenceDrawer metric={selectedMetric} onClose={closeEvidence} />
        ) : null}
      </div>
      {teamFocusOpen && summary.network_element_type ? (
        <TeamFocusDrawer
          taskId={taskId}
          networkElementType={summary.network_element_type}
          onSaved={refresh}
          onClose={() => setTeamFocusOpen(false)}
        />
      ) : null}
    </div>
  );
}

export function KpiResultWorkbenchPage() {
  const { taskId = "" } = useParams();
  return <WorkbenchPageContent key={taskId} taskId={taskId} />;
}
