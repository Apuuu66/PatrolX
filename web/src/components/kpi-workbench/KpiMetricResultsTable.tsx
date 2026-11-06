import type {
  KpiCurrentHealthStatus,
  KpiMetricResultPageV6,
  KpiMetricResultV6,
  KpiNeedsAttentionGroup,
  KpiTrendHealthStatus,
} from "../../api/http";

const GROUP_META: Record<KpiNeedsAttentionGroup, { label: string; tone: string }> = {
  failure: { label: "失败", tone: "failure" },
  warning: { label: "预警", tone: "warning" },
  trend_degraded: { label: "昨日恶化", tone: "trend" },
  unjudgeable: { label: "无法判定", tone: "unjudgeable" },
  needs_config: { label: "待配置", tone: "needs-config" },
};

const CURRENT_STATUS_LABELS: Record<KpiCurrentHealthStatus, string> = {
  normal: "正常",
  warn: "预警",
  fail: "失败",
  pending_config: "待配置",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};

const TREND_LABELS: Record<KpiTrendHealthStatus, string> = {
  improved: "改善",
  stable: "稳定",
  worsened: "恶化",
  observe: "关注",
  no_baseline: "无基线",
};

const EMPTY_STATE_COPY: Record<
  Exclude<KpiMetricResultPageV6["empty_state"], "none">,
  { title: string; description: string }
> = {
  team_focus_empty: {
    title: "当前网元类型的团队关注为空",
    description: "从全部指标中按需加入关注后，团队可跨任务共享同一份关注列表。",
  },
  no_task_metrics: {
    title: "当前任务没有 KPI 指标",
    description: "请检查测量单元启停与指标配置，完成重建后再刷新当前结果。",
  },
  no_matching_metrics: {
    title: "没有符合当前条件的指标",
    description: "清除筛选后重新查看当前视图。",
  },
};

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(value);
}

function formatChange(item: KpiMetricResultV6): string {
  if (item.change_value === null || item.change_value === undefined) return "—";
  if (item.change_unit === "relative") {
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2, signDisplay: "always" }).format(item.change_value)}%`;
  }
  if (item.change_unit === "pp") {
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2, signDisplay: "always" }).format(item.change_value)}pp`;
  }
  if (item.change_unit === "absolute") {
    return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2, signDisplay: "always" }).format(item.change_value);
  }
  return "—";
}

export function kpiMetricKey(metric: KpiMetricResultV6): string {
  return `${metric.measurement_unit_id}\u0000${metric.metric_resource_id}`;
}

export interface KpiMetricResultsTableProps {
  page: KpiMetricResultPageV6;
  onOpenEvidence?: (metric: KpiMetricResultV6) => void;
  onRefresh?: () => void;
  selectedMetricKey?: string | null;
}

export function KpiMetricResultsTable({
  page,
  onOpenEvidence,
  onRefresh,
  selectedMetricKey,
}: KpiMetricResultsTableProps) {
  if (page.empty_state !== "none") {
    const empty = EMPTY_STATE_COPY[page.empty_state];
    return (
      <div className="kpi-results-empty" role="status">
        <h2>{empty.title}</h2>
        <p>{empty.description}</p>
        {onRefresh ? (
          <button type="button" className="kpi-workbench-button" onClick={onRefresh}>
            刷新当前结果
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="kpi-results-table-wrap">
      <table className="kpi-results-table">
        <caption>KPI 巡检结果，按服务端判定顺序展示</caption>
        <thead>
          <tr>
            <th scope="col">状态</th>
            <th scope="col">指标</th>
            <th scope="col">重要度</th>
            <th scope="col">今日值</th>
            <th scope="col">昨日趋势</th>
            <th scope="col">判定原因</th>
            <th scope="col">证据</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((item, index) => {
            const group = item.needs_attention_group ? GROUP_META[item.needs_attention_group] : null;
            const currentStatus = item.current_status ? CURRENT_STATUS_LABELS[item.current_status] : "无法判定";
            const selected = selectedMetricKey === kpiMetricKey(item);
            return (
              <tr
                key={kpiMetricKey(item)}
                className={selected ? "is-selected" : undefined}
                data-testid="kpi-metric-row"
                data-metric-id={item.metric_resource_id}
              >
                <td>
                  <span
                    className={`kpi-result-status is-${group?.tone ?? "unjudgeable"}`}
                    data-status={item.needs_attention_group ?? item.current_status ?? "unjudgeable"}
                  >
                    <span className="kpi-result-status-dot" aria-hidden="true" />
                    {group?.label ?? currentStatus}
                  </span>
                  {group && group.label !== currentStatus ? (
                    <span className="kpi-result-current-status">今日 {currentStatus}</span>
                  ) : null}
                </td>
                <td>
                  <div className="kpi-result-metric">
                    <strong title={item.metric_name}>{item.metric_name}</strong>
                    <span title={`${item.measurement_unit_name} · ${item.metric_resource_id}`}>
                      {item.measurement_unit_name} · <code>{item.metric_resource_id}</code>
                    </span>
                    <span className={`kpi-result-role is-${item.role}`}>
                      {item.role === "base" ? (
                        <>源包直出 · <code>base</code></>
                      ) : (
                        <>PatrolX 计算 · <code>derived</code></>
                      )}
                    </span>
                  </div>
                </td>
                <td>
                  <span className={`kpi-importance is-${item.importance.toLowerCase()}`}>{item.importance}</span>
                </td>
                <td className="kpi-result-number" data-testid={`kpi-metric-today-value-${index}`}>
                  {item.today_value === null || item.today_value === undefined ? (
                    <span className="kpi-result-missing">源值缺失</span>
                  ) : (
                    formatNumber(item.today_value)
                  )}
                </td>
                <td>
                  <div className={`kpi-result-trend is-${item.yesterday_trend ?? "no_baseline"}`}>
                    <span>{item.yesterday_trend ? TREND_LABELS[item.yesterday_trend] : "无基线"}</span>
                    <strong>{formatChange(item)}</strong>
                  </div>
                </td>
                <td>
                  <span className="kpi-result-reason" title={item.reason}>{item.reason || "暂未提供判定原因"}</span>
                </td>
                <td>
                  {item.evidence_available && onOpenEvidence ? (
                    <button
                      type="button"
                      className="kpi-evidence-link"
                      aria-label={`查看${item.metric_name}证据`}
                      onClick={() => onOpenEvidence(item)}
                    >
                      查看
                    </button>
                  ) : (
                    <span className="kpi-result-no-evidence">暂无证据</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="kpi-results-footer">
        <span>当前显示 {page.items.length} 项 · 共 {page.total} 项 · 当前视图总计 {page.view_total} 项</span>
        <span>第 {page.page} 页</span>
      </div>
    </div>
  );
}
