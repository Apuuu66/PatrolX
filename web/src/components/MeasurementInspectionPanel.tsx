import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/http";
import type {
  MeasurementKpiOverview,
  MeasurementMetadataMetric,
  MeasurementMetadataUnit,
  MeasurementMetricDetail,
} from "../api/http";
import { KpiDailyHealthPanel } from "./KpiDailyHealthPanel";
import { MetricTrendCell } from "./MeasurementTrendChart";

const MeasurementMetricDetail = lazy(() =>
  import("./MeasurementMetricDetail").then((module) => ({ default: module.MeasurementMetricDetail })),
);
const MeasurementDerivedMetrics = lazy(() =>
  import("./MeasurementMetricDetail").then((module) => ({ default: module.MeasurementDerivedMetrics })),
);

const METRIC_PAGE_SIZE = 10;
const METRIC_NAME_COLLATOR = new Intl.Collator("zh-Hans-CN");

const STATUS_LABELS: Record<string, string> = {
  pass: "通过",
  warn: "告警",
  fail: "失败",
  error: "异常",
  skip: "跳过",
};

const STATUS_COLORS: Record<string, string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
  error: "default",
  skip: "blue",
};

const BUSINESS_STATUS_LABELS: Record<string, string> = {
  normal: "正常",
  warn: "阈值预警",
  fail: "阈值失败",
  unconfigured: "未配置阈值",
  not_applicable: "不适用",
  not_judgeable: "无法判定",
};

const TREND_LABELS: Record<string, string> = {
  stable: "稳定",
  rising: "上升",
  falling: "下降",
  spike: "突增",
  plunge: "突降",
  fluctuating: "波动",
  all_zero: "全 0",
  recovering: "恢复中",
  cannot_determine: "无法判断",
};

const TREND_SIGNAL_LABELS: Record<string, string> = {
  improved: "改善",
  worsened: "恶化",
  none: "无方向信号",
};

const IMPORTANCE_LABELS: Record<string, string> = {
  P0: "P0",
  P1: "P1",
  P2: "P2",
  normal: "普通",
};

const IMPORTANCE_ORDER: Record<string, number> = { P0: 0, P1: 1, P2: 2, normal: 3 };

function InlineTag({ color = "default", children }: { color?: string; children: ReactNode }) {
  return <span className={`measurement-inline-tag measurement-inline-tag--${color}`}>{children}</span>;
}

function MetricReadTag({ metric }: { metric: MeasurementMetadataMetric }) {
  if (metric.read_status === "missing") return <InlineTag color="red">列缺失</InlineTag>;
  if (metric.read_status === "parse_error") return <InlineTag color="red">不可读</InlineTag>;
  if (metric.value_pattern === "all_zero") return <InlineTag color="blue">全 0</InlineTag>;
  return <InlineTag color="green">可读</InlineTag>;
}

function MetricBusinessTag({ metric }: { metric: MeasurementMetadataMetric }) {
  const status = metric.business_status;
  if (!status) return <InlineTag>旧数据</InlineTag>;
  const color = status === "fail" ? "red" : status === "warn" ? "gold" : status === "normal" ? "green" : "blue";
  return <InlineTag color={color}>{BUSINESS_STATUS_LABELS[status] ?? status}</InlineTag>;
}

function MetricNameCell({ metric }: { metric: MeasurementMetadataMetric }) {
  const name = metric.metric_resource_name_zh || metric.base_source_name || metric.metric_resource_id;
  return (
    <div className="measurement-metric-name">
      <div>{name}</div>
      {name !== metric.metric_resource_id ? (
        <span className="measurement-metric-resource-id">{metric.metric_resource_id}</span>
      ) : null}
    </div>
  );
}

function KpiOverviewCard({ overview }: { overview: MeasurementKpiOverview }) {
  const statusCounts = overview.status_counts ?? {};
  const healthScore = Math.max(0, Math.min(100, overview.health_score));
  const statistics = [
    { label: "测量单元", value: overview.unit_count },
    { label: "指标数", value: overview.metric_count },
    { label: "阈值失败", value: overview.business_fail_count, tone: "fail" },
    { label: "阈值预警", value: overview.business_warn_count, tone: "warn" },
    { label: "数据异常", value: overview.data_error_count },
    { label: "趋势恶化", value: overview.trend_worsened_count },
    { label: "未配置阈值", value: overview.unconfigured_count },
    { label: "自动入库", value: overview.auto_registered_count ?? 0 },
    { label: "跨单元冲突", value: overview.conflict_count ?? 0 },
    { label: "未匹配文件", value: overview.unmatched_file_count ?? 0 },
  ];
  return (
    <section className="measurement-kpi-overview" aria-labelledby="measurement-kpi-overview-title">
      <h3 id="measurement-kpi-overview-title">KPI 总览</h3>
      <div className="measurement-kpi-overview-content">
        <div className="measurement-kpi-health">
          <div
            className="measurement-kpi-health-score"
            role="progressbar"
            aria-label="最低健康分"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={healthScore}
          >
            {healthScore}
          </div>
          <span>最低健康分</span>
        </div>
        <dl className="measurement-kpi-statistics">
          {statistics.map((item) => (
            <div key={item.label} data-tone={item.tone}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
        <div className="measurement-kpi-status-counts">
          <span className="measurement-kpi-status-label">规则状态</span>
          {Object.entries(statusCounts).map(([status, count]) => (
            <span key={status} className="measurement-kpi-status-count">
              <InlineTag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</InlineTag> {count}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function metricRowKey(metric: MeasurementMetadataMetric): string {
  return `${metric.metric_resource_id}::${metric.raw_source_name}`;
}

function sortMetrics(metrics: MeasurementMetadataMetric[]): MeasurementMetadataMetric[] {
  return [...metrics].sort((left, right) => {
    const leftOrder = IMPORTANCE_ORDER[left.importance ?? "normal"] ?? 3;
    const rightOrder = IMPORTANCE_ORDER[right.importance ?? "normal"] ?? 3;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    return METRIC_NAME_COLLATOR.compare(
      `${left.metric_resource_name_zh ?? ""}${left.metric_resource_id}`,
      `${right.metric_resource_name_zh ?? ""}${right.metric_resource_id}`,
    );
  });
}

export function MeasurementInspectionPanel({
  metadata,
  taskId,
  ruleCode,
  showAllColumns = false,
}: {
  metadata?: Record<string, unknown>;
  taskId?: string;
  ruleCode?: string;
  /** 证据面板的"显示全部列"开关；默认精简列（FR-022）。 */
  showAllColumns?: boolean;
}) {
  const [metricDetails, setMetricDetails] = useState<Record<string, MeasurementMetricDetail | undefined>>({});
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({});
  const [detailErrors, setDetailErrors] = useState<Record<string, string | undefined>>({});
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null);
  const [metricPage, setMetricPage] = useState(1);
  const [expandedMetrics, setExpandedMetrics] = useState<Set<string>>(() => new Set());
  const taskRuleKey = `${taskId ?? ""}:${ruleCode ?? ""}`;
  const previousTaskRuleKey = useRef(taskRuleKey);

  useEffect(() => {
    if (previousTaskRuleKey.current === taskRuleKey) return;
    previousTaskRuleKey.current = taskRuleKey;
    setMetricDetails({});
    setDetailLoading({});
    setDetailErrors({});
    setSelectedUnitId(null);
    setMetricPage(1);
    setExpandedMetrics(new Set());
  }, [taskRuleKey]);

  const loadMetricDetail = useCallback(
    async (unitId: string, metricId: string) => {
      if (!taskId || !ruleCode) return;
      const key = `${unitId}:${metricId}`;
      setDetailLoading((current) => ({ ...current, [key]: true }));
      setDetailErrors((current) => ({ ...current, [key]: undefined }));
      try {
        const detail = await api.getMeasurementMetricDetail(taskId, ruleCode, unitId, metricId);
        setMetricDetails((current) => ({ ...current, [key]: detail }));
      } catch (error) {
        setDetailErrors((current) => ({
          ...current,
          [key]: error instanceof Error ? error.message : "指标明细加载失败",
        }));
      } finally {
        setDetailLoading((current) => ({ ...current, [key]: false }));
      }
    },
    [ruleCode, taskId],
  );

  const overview = useMemo(() => {
    return metadata?.kpi_overview ? (metadata.kpi_overview as MeasurementKpiOverview) : null;
  }, [metadata]);

  const units = useMemo(() => {
    const raw = metadata?.measurement_units;
    if (!Array.isArray(raw)) return [];
    return (raw as MeasurementMetadataUnit[])
      .map((unit) => ({ ...unit, metrics: [...unit.metrics] }))
      .sort((left, right) => (left.risk_summary?.health_score ?? 100) - (right.risk_summary?.health_score ?? 100));
  }, [metadata]);

  const activeUnit = units.find((unit) => unit.measurement_unit_id === selectedUnitId) ?? units[0];
  const metrics = useMemo(() => sortMetrics(activeUnit?.metrics ?? []), [activeUnit]);
  const pageCount = Math.max(1, Math.ceil(metrics.length / METRIC_PAGE_SIZE));
  const currentPage = Math.min(metricPage, pageCount);
  const pageMetrics = metrics.slice((currentPage - 1) * METRIC_PAGE_SIZE, currentPage * METRIC_PAGE_SIZE);

  const chooseUnit = (unitId: string) => {
    setSelectedUnitId(unitId);
    setMetricPage(1);
    setExpandedMetrics(new Set());
  };

  const toggleMetric = (metric: MeasurementMetadataMetric) => {
    const key = metricRowKey(metric);
    const opening = !expandedMetrics.has(key);
    if (opening) void loadMetricDetail(activeUnit.measurement_unit_id, metric.metric_resource_id);
    setExpandedMetrics((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!activeUnit) {
    return (
      <div className="measurement-inspection-panel" data-testid="measurement-inspection-panel">
        <KpiDailyHealthPanel metadata={metadata} taskId={taskId} ruleCode={ruleCode} />
        <div className="measurement-panel-empty">没有可展示的测量单元结果</div>
      </div>
    );
  }

  const objectRows = Object.values(activeUnit.objects ?? {});
  const risk = activeUnit.risk_summary;
  const dataColumnCount = showAllColumns ? 8 : 7;

  return (
    <div className="measurement-inspection-panel" data-testid="measurement-inspection-panel">
      <KpiDailyHealthPanel metadata={metadata} taskId={taskId} ruleCode={ruleCode} />
      {overview ? <KpiOverviewCard overview={overview} /> : null}
      <div className="measurement-unit-toolbar">
        <label htmlFor="measurement-unit-selector">测量单元</label>
        <select
          id="measurement-unit-selector"
          className="measurement-unit-select"
          aria-label="测量单元"
          data-testid="measurement-unit-selector"
          value={activeUnit.measurement_unit_id}
          onChange={(event) => chooseUnit(event.target.value)}
        >
          {units.map((unit) => (
            <option key={unit.measurement_unit_id} value={unit.measurement_unit_id} title={unit.name_zh}>
              {`${unit.name_zh}（${STATUS_LABELS[unit.status]}，健康分 ${unit.risk_summary?.health_score ?? 100}）`}
            </option>
          ))}
        </select>
        <span className="measurement-unit-count">共 {units.length} 个，仅展示当前单元</span>
      </div>

      <section className="measurement-unit-card" aria-labelledby="measurement-unit-title">
        <header className="measurement-unit-card-header">
          <div className="measurement-unit-title" id="measurement-unit-title">
            <h3>{activeUnit.name_zh}</h3>
            <span className="measurement-unit-id">{activeUnit.measurement_unit_id}</span>
            <InlineTag color={STATUS_COLORS[activeUnit.status]}>{STATUS_LABELS[activeUnit.status]}</InlineTag>
            {activeUnit.reason ? <span className="measurement-unit-reason">{activeUnit.reason}</span> : null}
          </div>
          {risk ? <span className="measurement-unit-health">健康分 {risk.health_score}</span> : null}
        </header>
        <dl className="measurement-unit-details">
          <div>
            <dt>英文名</dt>
            <dd>{activeUnit.name_en}</dd>
          </div>
          <div>
            <dt>文件数</dt>
            <dd>{activeUnit.file_count}</dd>
          </div>
          <div>
            <dt>指标覆盖</dt>
            <dd>{activeUnit.metric_coverage ?? "-"}</dd>
          </div>
          <div className="measurement-unit-source-files">
            <dt>来源文件</dt>
            <dd>{(activeUnit.source_files ?? []).join("，") || "-"}</dd>
          </div>
          <div>
            <dt>指标数</dt>
            <dd>{activeUnit.metrics.length}</dd>
          </div>
          <div>
            <dt>行对象数</dt>
            <dd>{objectRows.length}</dd>
          </div>
        </dl>

        <div className="measurement-metric-table-scroll">
          <table
            className="measurement-metric-table"
            aria-label="KPI 指标列表"
          >
            <caption className="visually-hidden">KPI 指标列表</caption>
            <colgroup>
              <col className="measurement-metric-col-toggle" />
              <col className="measurement-metric-col-name" />
              <col className="measurement-metric-col-importance" />
              {showAllColumns ? <col className="measurement-metric-col-source" /> : null}
              <col className="measurement-metric-col-unit" />
              <col className="measurement-metric-col-read" />
              <col className="measurement-metric-col-status" />
              <col className="measurement-metric-col-threshold" />
              <col className="measurement-metric-col-trend" />
            </colgroup>
            <thead>
              <tr>
                <th scope="col"><span className="visually-hidden">展开</span></th>
                <th scope="col">指标</th>
                <th scope="col">重点</th>
                {showAllColumns ? <th scope="col">CSV 列名</th> : null}
                <th scope="col">单位</th>
                <th scope="col">可读性</th>
                <th scope="col">业务状态</th>
                <th scope="col">阈值</th>
                <th scope="col">趋势</th>
              </tr>
            </thead>
            <tbody>
              {pageMetrics.map((metric) => {
                const key = metricRowKey(metric);
                const expanded = expandedMetrics.has(key);
                const detailKey = `${activeUnit.measurement_unit_id}:${metric.metric_resource_id}`;
                const metricName = metric.metric_resource_name_zh || metric.base_source_name || metric.metric_resource_id;
                const thresholds = metric.warning_threshold === null && metric.critical_threshold === null
                  ? "-"
                  : `${metric.warning_threshold ?? "-"} / ${metric.critical_threshold ?? "-"}`;
                return (
                  <MetricRows
                    key={key}
                    metric={metric}
                    metricName={metricName}
                    expanded={expanded}
                    dataColumnCount={dataColumnCount}
                    showAllColumns={showAllColumns}
                    thresholds={thresholds}
                    taskId={taskId}
                    ruleCode={ruleCode}
                    unitId={activeUnit.measurement_unit_id}
                    detail={metricDetails[detailKey]?.metric as MeasurementMetadataMetric | undefined}
                    detailLoading={Boolean(detailLoading[detailKey])}
                    detailError={detailErrors[detailKey]}
                    showAllDetailColumns={showAllColumns}
                    onToggle={() => toggleMetric(metric)}
                    onRetry={() => void loadMetricDetail(activeUnit.measurement_unit_id, metric.metric_resource_id)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>

        {pageCount > 1 ? (
          <nav className="measurement-metric-pagination" aria-label="指标分页">
            <button
              type="button"
              className="measurement-pagination-button"
              disabled={currentPage === 1}
              onClick={() => setMetricPage(currentPage - 1)}
            >
              上一页
            </button>
            <span>第 {currentPage} / {pageCount} 页，共 {metrics.length} 条</span>
            <button
              type="button"
              className="measurement-pagination-button"
              disabled={currentPage === pageCount}
              onClick={() => setMetricPage(currentPage + 1)}
            >
              下一页
            </button>
          </nav>
        ) : null}

        {(activeUnit.derived_metrics ?? []).length > 0 ? (
          <Suspense fallback={<div className="measurement-derived-loading">正在加载派生指标…</div>}>
            <MeasurementDerivedMetrics metrics={activeUnit.derived_metrics ?? []} />
          </Suspense>
        ) : null}
      </section>
    </div>
  );
}

function MetricRows({
  metric,
  metricName,
  expanded,
  dataColumnCount,
  showAllColumns,
  thresholds,
  taskId,
  ruleCode,
  unitId,
  detail,
  detailLoading,
  detailError,
  showAllDetailColumns,
  onToggle,
  onRetry,
}: {
  metric: MeasurementMetadataMetric;
  metricName: string;
  expanded: boolean;
  dataColumnCount: number;
  showAllColumns: boolean;
  thresholds: string;
  taskId?: string;
  ruleCode?: string;
  unitId: string;
  detail?: MeasurementMetadataMetric;
  detailLoading: boolean;
  detailError?: string;
  showAllDetailColumns: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  return (
    <>
      <tr className={expanded ? "measurement-metric-row is-expanded" : "measurement-metric-row"}>
        <td className="measurement-metric-toggle-cell">
          <button
            type="button"
            className="measurement-metric-toggle"
            aria-expanded={expanded}
            aria-label={`${expanded ? "收起" : "展开"}${metricName}明细`}
            onClick={onToggle}
          >
            {expanded ? "−" : "+"}
          </button>
        </td>
        <td><MetricNameCell metric={metric} /></td>
        <td>{IMPORTANCE_LABELS[metric.importance ?? "normal"] ?? "普通"}</td>
        {showAllColumns ? <td>{metric.raw_source_name}</td> : null}
        <td>{metric.display_unit || "-"}</td>
        <td><MetricReadTag metric={metric} /></td>
        <td><MetricBusinessTag metric={metric} /></td>
        <td className="measurement-metric-number">{thresholds}</td>
        <td>
          <div className="measurement-metric-trend">
            <div className="measurement-metric-trend-tags">
              <InlineTag color="blue">
                {TREND_LABELS[metric.trend_label ?? "cannot_determine"] ?? metric.trend_label}
              </InlineTag>
              <InlineTag color={metric.trend_signal === "improved" ? "green" : metric.trend_signal === "worsened" ? "red" : "blue"}>
                {TREND_SIGNAL_LABELS[metric.trend_signal ?? "none"]}
              </InlineTag>
            </div>
            <MetricTrendCell
              metric={metric}
              detailMetric={detail}
              taskId={taskId}
              ruleCode={ruleCode}
              unitId={unitId}
            />
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="measurement-metric-detail-row">
          <td colSpan={dataColumnCount + 1}>
            <Suspense fallback={<div className="measurement-metric-detail-loading">正在加载指标明细…</div>}>
              <MeasurementMetricDetail
                metric={metric}
                detail={detail}
                showAllColumns={showAllDetailColumns}
                isLoading={detailLoading}
                error={detailError}
                onRetry={onRetry}
              />
            </Suspense>
          </td>
        </tr>
      ) : null}
    </>
  );
}
