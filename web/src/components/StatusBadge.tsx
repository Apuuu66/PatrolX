import { Badge, Tag } from "antd";

import { RESULT_STATUS_META, TASK_STATUS_LABELS } from "./statusLabels";

const RULE_COLORS: Record<string, string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
  error: "default",
  skip: "blue",
};

const RULE_LABELS = new Map<string, string>(RESULT_STATUS_META.map((meta) => [meta.key, meta.label]));

const SEVERITY_LABELS: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

const TASK_COLORS: Record<string, string> = {
  pending: "default",
  running: "processing",
  completed: "green",
  failed: "red",
};

export function RuleStatusTag({ status, skipReason }: { status: string; skipReason?: string | null }) {
  const label = RULE_LABELS.get(status) ?? status.toUpperCase();
  if (status === "skip" && skipReason) {
    return (
      <Badge
        color="blue"
        text={
          <span title={skipReason} style={{ cursor: "help" }}>
            {label}
          </span>
        }
      />
    );
  }
  return <Tag color={RULE_COLORS[status] ?? "default"}>{label}</Tag>;
}

export function TaskStatusTag({ status }: { status: string }) {
  return (
    <Tag color={TASK_COLORS[status] ?? "default"}>{TASK_STATUS_LABELS[status] ?? status}</Tag>
  );
}

export function SeverityTag({ severity }: { severity: string }) {
  const color =
    severity === "critical" ? "red" : severity === "high" ? "volcano" : severity === "medium" ? "orange" : "default";
  return <Tag color={color}>{SEVERITY_LABELS[severity] ?? severity}</Tag>;
}
