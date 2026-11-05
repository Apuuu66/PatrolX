import { useEffect, useMemo, useState } from "react";

import {
  api,
  type KpiDailyBucket,
  type KpiDailyHealthGroup,
  type KpiDailyHealthMetricDetail,
} from "../api/http";

const CURRENT_LABELS: Record<string, string> = {
  normal: "正常",
  warn: "预警",
  fail: "失败",
  pending_config: "待配置",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};

const TREND_LABELS: Record<string, string> = {
  improved: "改善",
  stable: "稳定",
  worsened: "恶化",
  observe: "关注",
  no_baseline: "无昨日基线",
};

const CONSISTENCY_LABELS: Record<string, string> = {
  not_checked: "未检查",
  within_tolerance: "容差内",
  exceeded: "超出容差",
  unavailable: "不可用",
};

const BUCKET_STATUS_LABELS: Record<string, string> = {
  ok: "有数据",
  no_data: "无数据",
  zero_denominator: "分母为零",
  unreadable: "不可读",
  no_baseline: "无基线",
};

function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "不适用";
  return `${value.toFixed(1)}%`;
}

function groupBucketText(group: KpiDailyHealthGroup, bucket: "today" | "yesterday", isPercentage: boolean): string {
  const value = group[bucket];
  if (!value) return "无数据";
  if (value.status === "zero_denominator") return group.reason || "不适用（分母为 0）";
  if (value.value === null) {
    return group.reason || BUCKET_STATUS_LABELS[value.status] || "无数据";
  }
  return isPercentage ? formatRate(value.value) : formatNumber(value.value, 4);
}

function BucketEvidence({
  label,
  bucket,
  group,
  isPercentage,
}: {
  label: string;
  bucket: KpiDailyBucket | null | undefined;
  group: KpiDailyHealthGroup;
  isPercentage: boolean;
}) {
  const valueText = groupBucketText(group, label === "今日" ? "today" : "yesterday", isPercentage);
  return (
    <div className="kpi-health-bucket">
      <div className="kpi-health-bucket-title">
        <strong>{label}</strong>
        <span>{bucket?.date ?? "—"}</span>
      </div>
      <div className="kpi-health-bucket-value">{label}：{valueText}</div>
      <p>{bucket?.status ? BUCKET_STATUS_LABELS[bucket.status] ?? bucket.status : "无数据"}</p>
      {bucket?.numerator !== null && bucket?.numerator !== undefined
        && bucket?.denominator !== null && bucket?.denominator !== undefined ? (
        <code>
          {formatNumber(bucket.numerator)} / {formatNumber(bucket.denominator)}
          {" = "}
          {formatRate(bucket.value)}
        </code>
      ) : null}
      <span className="kpi-health-secondary">有效点 {bucket?.valid_count ?? 0}</span>
      {bucket?.first_measured_at ? (
        <span className="kpi-health-secondary">首次测量 {bucket.first_measured_at}</span>
      ) : null}
      {bucket?.last_measured_at ? (
        <span className="kpi-health-secondary">最后测量 {bucket.last_measured_at}</span>
      ) : null}
    </div>
  );
}

function SevenDayTrend({ points, isPercentage }: { points: KpiDailyBucket[]; isPercentage: boolean }) {
  const chart = useMemo(() => {
    const width = 720;
    const height = 190;
    const padding = { top: 18, right: 24, bottom: 38, left: 50 };
    const values = points.flatMap((point) => typeof point.value === "number" ? [point.value] : []);
    const min = values.length > 0 ? Math.min(...values) : 0;
    const max = values.length > 0 ? Math.max(...values) : 1;
    const spread = max - min || 1;
    const paddedMin = min - spread * 0.12;
    const paddedMax = max + spread * 0.12;
    const x = (index: number) => padding.left + (index / Math.max(1, points.length - 1)) * (width - padding.left - padding.right);
    const y = (value: number) => padding.top + ((paddedMax - value) / (paddedMax - paddedMin)) * (height - padding.top - padding.bottom);
    let path = "";
    let drawing = false;
    const marks = points.map((point, index) => {
      const value = point.value;
      if (typeof value !== "number") {
        drawing = false;
        return { point, x: x(index), y: null };
      }
      path += `${drawing ? " L" : " M"} ${x(index).toFixed(2)} ${y(value).toFixed(2)}`;
      drawing = true;
      return { point, x: x(index), y: y(value) };
    });
    return { width, height, path, marks, padding, min, max };
  }, [points]);

  return (
    <section className="kpi-health-seven-day" aria-labelledby="kpi-health-seven-day-title" data-testid="daily-health-seven-day-trend">
      <div className="kpi-health-section-heading">
        <div>
          <h4 id="kpi-health-seven-day-title">近 7 日趋势</h4>
          <p>按 UTC+8 自然日聚合；空心点表示当日无有效值。</p>
        </div>
        <span className="kpi-health-secondary">
          {points.filter((point) => point.value !== null).length}/{points.length} 天有数据
        </span>
      </div>
      <div className="kpi-health-chart-scroll">
        <svg
          className="kpi-health-line-chart"
          viewBox={`0 0 ${chart.width} ${chart.height}`}
          role="img"
          aria-label="KPI 近 7 日趋势图"
        >
          <line
            x1={chart.padding.left}
            x2={chart.width - chart.padding.right}
            y1={chart.height - chart.padding.bottom}
            y2={chart.height - chart.padding.bottom}
            className="kpi-health-chart-axis"
          />
          <text x="8" y={chart.padding.top + 5} className="kpi-health-chart-label">
            {isPercentage ? formatRate(chart.max) : formatNumber(chart.max, 2)}
          </text>
          <text x="8" y={chart.height - chart.padding.bottom} className="kpi-health-chart-label">
            {isPercentage ? formatRate(chart.min) : formatNumber(chart.min, 2)}
          </text>
          <path d={chart.path} className="kpi-health-chart-path" />
          {chart.marks.map(({ point, x, y: pointY }, index) => (
            <g key={`${point.date}-${index}`}>
              {pointY !== null ? (
                <>
                  <circle cx={x} cy={pointY} r="5" className="kpi-health-chart-point" />
                  <title>
                    {point.date}：{isPercentage ? formatRate(point.value) : formatNumber(point.value, 4)}
                  </title>
                </>
              ) : (
                <circle cx={x} cy={chart.height - chart.padding.bottom} r="4" className="kpi-health-chart-point is-empty" />
              )}
              <text x={x} y={chart.height - 14} textAnchor="middle" className="kpi-health-chart-date">
                {point.date.slice(5)}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </section>
  );
}

export function KpiMetricHealthDetail({
  taskId,
  ruleCode,
  measurementUnitId,
  metricResourceId,
}: {
  taskId: string;
  ruleCode: string;
  measurementUnitId: string;
  metricResourceId: string;
}) {
  const [detail, setDetail] = useState<KpiDailyHealthMetricDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api.getKpiDailyHealthMetric(taskId, ruleCode, measurementUnitId, metricResourceId)
      .then((value) => {
        if (!cancelled) setDetail(value);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "指标证据加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [measurementUnitId, metricResourceId, reloadKey, ruleCode, taskId]);

  if (loading && !detail) {
    return <div className="kpi-health-evidence-loading" role="status">正在加载指标证据…</div>;
  }

  if (error || !detail) {
    return (
      <div className="kpi-health-evidence-error" role="alert">
        <strong>指标证据加载失败</strong>
        <p>{error ?? "接口没有返回指标证据"}</p>
        <button type="button" className="kpi-health-evidence-button" onClick={() => setReloadKey((value) => value + 1)}>
          重试
        </button>
      </div>
    );
  }

  const isPercentage = detail.metric.role === "derived" || detail.metric.daily_aggregation === "formula";
  const consistency = detail.metric.consistency;
  const consistencyText = consistency.status === "within_tolerance" && consistency.difference_pp !== null
    ? `${CONSISTENCY_LABELS[consistency.status]}（${formatNumber(consistency.difference_pp, 2)}pp，容差 ${formatNumber(consistency.tolerance_pp, 2)}pp）`
    : `${CONSISTENCY_LABELS[consistency.status] ?? consistency.status}（容差 ${formatNumber(consistency.tolerance_pp, 2)}pp）`;
  const threshold = detail.metric.current_threshold;
  const change = detail.metric.change_threshold;

  return (
    <article className="kpi-health-detail">
      <div className="kpi-health-detail-summary">
        <div>
          <span className="kpi-health-secondary">{detail.metric_resource_id}</span>
          <h3>{detail.metric.name_zh || detail.metric_resource_id}</h3>
          <p>
            <span className={`kpi-health-pill kpi-health-pill--${detail.metric.current_status}`}>
              {CURRENT_LABELS[detail.metric.current_status] ?? detail.metric.current_status}
            </span>
            <span className={`kpi-health-pill kpi-health-pill--trend-${detail.metric.trend_status}`}>
              {TREND_LABELS[detail.metric.trend_status] ?? detail.metric.trend_status}
            </span>
          </p>
        </div>
        <dl className="kpi-health-detail-facts">
          <div>
            <dt>数据日期</dt>
            <dd>{detail.metric.data_date ?? "—"}</dd>
          </div>
          <div>
            <dt>对比日期</dt>
            <dd>{detail.metric.previous_date ?? "—"}</dd>
          </div>
          <div>
            <dt>日聚合方式</dt>
            <dd>日聚合：{detail.metric.daily_aggregation}</dd>
          </div>
          <div>
            <dt>指标角色</dt>
            <dd>{detail.metric.role === "derived" ? "聚合指标" : "基础指标"}</dd>
          </div>
        </dl>
      </div>

      {detail.metric.formula ? (
        <div className="kpi-health-formula">
          <span>日聚合公式</span>
          <code>{detail.metric.formula}</code>
        </div>
      ) : null}

      <div className="kpi-health-evidence-grid">
        <div className="kpi-health-evidence-item">
          <strong>当前阈值</strong>
          <span>
            {threshold.direction === "higher_better" ? "越高越好" : threshold.direction === "lower_better" ? "越低越好" : "方向未配置"}
          </span>
          <span>预警 {threshold.warning_threshold ?? "—"} / 失败 {threshold.critical_threshold ?? "—"}</span>
          <span className="kpi-health-secondary">来源：{threshold.source}</span>
        </div>
        <div className="kpi-health-evidence-item">
          <strong>日变化阈值</strong>
          <span>
            {change.value === null ? "未配置" : `${formatNumber(change.value, 2)} ${change.unit === "unavailable" ? "" : change.unit}`}
          </span>
          <span className="kpi-health-secondary">来源：{change.source}</span>
        </div>
        <div className="kpi-health-evidence-item">
          <strong>一致性检查</strong>
          <span>一致性检查：{consistencyText}</span>
        </div>
      </div>

      <section className="kpi-health-group-section" aria-labelledby="kpi-health-groups-title">
        <div className="kpi-health-section-heading">
          <div>
            <h4 id="kpi-health-groups-title">对象与周期证据</h4>
            <p>成功率按同一对象、同一周期的分子总和 ÷ 分母总和计算，不取分钟成功率均值。</p>
          </div>
        </div>
        <div className="kpi-health-group-list">
          {detail.groups.length > 0 ? detail.groups.map((group) => {
            const sourceFiles = group.source_files?.length ? group.source_files : ["—"];
            return (
            <article
              className="kpi-health-group"
              data-testid="daily-health-group"
              key={`${group.object_key}:${group.period_minutes ?? "all"}`}
            >
              <header>
                <div>
                  <strong>{group.object_key}</strong>
                  <span>{group.period_minutes === null ? "全周期" : `${group.period_minutes} 分钟`}</span>
                </div>
                <div className="kpi-health-group-tags">
                  <span className={`kpi-health-pill kpi-health-pill--${group.current_status}`}>
                    {CURRENT_LABELS[group.current_status] ?? group.current_status}
                  </span>
                  <span className={`kpi-health-pill kpi-health-pill--trend-${group.trend_status}`}>
                    {TREND_LABELS[group.trend_status] ?? group.trend_status}
                  </span>
                </div>
              </header>
              <div className="kpi-health-buckets">
                <BucketEvidence label="今日" bucket={group.today} group={group} isPercentage={isPercentage} />
                <BucketEvidence label="昨日" bucket={group.yesterday} group={group} isPercentage={isPercentage} />
              </div>
              <div className="kpi-health-group-footer">
                <span>判定：{group.reason || "无补充说明"}</span>
                <span>来源文件：</span>
                {sourceFiles.map((source) => (
                  <code key={source}>{source}</code>
                ))}
              </div>
            </article>
            );
          }) : (
            <div className="kpi-health-empty">没有对象与周期证据。</div>
          )}
        </div>
      </section>

      <SevenDayTrend points={detail.seven_day_trend} isPercentage={isPercentage} />
    </article>
  );
}
