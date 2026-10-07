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
  product: "网元类型",
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

export interface DeviceIdDisplay {
  /** 页面展示文本，缺失时为 "-"。 */
  value: string;
  /** 取值来源：手工设备 ID、台账解析的网元名称，或缺失。 */
  source: "manual" | "ledger" | null;
}

export interface DeviceIdSource {
  device_id?: string | null;
  inventory?: {
    devices?: readonly { normalized_name?: string | null }[] | null;
  } | null;
}

/**
 * 设备 ID 展示规则：优先展示手工填写的设备 ID；未填写时回退到台账解析出的网元名称。
 * 手工设备 ID 用于跨任务历史匹配，台账解析结果只作为展示证据。
 */
export function getDeviceIdDisplay(
  task: DeviceIdSource,
  customer?: Record<string, string> | null,
): DeviceIdDisplay {
  const manual = (task.device_id ?? customer?.device_id ?? "").trim();
  if (manual) {
    return { value: manual, source: "manual" };
  }

  const names = (task.inventory?.devices ?? [])
    .map((device) => device.normalized_name?.trim() ?? "")
    .filter((name) => name.length > 0);
  const uniqueNames = [...new Set(names)];
  if (uniqueNames.length > 0) {
    return { value: uniqueNames.join("、"), source: "ledger" };
  }

  return { value: "-", source: null };
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
