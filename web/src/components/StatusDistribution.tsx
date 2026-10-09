import { Tooltip } from "antd";
import { getStatusTextColor } from "../utils/statusTextColors";
import type { RuleStatus, TaskStats } from "../api/http";
import {
  getHealthBarSegments,
  type HealthBarEmphasisMode,
  type HealthBarSegment,
} from "../utils/taskDisplay";

export type StatusDistributionVariant = "compact" | "full";

export interface StatusDistributionProps {
  stats: Pick<TaskStats, "pass" | "warn" | "fail" | "error" | "skip">;
  variant?: StatusDistributionVariant;
  /** 概览卡传 overview 弱化 pass/skip；任务行与详情保持标准状态色（FR-002、R1）。 */
  emphasis?: HealthBarEmphasisMode;
  emptyText?: string;
  className?: string;
  /** 当前激活的状态筛选；仅在提供 onStatusClick 时生效 */
  activeStatus?: RuleStatus | null;
  /** 提供后可点选非零状态计数，用于状态筛选联动 */
  onStatusClick?: (status: RuleStatus) => void;
}

/** Tooltip 文案：状态 + 计数 + 整数百分比（FR-002、R2）。 */
function segmentTooltip(segment: HealthBarSegment): string {
  return `${segment.label} ${segment.value}（${Math.round(segment.percent)}%）`;
}

/**
 * 状态分布：分段条 + 非零计数。
 *
 * - 排序统一为 fail → warn → error → skip → pass（FR-001、R1）。
 * - 0 值状态不渲染计数、不渲染分段（FR-003）。
 * - 五态总和为 0 时渲染文本空态，不得渲染空条。
 * - 每段与计数提供 Tooltip 说明状态、计数与占比（FR-002）。
 * - 提供 onStatusClick 时，非零计数同时是状态筛选入口（任务详情）。
 */
export function StatusDistribution({
  stats,
  variant = "compact",
  emphasis = "standard",
  emptyText = "暂无规则结果",
  className,
  activeStatus = null,
  onStatusClick,
}: StatusDistributionProps) {
  const segments = getHealthBarSegments(stats, { emphasis });
  const interactive = typeof onStatusClick === "function";

  if (segments.length === 0) {
    return <span className="status-distribution-empty">{emptyText}</span>;
  }

  return (
    <div
      className={`status-distribution status-distribution-${variant}${
        emphasis === "overview" ? " status-distribution-overview" : ""
      }${className ? ` ${className}` : ""}`}
    >
      <div className="status-distribution-bar" role="img" aria-label="规则状态分布">
        {segments.map((segment) => (
          <Tooltip key={segment.key} title={segmentTooltip(segment)}>
            <span
              data-status-segment={segment.key}
              className={`status-distribution-segment status-distribution-segment-${segment.emphasis}`}
              style={{ width: `${segment.percent}%`, background: segment.color }}
              aria-label={segmentTooltip(segment)}
            />
          </Tooltip>
        ))}
      </div>
      <div className="status-distribution-counts">
        {segments.map((segment) => {
          const countText = `${segment.label} ${segment.value}`;
          const dot = (
            <span
              aria-hidden
              className="status-distribution-dot"
              data-status-dot={segment.key}
              style={{ background: segment.color }}
            />
          );
          // 关注状态（失败 / 告警 / 异常）的计数文字使用文本安全色；
          // 通过 / 跳过保持中性次要色，维持概览降噪（FR-002、FR-019、R13）。
          const countColor =
            segment.emphasis === "attention" ? getStatusTextColor(segment.key, "inherit") : undefined;
          const countStyle = countColor ? { color: countColor } : undefined;

          if (!interactive) {
            return (
              <Tooltip key={segment.key} title={segmentTooltip(segment)}>
                <span
                  className="status-distribution-count"
                  data-status-count={segment.key}
                  style={countStyle}
                >
                  {dot}
                  {countText}
                </span>
              </Tooltip>
            );
          }

          return (
            <Tooltip key={segment.key} title={segmentTooltip(segment)}>
              <button
                type="button"
                className={`status-distribution-count status-distribution-count-interactive${
                  activeStatus === segment.key ? " is-active" : ""
                }`}
                data-status-count={segment.key}
                style={countStyle}
                aria-label={`筛选${segment.label}`}
                aria-pressed={activeStatus === segment.key}
                onClick={() => onStatusClick?.(segment.key)}
              >
                {dot}
                {countText}
              </button>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}
