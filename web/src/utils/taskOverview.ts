import type { OverviewSummary, TaskStats } from "../api/http";

export type OverviewMetricKey =
  | "task_count"
  | "registered_rule_count"
  | "rule_result_count"
  | "finding_count";

export interface OverviewMetricDefinition {
  key: OverviewMetricKey;
  label: string;
  /** 口径说明：概览卡 Tooltip 文案（FR-004、R3）。 */
  description: string;
  /** 统计范围，本轮固定为全部任务。 */
  scope: string;
}

const SCOPE = "统计范围：全部任务";

export const OVERVIEW_METRICS: readonly OverviewMetricDefinition[] = [
  {
    key: "task_count",
    label: "巡检任务",
    description: "已上传并创建的全部巡检任务数量，包含排队中、执行中与已完成任务。",
    scope: SCOPE,
  },
  {
    key: "registered_rule_count",
    label: "注册规则",
    description: "当前已注册的巡检规则数量，与任务是否执行无关。",
    scope: SCOPE,
  },
  {
    key: "rule_result_count",
    label: "规则结果",
    description:
      "全部任务中已执行规则的结论条数，等于通过、告警、失败、异常、跳过五态之和；一条规则只产生一条规则结果。",
    scope: SCOPE,
  },
  {
    key: "finding_count",
    label: "发现问题数",
    description:
      "全部规则输出中的问题条目总数，按发现条目计数；一条规则可产生多条发现，因此该数值通常大于规则结果数。",
    scope: SCOPE,
  },
];

export function getOverviewMetricValue(
  overview: OverviewSummary | null,
  key: OverviewMetricKey,
): number | null {
  if (!overview) return null;
  const value = overview[key];
  return typeof value === "number" ? value : null;
}

/** 概览条使用的五态计数；概览未加载时返回 null，避免渲染 0 值假分布（FR-005）。 */
export function getOverviewDistribution(
  overview: OverviewSummary | null,
): Pick<TaskStats, "pass" | "warn" | "fail" | "error" | "skip"> | null {
  if (!overview) return null;
  const { pass, warn, fail, error, skip } = overview.status_counts;
  return { pass, warn, fail, error, skip };
}
