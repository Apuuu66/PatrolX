import { lazy, startTransition, Suspense, useEffect, useMemo, useState } from "react";
import type { MeasurementMetadataMetric, MeasurementTrendPoint } from "../api/http";
import { api } from "../api/http";
import { analyzeTrendComparison, type TrendComparison } from "../utils/measurementTrend";
import type { MetricTrendCellMetric } from "./MeasurementTrendTypes";

const HistoryTrendPanel = lazy(() =>
  import("./MeasurementAdvancedTrend").then((module) => ({ default: module.HistoryTrendPanel })),
);
const VersionComparePanel = lazy(() =>
  import("./MeasurementAdvancedTrend").then((module) => ({ default: module.VersionComparePanel })),
);

const POINT_PAGE_SIZE = 10;
const DATE_TIME_PATTERN = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2})?/;
const EXPLICIT_TIMEZONE_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const COMPACT_NUMBER = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 });
const BEIJING_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

type TrendTab = "single" | "history" | "version";

type ParsedPoint = {
  date: string;
  timeLabel: string;
  sortKey: string;
  value: number;
  source: MeasurementTrendPoint;
};

function MetricDisplayName(metric: { metric_resource_id: string; metric_resource_name_zh?: string | null; base_source_name?: string }) {
  return metric.metric_resource_name_zh || metric.base_source_name || metric.metric_resource_id;
}

function parsePoints(points: MeasurementTrendPoint[]): ParsedPoint[] {
  return points
    .map((point) => {
      const displayTime = formatPointTime(point.time);
      const match = DATE_TIME_PATTERN.exec(displayTime);
      if (!match || !Number.isFinite(point.value)) return null;
      const [, date, timeLabel] = match;
      return {
        date,
        timeLabel,
        sortKey: `${date} ${timeLabel}`,
        value: point.value,
        source: point,
      };
    })
    .filter((point): point is ParsedPoint => point !== null)
    .sort((left, right) => left.sortKey.localeCompare(right.sortKey));
}

function formatValue(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${value}${unit ? ` ${unit}` : ""}`;
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function formatPointTime(value: string): string {
  const normalized = value.replace("T", " ").slice(0, 19);
  if (!EXPLICIT_TIMEZONE_PATTERN.test(value)) return normalized;

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return normalized;
  const parts = Object.fromEntries(
    BEIJING_TIME_FORMATTER.formatToParts(date).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function formatChartTime(point: ParsedPoint, includeDate: boolean): string {
  return includeDate ? `${point.date.slice(5)} ${point.timeLabel}` : point.timeLabel;
}

function formatSourceEvidence(point: MeasurementTrendPoint): string {
  const rows = point.source_rows ?? [];
  if (!rows.length) return "-";
  return rows.map((row) => `${row.source_file}:${row.line_number}`).join("、");
}

function insufficientPointsReason(pointCount: number, trendReason?: string | null): string {
  if (trendReason === "no_time_series") return "未找到可用时间序列，测量时间缺失或格式非法";
  if (pointCount === 0) return "本任务内没有可用于趋势判断的时间点";
  if (pointCount === 1) return "本任务内只有 1 个时间点，至少需要 2 个时间点才能判断趋势";
  return "时间点数量不足，无法判断趋势";
}

function TrendComparisonSummary({ comparison, unit }: { comparison: TrendComparison; unit?: string | null }) {
  return (
    <section className={`measurement-trend-summary is-${comparison.mode}`} aria-label="趋势对比摘要">
      <strong>{comparison.message}</strong>
      {comparison.mode !== "insufficient" ? (
        <dl>
          <div>
            <dt>最新值</dt>
            <dd>{formatValue(comparison.latestValue, unit)}</dd>
          </div>
          <div>
            <dt>基线值</dt>
            <dd>{formatValue(comparison.baselineValue, unit)}</dd>
          </div>
          <div>
            <dt>偏差</dt>
            <dd>{formatValue(comparison.deviation, unit)}</dd>
          </div>
          <div>
            <dt>偏差比例</dt>
            <dd>{formatPercent(comparison.deviationRatio)}</dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}

function SingleTaskTrendChart({
  metricName,
  points,
  unit,
}: {
  metricName: string;
  points: MeasurementTrendPoint[];
  unit?: string | null;
}) {
  const parsed = useMemo(() => parsePoints(points), [points]);
  if (parsed.length < 2) return null;

  const width = 920;
  const height = 300;
  const margin = { left: 62, right: 24, top: 28, bottom: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = parsed.map((point) => point.value);
  const valueMin = Math.min(...values);
  const valueMax = Math.max(...values);
  const valueRange = valueMax - valueMin || Math.abs(valueMax) * 0.1 || 1;
  const chartMin = valueMin - valueRange * 0.08;
  const chartMax = valueMax + valueRange * 0.08;
  const chartRange = chartMax - chartMin;
  const xFor = (index: number) => margin.left + (index / (parsed.length - 1)) * plotWidth;
  const yFor = (value: number) => margin.top + ((chartMax - value) / chartRange) * plotHeight;
  const path = parsed.map((point, index) => `${index === 0 ? "M" : "L"}${xFor(index).toFixed(2)},${yFor(point.value).toFixed(2)}`).join(" ");
  const areaPath = `${path} L${xFor(parsed.length - 1).toFixed(2)},${(margin.top + plotHeight).toFixed(2)} L${xFor(0).toFixed(2)},${(margin.top + plotHeight).toFixed(2)} Z`;
  const includesMultipleDates = new Set(parsed.map((point) => point.date)).size > 1;
  const tickIndexes = [...new Set(Array.from({ length: Math.min(6, parsed.length) }, (_, index) => (
    Math.round((index / Math.max(1, Math.min(6, parsed.length) - 1)) * (parsed.length - 1))
  )))];

  return (
    <div className="measurement-trend-chart">
      <div className="measurement-trend-chart-heading">
        <span>任务内趋势</span>
        {unit ? <span className="measurement-trend-chart-unit">单位：{unit}</span> : null}
      </div>
      <div className="measurement-trend-chart-scroll">
        <svg
          className="measurement-trend-chart-svg"
          data-testid="measurement-single-trend-chart"
          role="img"
          aria-label={`${metricName}任务内趋势图`}
          viewBox={`0 0 ${width} ${height}`}
        >
          {Array.from({ length: 5 }, (_, index) => {
            const ratio = index / 4;
            const y = margin.top + ratio * plotHeight;
            const value = chartMax - ratio * chartRange;
            return (
              <g key={index}>
                <line x1={margin.left} x2={width - margin.right} y1={y} y2={y} className="measurement-trend-grid-line" />
                <text x={margin.left - 10} y={y + 4} textAnchor="end" className="measurement-trend-axis-label">
                  {COMPACT_NUMBER.format(value)}
                </text>
              </g>
            );
          })}
          <path d={areaPath} className="measurement-trend-area" />
          <path d={path} className="measurement-trend-line" />
          {parsed.map((point, index) => (
            <circle
              key={`${point.source.time}-${point.source.object_key ?? "__all__"}-${index}`}
              cx={xFor(index)}
              cy={yFor(point.value)}
              r={index === parsed.length - 1 ? 4 : 2.5}
              className={index === parsed.length - 1 ? "measurement-trend-point is-latest" : "measurement-trend-point"}
            >
              <title>{`${formatPointTime(point.source.time)} · ${formatValue(point.value, unit)}`}</title>
            </circle>
          ))}
          {tickIndexes.map((index, tickIndex) => {
            const point = parsed[index];
            const textAnchor = tickIndex === 0 ? "start" : tickIndex === tickIndexes.length - 1 ? "end" : "middle";
            return (
              <text
                key={`${point.sortKey}-${index}`}
                x={xFor(index)}
                y={height - 20}
                textAnchor={textAnchor}
                className="measurement-trend-axis-label"
              >
                {formatChartTime(point, includesMultipleDates)}
              </text>
            );
          })}
        </svg>
      </div>
      <div className="measurement-trend-chart-note">共 {parsed.length} 个时间点，悬停数据点查看具体时间与数值。</div>
    </div>
  );
}

function TimePointDetail({ points, unit }: { points: MeasurementTrendPoint[]; unit?: string | null }) {
  const [requestedPage, setRequestedPage] = useState(1);
  const sortedPoints = useMemo(
    () => [...points].sort((left, right) => left.time.localeCompare(right.time)),
    [points],
  );
  const pageCount = Math.max(1, Math.ceil(sortedPoints.length / POINT_PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  const visiblePoints = sortedPoints.slice((page - 1) * POINT_PAGE_SIZE, page * POINT_PAGE_SIZE);

  if (!points.length) return null;
  return (
    <section className="measurement-time-point-detail">
      <h4>时间点明细</h4>
      <div className="measurement-detail-table-scroll">
        <table className="measurement-detail-table" aria-label="时间点明细">
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">对象</th>
              <th scope="col">周期</th>
              <th scope="col">值</th>
              <th scope="col">来源</th>
            </tr>
          </thead>
          <tbody>
            {visiblePoints.map((point, index) => (
              <tr key={`${point.time}-${point.object_key ?? "__all__"}-${point.period_minutes ?? "na"}-${index}`}>
                <td>{formatPointTime(point.time)}</td>
                <td>{point.object_key || "-"}</td>
                <td>{point.period_minutes ? `${point.period_minutes} 分钟` : "-"}</td>
                <td>{formatValue(point.value, unit)}</td>
                <td>{formatSourceEvidence(point)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pageCount > 1 ? (
        <nav className="measurement-detail-pagination" aria-label="时间点明细分页">
          <button type="button" disabled={page === 1} onClick={() => setRequestedPage(page - 1)}>上一页</button>
          <span>第 {page} / {pageCount} 页，共 {points.length} 条</span>
          <button type="button" disabled={page === pageCount} onClick={() => setRequestedPage(page + 1)}>下一页</button>
        </nav>
      ) : null}
    </section>
  );
}

function DailyAlignmentSummary({ points, unit }: { points: MeasurementTrendPoint[]; unit?: string | null }) {
  const dailyRows = useMemo(() => {
    const grouped = new Map<string, ParsedPoint[]>();
    for (const point of parsePoints(points)) {
      const group = grouped.get(point.date) ?? [];
      group.push(point);
      grouped.set(point.date, group);
    }
    return [...grouped.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([date, values]) => ({
        date,
        count: values.length,
        min: Math.min(...values.map((point) => point.value)),
        max: Math.max(...values.map((point) => point.value)),
        latest: values[values.length - 1],
      }));
  }, [points]);

  if (dailyRows.length < 2) return null;
  return (
    <section className="measurement-time-point-detail">
      <h4>按日对齐汇总</h4>
      <div className="measurement-detail-table-scroll">
        <table className="measurement-detail-table" aria-label="按日对齐汇总">
          <thead>
            <tr>
              <th scope="col">日期</th>
              <th scope="col">点数</th>
              <th scope="col">最小值</th>
              <th scope="col">最大值</th>
              <th scope="col">最新值</th>
            </tr>
          </thead>
          <tbody>
            {dailyRows.map((row) => (
              <tr key={row.date}>
                <td>{row.date}</td>
                <td>{row.count}</td>
                <td>{formatValue(row.min, unit)}</td>
                <td>{formatValue(row.max, unit)}</td>
                <td>{formatValue(row.latest.value, unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function MeasurementTrendDetail({
  metric,
  detailMetric: providedDetailMetric,
  taskId,
  ruleCode,
  unitId,
}: {
  metric: MetricTrendCellMetric;
  detailMetric?: MeasurementMetadataMetric | null;
  taskId?: string;
  ruleCode?: string;
  unitId?: string;
}) {
  const [loadedDetailMetric, setLoadedDetailMetric] = useState<MeasurementMetadataMetric | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TrendTab>("single");

  useEffect(() => {
    if (providedDetailMetric || loadedDetailMetric || detailError) return;
    if (!taskId || !ruleCode || !unitId) return;
    let cancelled = false;
    setDetailLoading(true);
    api
      .getMeasurementMetricDetail(taskId, ruleCode, unitId, metric.metric_resource_id)
      .then((detail) => {
        if (!cancelled) {
          startTransition(() => {
            setLoadedDetailMetric(detail.metric as unknown as MeasurementMetadataMetric);
            setDetailLoading(false);
          });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setDetailError(cause instanceof Error ? cause.message : "指标明细加载失败");
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    detailError,
    loadedDetailMetric,
    metric.metric_resource_id,
    providedDetailMetric,
    ruleCode,
    taskId,
    unitId,
  ]);

  const displayMetric = providedDetailMetric ?? loadedDetailMetric ?? metric;
  const allPoints = displayMetric.trend_points ?? metric.trend_points ?? [];
  const metricName = MetricDisplayName(displayMetric);
  const comparison = useMemo(() => analyzeTrendComparison(allPoints), [allPoints]);
  const summaryTrendPointCount = metric.trend_point_count ?? allPoints.length;
  const isAwaitingDetail =
    !providedDetailMetric &&
    !loadedDetailMetric &&
    !detailError &&
    summaryTrendPointCount >= 2 &&
    allPoints.length < 2;
  const insufficientPoints = allPoints.length < 2 && !isAwaitingDetail;

  return (
    <div className="measurement-trend-detail">
      {detailError ? (
        <div className="measurement-trend-warning" role="alert">
          <strong>指标明细加载失败，当前展示摘要数据</strong>
          <span>{detailError}</span>
        </div>
      ) : null}
      {detailLoading || isAwaitingDetail ? (
        <div className="measurement-trend-loading-note" role="status">正在加载完整明细…</div>
      ) : null}
      <div className="measurement-trend-tabs" role="tablist" aria-label="趋势视图">
        {([
          ["single", "单任务"],
          ["history", "历史对比"],
          ["version", "版本对比"],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            id={`measurement-trend-tab-${key}`}
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            aria-controls={`measurement-trend-panel-${key}`}
            className={activeTab === key ? "is-active" : undefined}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "single" ? (
        <div
          id="measurement-trend-panel-single"
          role="tabpanel"
          aria-labelledby="measurement-trend-tab-single"
          className="measurement-trend-panel"
        >
          {isAwaitingDetail ? (
            <div className="measurement-trend-panel-loading" role="status">正在加载趋势数据…</div>
          ) : insufficientPoints ? (
            <>
              <div className="measurement-trend-warning" role="alert">
                <strong>趋势点不足，无法判断趋势</strong>
                <span>{insufficientPointsReason(allPoints.length, displayMetric.trend_reason)}</span>
              </div>
              <p className="measurement-trend-guidance">可核对下方时间点明细，或切换历史对比、版本对比查看其他任务的数据。</p>
              <TimePointDetail points={allPoints} unit={metric.display_unit} />
            </>
          ) : (
            <>
              <TrendComparisonSummary comparison={comparison} unit={metric.display_unit} />
              <SingleTaskTrendChart metricName={metricName} points={allPoints} unit={metric.display_unit} />
              {comparison.mode === "multi_day" ? (
                <DailyAlignmentSummary points={allPoints} unit={metric.display_unit} />
              ) : null}
              <TimePointDetail points={allPoints} unit={metric.display_unit} />
            </>
          )}
        </div>
      ) : (
        <div
          id={`measurement-trend-panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`measurement-trend-tab-${activeTab}`}
          className="measurement-trend-panel"
        >
          <Suspense fallback={<div className="measurement-trend-panel-loading" role="status">正在加载对比数据…</div>}>
            {activeTab === "history" ? (
              <HistoryTrendPanel
                metric={displayMetric}
                taskId={taskId}
                ruleCode={ruleCode}
                unitId={unitId}
                unit={metric.display_unit}
              />
            ) : (
              <VersionComparePanel
                metric={displayMetric}
                taskId={taskId}
                ruleCode={ruleCode}
                unitId={unitId}
                unit={metric.display_unit}
              />
            )}
          </Suspense>
        </div>
      )}
    </div>
  );
}
