import type { RuleStatus, TaskStats } from "../api/http";
import { getHealthBarSegments } from "../utils/taskDisplay";

export type StatusDistributionVariant = "compact" | "full";

export interface StatusDistributionProps {
  stats: Pick<TaskStats, "pass" | "warn" | "fail" | "error" | "skip">;
  variant?: StatusDistributionVariant;
  emptyText?: string;
  className?: string;
  /** 当前激活的状态筛选；仅在提供 onStatusClick 时生效 */
  activeStatus?: RuleStatus | null;
  /** 提供后可点选非零状态计数，用于状态筛选联动 */
  onStatusClick?: (status: RuleStatus) => void;
}

/**
 * 状态分布：分段条 + 非零计数。
 *
 * - 0 值状态不渲染计数、不渲染分段（FR-003、FR-009）。
 * - 五态总和为 0 时渲染文本空态，不得渲染空条。
 * - 五态文字标签与非零状态一同呈现，不依赖颜色表达状态（FR-002）。
 * - 提供 onStatusClick 时，非零计数同时是状态筛选入口（任务详情）。
 */
export function StatusDistribution({
  stats,
  variant = "compact",
  emptyText = "暂无规则结果",
  className,
  activeStatus = null,
  onStatusClick,
}: StatusDistributionProps) {
  const segments = getHealthBarSegments(stats);
  const interactive = typeof onStatusClick === "function";

  if (segments.length === 0) {
    return <span className="status-distribution-empty">{emptyText}</span>;
  }

  return (
    <div className={`status-distribution status-distribution-${variant}${className ? ` ${className}` : ""}`}>
      <div className="status-distribution-bar" role="img" aria-label="规则状态分布">
        {segments.map((segment) => (
          <span
            key={segment.key}
            data-status-segment={segment.key}
            className="status-distribution-segment"
            style={{ width: `${segment.percent}%`, background: segment.color }}
            title={`${segment.label} ${segment.value}`}
          />
        ))}
      </div>
      <div className="status-distribution-counts">
        {segments.map((segment) =>
          interactive ? (
            <button
              key={segment.key}
              type="button"
              className={`status-distribution-count status-distribution-count-interactive${
                activeStatus === segment.key ? " is-active" : ""
              }`}
              data-status-count={segment.key}
              aria-label={`筛选${segment.label}`}
              aria-pressed={activeStatus === segment.key}
              onClick={() => onStatusClick(segment.key)}
            >
              <span aria-hidden className="status-distribution-dot" style={{ background: segment.color }} />
              {segment.label} {segment.value}
            </button>
          ) : (
            <span key={segment.key} className="status-distribution-count" data-status-count={segment.key}>
              <span aria-hidden className="status-distribution-dot" style={{ background: segment.color }} />
              {segment.label} {segment.value}
            </span>
          ),
        )}
      </div>
    </div>
  );
}
