import type { KpiNeedsAttentionGroup, KpiTaskSummaryV6 } from "../../api/http";

const GROUP_META: Record<KpiNeedsAttentionGroup, { label: string; tone: string }> = {
  failure: { label: "失败", tone: "failure" },
  warning: { label: "预警", tone: "warning" },
  trend_degraded: { label: "昨日恶化", tone: "trend" },
  unjudgeable: { label: "无法判定", tone: "unjudgeable" },
  needs_config: { label: "待配置", tone: "needs-config" },
};

function formatLatestMeasuredAt(value: string | null): string {
  if (!value) return "暂无测量时间";
  const measuredAt = new Date(value);
  if (Number.isNaN(measuredAt.getTime())) return "暂无测量时间";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(measuredAt);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

export interface KpiSummaryHeaderProps {
  summary: KpiTaskSummaryV6;
  selectedGroup?: KpiNeedsAttentionGroup | null;
  onGroupSelect?: (group: KpiNeedsAttentionGroup) => void;
}

export function KpiSummaryHeader({ summary, selectedGroup, onGroupSelect }: KpiSummaryHeaderProps) {
  const { counts } = summary;
  const networkLabel = summary.network_element_type
    ? `${summary.network_element_type} 团队关注 · 按网元类型共享`
    : "未选择规则适用网元类型 · 团队关注不可用";

  return (
    <section className="kpi-summary-card" aria-labelledby="kpi-summary-title">
      <div className="kpi-summary-conclusion">
        <span className="kpi-summary-kicker" id="kpi-summary-title">{networkLabel}</span>
        <div className="kpi-summary-headline">
          <strong data-testid="kpi-summary-needs-attention">{counts.needs_attention_count}</strong>
          <span>项需要处理</span>
        </div>
        <p>
          关注 {counts.team_focus_count} · 无需处理 {counts.no_action_count}
          {counts.unavailable_focus_count > 0 ? ` · 不可用 ${counts.unavailable_focus_count}` : ""}
        </p>
      </div>

      <dl className="kpi-summary-counts">
        <div data-testid="kpi-summary-all">
          <dt>全部指标</dt>
          <dd>{counts.all_metric_count}</dd>
          <span>任务冻结范围</span>
        </div>
        <div data-testid="kpi-summary-focus">
          <dt>团队关注</dt>
          <dd>{counts.team_focus_count}</dd>
          <span>当前可用</span>
        </div>
        <div className="is-attention" data-testid="kpi-summary-needs-attention-count">
          <dt>需处理</dt>
          <dd>{counts.needs_attention_count}</dd>
          <span>需逐项核验</span>
        </div>
        <div className="is-clear" data-testid="kpi-summary-no-action">
          <dt>无需处理</dt>
          <dd>{counts.no_action_count}</dd>
          <span>关注范围内</span>
        </div>
      </dl>

      <div className="kpi-summary-context">
        <span>数据日期 <strong>{summary.data_date ?? "无数据"}</strong></span>
        <span aria-hidden="true">·</span>
        <span>对比日期 <strong>{summary.previous_date ?? "无基线"}</strong></span>
        <span aria-hidden="true">·</span>
        <span>最新测量 <strong>{formatLatestMeasuredAt(summary.latest_measured_at)}</strong></span>
        <span className="kpi-summary-enabled" data-testid="kpi-summary-enabled-units">
          启用测量单元 {counts.enabled_measurement_unit_count}
        </span>
      </div>

      <div className="kpi-summary-groups" data-testid="kpi-summary-groups" aria-label="需处理分组">
        <span className="kpi-summary-groups-label">互斥分组</span>
        {summary.needs_attention_groups.map((group) => {
          const meta = GROUP_META[group.group];
          const selected = selectedGroup === group.group;
          const content = (
            <>
              <span className="kpi-summary-group-dot" aria-hidden="true" />
              <span>{meta.label}</span>
              <strong>{group.count}</strong>
            </>
          );
          return onGroupSelect ? (
            <button
              key={group.group}
              type="button"
              className={`kpi-summary-group is-${meta.tone}${selected ? " is-selected" : ""}`}
              data-testid={`kpi-group-${group.group}`}
              aria-pressed={selected}
              onClick={() => onGroupSelect(group.group)}
            >
              {content}
            </button>
          ) : (
            <span
              key={group.group}
              className={`kpi-summary-group is-${meta.tone}`}
              data-testid={`kpi-group-${group.group}`}
            >
              {content}
            </span>
          );
        })}
      </div>
    </section>
  );
}
