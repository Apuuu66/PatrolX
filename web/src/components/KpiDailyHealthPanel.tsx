import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import type { KpiDailyHealthMetricDetail } from "../api/http";

export type KpiDailyHealthCurrentStatus =
  | "normal"
  | "warn"
  | "fail"
  | "pending_config"
  | "unable_to_judge"
  | "not_applicable";

export type KpiDailyHealthTrendStatus =
  | "improved"
  | "stable"
  | "worsened"
  | "observe"
  | "no_baseline";

export interface KpiDailyHealthThreshold {
  direction: "higher_better" | "lower_better" | "neutral" | null;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
  source: string;
}

export interface KpiDailyHealthChangeThreshold {
  value: number | null;
  unit: "pp" | "relative" | "unavailable";
  source: string;
}

export interface KpiDailyHealthConsistency {
  status: "not_checked" | "within_tolerance" | "exceeded" | "unavailable";
  tolerance_pp: number;
  difference_pp?: number | null;
}

export interface KpiDailyHealthMetricObject {
  object_key: string;
  period_minutes: number | null;
  current_status: KpiDailyHealthCurrentStatus;
  current_reason?: string;
  current_reason_code?: string;
  today_value?: number | null;
  yesterday_value?: number | null;
  trend_status: KpiDailyHealthTrendStatus;
  trend_reason?: string;
  trend_reason_code?: string;
  numerator?: number | null;
  denominator?: number | null;
  valid_count: number;
  first_measured_at?: string | null;
  last_measured_at?: string | null;
  source_files?: string[];
}

export interface KpiDailyHealthMetric {
  measurement_unit_id: string;
  measurement_unit_name_zh: string;
  measurement_unit_enabled: boolean;
  metric_resource_id: string;
  metric_resource_name_zh: string;
  metric_resource_enabled: boolean;
  binding_confirmed: boolean;
  role: "base" | "derived";
  importance: "P0" | "P1" | "P2" | "normal";
  direction: "higher_better" | "lower_better" | "neutral" | null;
  display_unit?: string | null;
  is_percentage: boolean;
  current_status: KpiDailyHealthCurrentStatus;
  current_reason: string;
  current_reason_text: string;
  today_value: number | null;
  today_display: string | null;
  yesterday_value: number | null;
  yesterday_display: string | null;
  delta: number | null;
  delta_display: string | null;
  trend_status: KpiDailyHealthTrendStatus;
  trend_reason: string;
  trend_reason_code: string;
  current_threshold: KpiDailyHealthThreshold;
  change_threshold: KpiDailyHealthChangeThreshold;
  daily_aggregation: string;
  aggregation_source: string;
  zero_semantics: string;
  consistency: KpiDailyHealthConsistency;
  objects: KpiDailyHealthMetricObject[];
}

export interface KpiDailyHealthScope {
  enabled_measurement_unit_count: number;
  confirmed_binding_metric_count: number;
  expected_metric_count: number;
  out_of_scope_file_count: number;
  unconfirmed_binding_count: number;
  out_of_scope_reason_counts: Record<string, number>;
}

export interface KpiDailyHealthLegacyFallback {
  code: string;
  message: string;
}

export interface KpiDailyHealthSnapshot {
  schema_version: number;
  timezone: string;
  data_date: string;
  previous_date: string;
  latest_measured_at: string | null;
  legacy_fallback: KpiDailyHealthLegacyFallback | null;
  current_counts: Partial<Record<KpiDailyHealthCurrentStatus, number>>;
  trend_counts: Partial<Record<KpiDailyHealthTrendStatus, number>>;
  scope: KpiDailyHealthScope;
  metrics: KpiDailyHealthMetric[];
}

const CURRENT_STATUSES: KpiDailyHealthCurrentStatus[] = [
  "normal",
  "warn",
  "fail",
  "pending_config",
  "unable_to_judge",
  "not_applicable",
];

const TREND_STATUSES: KpiDailyHealthTrendStatus[] = [
  "improved",
  "stable",
  "worsened",
  "observe",
  "no_baseline",
];

const CURRENT_LABELS: Record<KpiDailyHealthCurrentStatus, string> = {
  normal: "正常",
  warn: "预警",
  fail: "失败",
  pending_config: "待配置",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};

const TREND_LABELS: Record<KpiDailyHealthTrendStatus, string> = {
  improved: "改善",
  stable: "稳定",
  worsened: "恶化",
  observe: "关注",
  no_baseline: "无昨日基线",
};

const CURRENT_FOCUS_ORDER: Record<KpiDailyHealthCurrentStatus, number> = {
  fail: 0,
  warn: 1,
  pending_config: 2,
  unable_to_judge: 3,
  not_applicable: 4,
  normal: 5,
};

const TREND_FOCUS_ORDER: Record<KpiDailyHealthTrendStatus, number> = {
  worsened: 0,
  observe: 1,
  no_baseline: 2,
  improved: 3,
  stable: 4,
};

const IMPORTANCE_ORDER: Record<KpiDailyHealthMetric["importance"], number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  normal: 3,
};

const OUT_OF_SCOPE_REASON_LABELS: Record<string, string> = {
  disabled_unit: "停用测量单元",
  unconfirmed_binding: "未确认绑定",
};

const MetricDetail = lazy(() =>
  import("./KpiMetricHealthDetail").then((module) => ({ default: module.KpiMetricHealthDetail })),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asSnapshot(value: unknown): KpiDailyHealthSnapshot | null {
  if (!isRecord(value) || typeof value.data_date !== "string" || !Array.isArray(value.metrics)) {
    return null;
  }
  const rawScope = isRecord(value.scope) ? value.scope : {};
  return {
    schema_version: typeof value.schema_version === "number" ? value.schema_version : 1,
    timezone: typeof value.timezone === "string" ? value.timezone : "Asia/Shanghai",
    data_date: value.data_date,
    previous_date: typeof value.previous_date === "string" ? value.previous_date : "-",
    latest_measured_at: typeof value.latest_measured_at === "string" ? value.latest_measured_at : null,
    legacy_fallback: isRecord(value.legacy_fallback)
      ? {
          code: String(value.legacy_fallback.code ?? "legacy_result"),
          message: String(value.legacy_fallback.message ?? "旧任务缺少日健康判定，请重跑任务"),
        }
      : null,
    current_counts: isRecord(value.current_counts) ? value.current_counts : {},
    trend_counts: isRecord(value.trend_counts) ? value.trend_counts : {},
    scope: {
      enabled_measurement_unit_count: Number(rawScope.enabled_measurement_unit_count ?? 0),
      confirmed_binding_metric_count: Number(rawScope.confirmed_binding_metric_count ?? 0),
      expected_metric_count: Number(rawScope.expected_metric_count ?? value.metrics.length),
      out_of_scope_file_count: Number(rawScope.out_of_scope_file_count ?? 0),
      unconfirmed_binding_count: Number(rawScope.unconfirmed_binding_count ?? 0),
      out_of_scope_reason_counts: isRecord(rawScope.out_of_scope_reason_counts)
        ? Object.fromEntries(Object.entries(rawScope.out_of_scope_reason_counts).map(([key, count]) => [key, Number(count)]))
        : {},
    },
    metrics: value.metrics as KpiDailyHealthMetric[],
  };
}

function countStatuses<T extends string>(metrics: KpiDailyHealthMetric[], statuses: T[], key: "current_status" | "trend_status") {
  return Object.fromEntries(
    statuses.map((status) => [status, metrics.filter((metric) => metric[key] === status).length]),
  ) as Record<T, number>;
}

function focusMetrics(metrics: KpiDailyHealthMetric[]): KpiDailyHealthMetric[] {
  return [...metrics]
    .filter((metric) =>
      metric.current_status === "fail"
      || metric.current_status === "warn"
      || metric.current_status === "pending_config"
      || metric.current_status === "unable_to_judge"
      || metric.trend_status === "worsened"
    )
    .sort((left, right) => {
      const statusOrder = CURRENT_FOCUS_ORDER[left.current_status] - CURRENT_FOCUS_ORDER[right.current_status];
      if (statusOrder !== 0) return statusOrder;
      const trendOrder = TREND_FOCUS_ORDER[left.trend_status] - TREND_FOCUS_ORDER[right.trend_status];
      if (trendOrder !== 0) return trendOrder;
      const importanceOrder = IMPORTANCE_ORDER[left.importance] - IMPORTANCE_ORDER[right.importance];
      if (importanceOrder !== 0) return importanceOrder;
      return `${left.measurement_unit_name_zh}${left.metric_resource_name_zh}`.localeCompare(
        `${right.measurement_unit_name_zh}${right.metric_resource_name_zh}`,
        "zh-CN",
      );
    });
}

function StatusPill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return <span className={`kpi-health-pill kpi-health-pill--${tone}`}>{children}</span>;
}

function LegacyPanel({ message }: { message: string }) {
  return (
    <section className="kpi-health-legacy" aria-labelledby="kpi-health-legacy-title">
      <h3 id="kpi-health-legacy-title">KPI 日健康兼容提示</h3>
      <p>{message}</p>
      <p>当前仍可查看原有 KPI 指标与巡检发现；如需日健康结论，请重新执行 KPI 巡检。</p>
    </section>
  );
}

export function KpiDailyHealthPanel({
  metadata,
  taskId,
  ruleCode,
}: {
  metadata?: Record<string, unknown>;
  taskId?: string;
  ruleCode?: string;
}) {
  const snapshot = useMemo(() => asSnapshot(metadata?.daily_health), [metadata]);
  const [evidenceMetric, setEvidenceMetric] = useState<KpiDailyHealthMetric | null>(null);
  const [currentFilter, setCurrentFilter] = useState<KpiDailyHealthCurrentStatus | "all">("all");
  const [trendFilter, setTrendFilter] = useState<KpiDailyHealthTrendStatus | "all">("all");

  useEffect(() => {
    setEvidenceMetric(null);
    setCurrentFilter("all");
    setTrendFilter("all");
  }, [taskId, ruleCode]);

  if (!snapshot) {
    return <LegacyPanel message="旧任务没有日健康结论；请重新执行 KPI 巡检后查看当前判定与昨日趋势。" />;
  }

  const currentCounts = countStatuses(snapshot.metrics, CURRENT_STATUSES, "current_status");
  const trendCounts = countStatuses(snapshot.metrics, TREND_STATUSES, "trend_status");
  const visibleCurrentStatuses = CURRENT_STATUSES.filter((status) => currentCounts[status] > 0);
  const visibleTrendStatuses = TREND_STATUSES.filter((status) => trendCounts[status] > 0);
  const filteredMetrics = snapshot.metrics.filter((metric) =>
    (currentFilter === "all" || metric.current_status === currentFilter)
    && (trendFilter === "all" || metric.trend_status === trendFilter)
  );
  const focus = focusMetrics(snapshot.metrics);
  const outOfScopeReasons = Object.entries(snapshot.scope.out_of_scope_reason_counts)
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${OUT_OF_SCOPE_REASON_LABELS[reason] ?? reason} ${count}`);

  return (
    <section className="kpi-daily-health" aria-labelledby="kpi-daily-health-title">
      <header className="kpi-daily-health-header">
        <div>
          <p className="kpi-daily-health-eyebrow">维护人员首屏结论</p>
          <h3 id="kpi-daily-health-title">KPI 当前判定与昨日趋势</h3>
          <p className="kpi-daily-health-meta">
            数据日期 {snapshot.data_date} ｜ 对比日 {snapshot.previous_date} ｜ {snapshot.timezone}
            {snapshot.latest_measured_at ? ` ｜ 最新测量 ${snapshot.latest_measured_at}` : ""}
          </p>
        </div>
        <StatusPill tone="scope">仅统计已启用范围</StatusPill>
      </header>

      {snapshot.legacy_fallback ? (
        <div className="kpi-health-legacy-inline" role="status">
          <strong>KPI 日健康兼容提示</strong>
          <span>{snapshot.legacy_fallback.message}</span>
        </div>
      ) : null}

      <div className="kpi-health-distributions">
        <section className="kpi-health-distribution" aria-labelledby="kpi-current-distribution-title">
          <div className="kpi-health-distribution-title">
            <h4 id="kpi-current-distribution-title">当前判定</h4>
            <span data-testid="current-total">合计 {snapshot.metrics.length}</span>
          </div>
          <div className="kpi-health-count-grid">
            {visibleCurrentStatuses.map((status) => (
              <button
                type="button"
                className={`kpi-health-count kpi-health-count--${status}`}
                data-testid={`current-${status}`}
                aria-label={`筛选当前判定：${CURRENT_LABELS[status]}（${currentCounts[status]}）`}
                aria-pressed={currentFilter === status}
                key={status}
                onClick={() => {
                  setCurrentFilter(currentFilter === status ? "all" : status);
                  setTrendFilter("all");
                }}
              >
                <span>{CURRENT_LABELS[status]}</span>
                <strong>{currentCounts[status]}</strong>
              </button>
            ))}
          </div>
        </section>

        <section className="kpi-health-distribution" aria-labelledby="kpi-trend-distribution-title">
          <div className="kpi-health-distribution-title">
            <h4 id="kpi-trend-distribution-title">较昨日趋势</h4>
            <span data-testid="trend-total">合计 {snapshot.metrics.length}</span>
          </div>
          <div className="kpi-health-count-grid kpi-health-count-grid--trend">
            {visibleTrendStatuses.map((status) => (
              <button
                type="button"
                className={`kpi-health-count kpi-health-count--trend-${status}`}
                data-testid={`trend-${status}`}
                aria-label={`筛选昨日趋势：${TREND_LABELS[status]}（${trendCounts[status]}）`}
                aria-pressed={trendFilter === status}
                key={status}
                onClick={() => {
                  setTrendFilter(trendFilter === status ? "all" : status);
                  setCurrentFilter("all");
                }}
              >
                <span>{TREND_LABELS[status]}</span>
                <strong>{trendCounts[status]}</strong>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="kpi-health-scope" data-testid="daily-health-scope">
        <strong>统计范围</strong>
        <span>启用测量单元 {snapshot.scope.enabled_measurement_unit_count}</span>
        <span>已确认绑定指标 {snapshot.scope.confirmed_binding_metric_count}</span>
        <span>预期指标 {snapshot.scope.expected_metric_count}</span>
        <span>范围外文件 {snapshot.scope.out_of_scope_file_count}</span>
        <span>未确认绑定 {snapshot.scope.unconfirmed_binding_count}</span>
        {outOfScopeReasons.length > 0 ? <span>原因：{outOfScopeReasons.join("、")}</span> : null}
      </div>

      <section className="kpi-health-focus" aria-labelledby="kpi-health-focus-title" data-testid="daily-health-focus">
        <div className="kpi-health-section-heading">
          <div>
            <h4 id="kpi-health-focus-title">重点关注</h4>
            <p>优先查看失败、预警、待配置、无法判定，以及正常但较昨日恶化的指标。</p>
          </div>
        </div>
        {focus.length > 0 ? (
          <div className="kpi-health-focus-grid">
            {focus.map((metric) => (
              <article
                className={`kpi-health-focus-card kpi-health-focus-card--${metric.current_status}`}
                data-testid="focus-metric"
                key={`${metric.measurement_unit_id}:${metric.metric_resource_id}`}
              >
                <div className="kpi-health-focus-card-head">
                  <span className="kpi-health-unit-name">{metric.measurement_unit_name_zh}</span>
                  <span className="kpi-health-importance">{metric.importance}</span>
                </div>
                <div className="kpi-health-focus-card-name">
                  {metric.metric_resource_name_zh} · 当前{CURRENT_LABELS[metric.current_status]}
                </div>
                <div className="kpi-health-focus-card-value">
                  <strong>{metric.today_display ?? "—"}</strong>
                  <span>{metric.delta_display ?? "无昨日差值"}</span>
                </div>
                <div className="kpi-health-focus-card-foot">
                  <span>{metric.current_reason_text}</span>
                  <StatusPill tone={`trend-${metric.trend_status}`}>
                    {TREND_LABELS[metric.trend_status]}
                  </StatusPill>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="kpi-health-empty">当前范围内没有指标。</div>
        )}
      </section>

      <section className="kpi-health-table-section" aria-labelledby="kpi-health-table-title">
        <div className="kpi-health-section-heading">
          <div>
            <h4 id="kpi-health-table-title">全部指标结论</h4>
            <p>每个指标按独立 metric_resource_id 展示，名称相近的成功率不会被合并。</p>
          </div>
        </div>
        <div className="kpi-health-table-toolbar" aria-label="指标筛选">
          <label>
            <span>当前判定</span>
            <select
              aria-label="按当前判定筛选"
              value={currentFilter}
              onChange={(event) => setCurrentFilter(event.target.value as KpiDailyHealthCurrentStatus | "all")}
            >
              <option value="all">全部</option>
              {CURRENT_STATUSES.map((status) => (
                <option value={status} key={status}>{CURRENT_LABELS[status]}</option>
              ))}
            </select>
          </label>
          <label>
            <span>昨日趋势</span>
            <select
              aria-label="按昨日趋势筛选"
              value={trendFilter}
              onChange={(event) => setTrendFilter(event.target.value as KpiDailyHealthTrendStatus | "all")}
            >
              <option value="all">全部</option>
              {TREND_STATUSES.map((status) => (
                <option value={status} key={status}>{TREND_LABELS[status]}</option>
              ))}
            </select>
          </label>
          <span className="kpi-health-secondary" data-testid="daily-health-filter-total">
            显示 {filteredMetrics.length} / {snapshot.metrics.length}
          </span>
          {currentFilter !== "all" || trendFilter !== "all" ? (
            <button
              type="button"
              className="kpi-health-filter-reset"
              onClick={() => {
                setCurrentFilter("all");
                setTrendFilter("all");
              }}
            >
              重置筛选
            </button>
          ) : null}
        </div>
        <div className="kpi-health-table-scroll">
          <table className="kpi-health-table" aria-label="KPI 日健康指标结论">
            <thead>
              <tr>
                <th scope="col">测量单元</th>
                <th scope="col">指标</th>
                <th scope="col">指标角色</th>
                <th scope="col">当前判定</th>
                <th scope="col">今日</th>
                <th scope="col">昨日</th>
                <th scope="col">变化</th>
                <th scope="col">趋势</th>
                <th scope="col">证据</th>
              </tr>
            </thead>
            <tbody>
              {filteredMetrics.map((metric) => (
                <tr
                  data-testid="daily-health-metric-row"
                  data-current-status={metric.current_status}
                  data-trend-status={metric.trend_status}
                  key={`${metric.measurement_unit_id}:${metric.metric_resource_id}`}
                >
                  <td>
                    <div className="kpi-health-unit-cell">{metric.measurement_unit_name_zh}</div>
                    <span className="kpi-health-secondary">{metric.measurement_unit_id}</span>
                  </td>
                  <td>
                    <span className="kpi-health-metric-name">{metric.metric_resource_name_zh}</span>
                    <span className="kpi-health-secondary kpi-health-resource-id">{metric.metric_resource_id}</span>
                  </td>
                  <td>
                    <span className={`kpi-health-role kpi-health-role--${metric.role}`}>
                      {metric.role === "derived" ? "聚合指标" : "基础指标"}
                    </span>
                  </td>
                  <td>
                    <StatusPill tone={metric.current_status}>当前：{CURRENT_LABELS[metric.current_status]}</StatusPill>
                    <span className="kpi-health-reason">{metric.current_reason_text}</span>
                  </td>
                  <td className="kpi-health-number">{metric.today_display ?? (metric.current_status === "not_applicable" ? "不适用" : "—")}</td>
                  <td className="kpi-health-number">{metric.yesterday_display ?? "—"}</td>
                  <td className={`kpi-health-number kpi-health-delta--${metric.trend_status}`}>
                    {metric.delta_display ?? "—"}
                  </td>
                  <td>
                    <StatusPill tone={`trend-${metric.trend_status}`}>
                      趋势：{TREND_LABELS[metric.trend_status]}
                    </StatusPill>
                    <span className="kpi-health-reason">{metric.trend_reason}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="kpi-health-evidence-button"
                      aria-label={`查看 ${metric.metric_resource_name_zh} 证据`}
                      disabled={!taskId || !ruleCode}
                      onClick={() => setEvidenceMetric(metric)}
                    >
                      查看证据
                    </button>
                  </td>
                </tr>
              ))}
              {filteredMetrics.length === 0 ? (
                <tr>
                  <td colSpan={9} className="kpi-health-table-empty">当前筛选条件下没有指标。</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {evidenceMetric ? (
        <div
          className="kpi-health-evidence-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="kpi-health-evidence-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEvidenceMetric(null);
          }}
        >
          <div className="kpi-health-evidence-dialog">
            <header className="kpi-health-evidence-header">
              <div>
                <span className="kpi-health-secondary">{evidenceMetric.metric_resource_id}</span>
                <h3 id="kpi-health-evidence-title">{evidenceMetric.metric_resource_name_zh}</h3>
              </div>
              <button
                type="button"
                className="kpi-health-dialog-close"
                aria-label="关闭指标证据"
                onClick={() => setEvidenceMetric(null)}
              >
                关闭
              </button>
            </header>
            <Suspense fallback={<div className="kpi-health-evidence-loading">正在加载指标证据…</div>}>
              <MetricDetail
                taskId={taskId ?? ""}
                ruleCode={ruleCode ?? ""}
                measurementUnitId={evidenceMetric.measurement_unit_id}
                metricResourceId={evidenceMetric.metric_resource_id}
              />
            </Suspense>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// 保持详情类型的按需加载边界，同时避免父组件为了打开对话框而请求数据。
export type KpiMetricEvidenceDetail = KpiDailyHealthMetricDetail;
