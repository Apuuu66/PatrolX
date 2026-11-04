import { Fragment, useState } from "react";

import type {
  MeasurementMetadataMetric,
  MeasurementMetadataMetricObservation,
  MeasurementMetadataUnit,
  MeasurementTrend,
} from "../api/http";

const PAGE_SIZE = 10;

const BUSINESS_STATUS_LABELS: Record<string, string> = {
  normal: "正常",
  warn: "阈值预警",
  fail: "阈值失败",
  unconfigured: "未配置阈值",
  not_applicable: "不适用",
  not_judgeable: "无法判定",
};

const DIRECTION_LABELS: Record<string, string> = {
  higher_better: "越高越好",
  lower_better: "越低越好",
  neutral: "不判定",
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

const TREND_SIGNAL_COLORS: Record<string, string> = {
  improved: "green",
  worsened: "red",
  none: "blue",
};

const TREND_SIGNAL_LABELS: Record<string, string> = {
  improved: "改善",
  worsened: "恶化",
  none: "无方向信号",
};

const STATUS_COLORS: Record<string, string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
};

type DerivedMetric = NonNullable<MeasurementMetadataUnit["derived_metrics"]>[number];
type DerivedObservation = DerivedMetric["observations"][number];

function InlineTag({ color = "default", children }: { color?: string; children: React.ReactNode }) {
  return <span className={`measurement-inline-tag measurement-inline-tag--${color}`}>{children}</span>;
}

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return value.toFixed(digits);
}

function usePaginatedRows<T>(rows: T[]) {
  const [requestedPage, setRequestedPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  return {
    page,
    pageCount,
    rows: rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    setPage: setRequestedPage,
  };
}

function PaginationControls({
  page,
  pageCount,
  ariaLabel,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  ariaLabel: string;
  onPageChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  return (
    <nav className="measurement-detail-pagination" aria-label={ariaLabel}>
      <button type="button" disabled={page === 1} onClick={() => onPageChange(page - 1)}>
        上一页
      </button>
      <span>第 {page} / {pageCount} 页</span>
      <button type="button" disabled={page === pageCount} onClick={() => onPageChange(page + 1)}>
        下一页
      </button>
    </nav>
  );
}

function TrendTable({ trends }: { trends: MeasurementTrend[] }) {
  const pagination = usePaginatedRows(trends);
  return (
    <div className="measurement-detail-section">
      <h4>趋势判定</h4>
      <div className="measurement-detail-table-scroll">
        <table className="measurement-detail-table" aria-label="趋势判定明细">
          <thead>
            <tr>
              <th scope="col">行对象</th>
              <th scope="col">周期(分钟)</th>
              <th scope="col">趋势标签</th>
              <th scope="col">方向信号</th>
              <th scope="col">说明</th>
              <th scope="col">趋势点数</th>
            </tr>
          </thead>
          <tbody>
            {pagination.rows.map((trend) => (
              <tr key={`${trend.object_key ?? "__all__"}-${trend.period_minutes ?? "unknown"}-${trend.label}`}>
                <td>{trend.object_key || "__all__"}</td>
                <td>{trend.period_minutes ?? "-"}</td>
                <td>{TREND_LABELS[trend.label] ?? trend.label}</td>
                <td>
                  <InlineTag color={TREND_SIGNAL_COLORS[trend.signal]}>
                    {TREND_SIGNAL_LABELS[trend.signal] ?? trend.signal}
                  </InlineTag>
                </td>
                <td>{trend.reason || "-"}</td>
                <td>{trend.point_count ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationControls
        page={pagination.page}
        pageCount={pagination.pageCount}
        ariaLabel="趋势判定分页"
        onPageChange={pagination.setPage}
      />
    </div>
  );
}

function ObservationTable({
  observations,
  showAllColumns,
}: {
  observations: MeasurementMetadataMetricObservation[];
  showAllColumns: boolean;
}) {
  const pagination = usePaginatedRows(observations);
  return (
    <div className="measurement-detail-section">
      <h4>行对象明细</h4>
      <div className="measurement-detail-table-scroll">
        <table className="measurement-detail-table" aria-label="行对象明细">
          <thead>
            <tr>
              <th scope="col">行对象</th>
              <th scope="col">行数</th>
              <th scope="col">有效值</th>
              {showAllColumns ? <th scope="col">空值</th> : null}
              {showAllColumns ? <th scope="col">解析错误</th> : null}
              <th scope="col">业务状态</th>
              {showAllColumns ? <th scope="col">均值</th> : null}
              <th scope="col">数值特征</th>
            </tr>
          </thead>
          <tbody>
            {pagination.rows.map((observation) => (
              <tr key={observation.object_key}>
                <td>{observation.object_key}</td>
                <td>{observation.row_count}</td>
                <td>{observation.valid_count}</td>
                {showAllColumns ? <td>{observation.null_count}</td> : null}
                {showAllColumns ? <td>{observation.parse_error_count}</td> : null}
                <td>
                  {observation.business_status
                    ? BUSINESS_STATUS_LABELS[observation.business_status] ?? observation.business_status
                    : "-"}
                </td>
                {showAllColumns ? <td>{formatNumber(observation.avg_value)}</td> : null}
                <td>
                  {observation.value_pattern === "all_zero" ? (
                    <InlineTag color="blue">全 0</InlineTag>
                  ) : observation.value_pattern === "unknown" ? (
                    <InlineTag>无数据</InlineTag>
                  ) : (
                    <InlineTag color="green">正常</InlineTag>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationControls
        page={pagination.page}
        pageCount={pagination.pageCount}
        ariaLabel="行对象明细分页"
        onPageChange={pagination.setPage}
      />
    </div>
  );
}

export function MeasurementMetricDetail({
  metric,
  detail,
  showAllColumns,
  isLoading,
  error,
  onRetry,
}: {
  metric: MeasurementMetadataMetric;
  detail?: MeasurementMetadataMetric;
  showAllColumns: boolean;
  isLoading: boolean;
  error?: string;
  onRetry: () => void;
}) {
  const displayMetric = detail ?? metric;

  return (
    <section className="measurement-metric-detail" data-testid="measurement-metric-detail">
      <dl className="measurement-detail-facts">
        <div>
          <dt>指标分组</dt>
          <dd>{displayMetric.metric_group || "未分组"}</dd>
        </div>
        <div>
          <dt>方向</dt>
          <dd>{DIRECTION_LABELS[displayMetric.direction ?? "neutral"]}</dd>
        </div>
        <div>
          <dt>预警阈值</dt>
          <dd>{displayMetric.warning_threshold ?? "-"}</dd>
        </div>
        <div>
          <dt>失败阈值</dt>
          <dd>{displayMetric.critical_threshold ?? "-"}</dd>
        </div>
      </dl>
      {isLoading ? <div className="measurement-detail-loading" role="status">正在加载完整明细…</div> : null}
      {error ? (
        <div className="measurement-detail-error" role="alert">
          <div>
            <strong>指标明细加载失败</strong>
            <p>{error}</p>
          </div>
          <button type="button" onClick={onRetry}>重试</button>
        </div>
      ) : null}
      {displayMetric.errors?.length ? (
        <pre className="measurement-detail-errors">{JSON.stringify(displayMetric.errors)}</pre>
      ) : null}
      {displayMetric.trends?.length ? <TrendTable trends={displayMetric.trends} /> : null}
      {displayMetric.observations?.length ? (
        <ObservationTable observations={displayMetric.observations} showAllColumns={showAllColumns} />
      ) : (
        <div className="measurement-detail-empty">没有行数据</div>
      )}
    </section>
  );
}

function DerivedObservationTable({ observations }: { observations: DerivedObservation[] }) {
  return (
    <div className="measurement-detail-table-scroll">
      <table className="measurement-detail-table" aria-label="派生指标行对象明细">
        <thead>
          <tr>
            <th scope="col">行对象</th>
            <th scope="col">状态</th>
            <th scope="col">值</th>
            <th scope="col">说明</th>
          </tr>
        </thead>
        <tbody>
          {observations.map((observation) => (
            <tr key={observation.object_key}>
              <td>{observation.object_key}</td>
              <td>
                <InlineTag color={STATUS_COLORS[observation.status]}>
                  {observation.status.toUpperCase()}
                </InlineTag>
              </td>
              <td>{observation.value === null || observation.value === undefined ? "-" : `${observation.value.toFixed(2)}%`}</td>
              <td>{observation.message || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MeasurementDerivedMetrics({ metrics }: { metrics: DerivedMetric[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const pagination = usePaginatedRows(metrics);

  const toggleMetric = (metricId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(metricId)) next.delete(metricId);
      else next.add(metricId);
      return next;
    });
  };

  return (
    <section className="measurement-derived-card" aria-labelledby="measurement-derived-title">
      <h3 id="measurement-derived-title">派生指标</h3>
      <div className="measurement-detail-table-scroll">
        <table className="measurement-detail-table" aria-label="派生指标列表">
          <thead>
            <tr>
              <th scope="col"><span className="visually-hidden">展开</span></th>
              <th scope="col">派生指标</th>
              <th scope="col">状态</th>
              <th scope="col">说明</th>
              <th scope="col">覆盖率</th>
            </tr>
          </thead>
          <tbody>
            {pagination.rows.map((metric) => {
              const isExpanded = expanded.has(metric.metric_resource_id);
              const name = metric.metric_resource_name_zh || metric.metric_resource_id;
              const validCount = metric.observations.filter((item) => item.value !== null && item.value !== undefined).length;
              return (
                <Fragment key={metric.metric_resource_id}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="measurement-metric-toggle"
                        aria-expanded={isExpanded}
                        aria-label={`${isExpanded ? "收起" : "展开"}${name}行对象`}
                        onClick={() => toggleMetric(metric.metric_resource_id)}
                      >
                        {isExpanded ? "−" : "+"}
                      </button>
                    </td>
                    <td>
                      <div className="measurement-metric-name">
                        <div>{name}</div>
                        {name !== metric.metric_resource_id ? (
                          <span className="measurement-metric-resource-id">{metric.metric_resource_id}</span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <InlineTag color={STATUS_COLORS[metric.status]}>
                        {metric.status.toUpperCase()}
                      </InlineTag>
                    </td>
                    <td>{metric.message || "-"}</td>
                    <td>{metric.observations.length ? `${validCount}/${metric.observations.length}` : "-"}</td>
                  </tr>
                  {isExpanded ? (
                    <tr className="measurement-detail-expanded-row">
                      <td colSpan={5}>
                        <DerivedObservationTable observations={metric.observations} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <PaginationControls
        page={pagination.page}
        pageCount={pagination.pageCount}
        ariaLabel="派生指标分页"
        onPageChange={pagination.setPage}
      />
    </section>
  );
}
