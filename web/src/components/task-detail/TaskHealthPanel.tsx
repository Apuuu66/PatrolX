import { Alert, Typography } from "antd";
import type { RuleStatus, TaskStats } from "../../api/http";
import { SummaryCards } from "../SummaryCards";
import { getAttentionSummary, getHealthBarSegments } from "../../utils/taskDisplay";
import type { StatusFilter } from "../../utils/taskFilter";

type TaskHealthPanelProps = {
  stats: TaskStats;
  statusCounts: Record<RuleStatus, number>;
  activeStatus: StatusFilter;
  attentionTotal: number;
  attentionHiddenCount: number;
  onStatusClick: (status: RuleStatus) => void;
};

export function TaskHealthPanel({
  stats,
  statusCounts,
  activeStatus,
  attentionTotal,
  attentionHiddenCount,
  onStatusClick,
}: TaskHealthPanelProps) {
  const segments = getHealthBarSegments(stats);

  return (
    <>
      <SummaryCards stats={stats} statusCounts={statusCounts} activeStatus={activeStatus} onStatusClick={onStatusClick} />
      <div aria-label="规则健康度分布">
        <div className="task-health-bar">
          {segments.map((segment) => (
            <button
              key={segment.key}
              type="button"
              className="health-bar-segment"
              aria-label={`筛选${segment.label}`}
              aria-pressed={activeStatus === segment.key}
              title={`${segment.label} ${segment.value}`}
              onClick={() => onStatusClick(segment.key)}
              style={{
                width: `${segment.percent}%`,
                backgroundColor: segment.color,
                minWidth: segment.percent > 0 ? 4 : 0,
                outline: activeStatus === segment.key ? "2px solid rgba(0, 0, 0, 0.65)" : "none",
                outlineOffset: 1,
              }}
            />
          ))}
        </div>
      </div>
      <Alert
        type={attentionTotal ? "warning" : "success"}
        showIcon
        message={
          attentionTotal
            ? `重点关注 ${attentionTotal} 条规则`
            : "巡检完成，未发现需要重点处理的规则"
        }
        description={
          attentionTotal
            ? `${getAttentionSummary(stats)} · 以下规则建议优先查看结论和证据。${
                attentionHiddenCount ? `其余 ${attentionHiddenCount} 条在全部规则中查看。` : ""
              }`
            : undefined
        }
      />
      <Typography.Title level={5} className="task-detail-section-title">
        基础信息
      </Typography.Title>
    </>
  );
}
