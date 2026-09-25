import type { RuleStatus, TaskStats } from "../api/http";

export type StatusStatEmphasis = "attention" | "normal" | "quiet";

type AttentionStatus = Extract<RuleStatus, "fail" | "warn" | "error">;

const ATTENTION_STATUSES: readonly AttentionStatus[] = ["fail", "warn", "error"];

export function getStatusStatEmphasis(status: RuleStatus, value: number): StatusStatEmphasis {
  if (value === 0) return "quiet";
  if ((ATTENTION_STATUSES as readonly RuleStatus[]).includes(status)) return "attention";
  return "normal";
}

const ATTENTION_LABELS = {
  fail: "失败",
  warn: "告警",
  error: "异常",
} as const;

export function getAttentionSummary(
  stats: Pick<TaskStats, "fail" | "warn" | "error">,
): string {
  if (ATTENTION_STATUSES.every((status) => stats[status] === 0)) {
    return "未发现失败、告警或异常规则";
  }
  return ATTENTION_STATUSES.map((status) => `${ATTENTION_LABELS[status]} ${stats[status]}`).join(" · ");
}

export interface DisplayField {
  key: string;
  label: string;
  value: string;
}

const CUSTOMER_LABELS: Record<string, string> = {
  province: "省份",
  operator: "运营商",
  product: "产品形态",
  version: "版本",
};

export function getCustomerFields(
  customer?: Record<string, string> | null,
): DisplayField[] {
  if (!customer) return [];

  return Object.entries(customer)
    .filter(([key, value]) => key !== "device_id" && value.trim())
    .map(([key, value]) => ({
      key,
      label: CUSTOMER_LABELS[key] ?? key,
      value,
    }));
}

export interface HealthBarSegment {
  key: RuleStatus;
  label: string;
  color: string;
  value: number;
  percent: number;
}

export function getHealthBarSegments(
  stats: Pick<TaskStats, "pass" | "warn" | "fail" | "error" | "skip">,
): HealthBarSegment[] {
  const total = stats.pass + stats.warn + stats.fail + stats.error + stats.skip;
  if (total === 0) return [];

  return ([
    { key: "pass", label: "通过", color: "#52c41a", value: stats.pass },
    { key: "warn", label: "告警", color: "#faad14", value: stats.warn },
    { key: "fail", label: "失败", color: "#ff4d4f", value: stats.fail },
    { key: "error", label: "异常", color: "#8c8c8c", value: stats.error },
    { key: "skip", label: "跳过", color: "#1677ff", value: stats.skip },
  ] as HealthBarSegment[])
    .filter((segment) => segment.value > 0)
    .map((segment) => ({ ...segment, percent: (segment.value / total) * 100 }));
}
