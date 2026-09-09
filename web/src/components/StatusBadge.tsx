import { Badge, Tag } from "antd";

const RULE_COLORS: Record<string, string> = {
  pass: "green",
  warn: "gold",
  fail: "red",
  error: "default",
  skip: "blue",
};

const TASK_COLORS: Record<string, string> = {
  pending: "default",
  running: "processing",
  completed: "green",
  failed: "red",
};

export function RuleStatusTag({ status, skipReason }: { status: string; skipReason?: string | null }) {
  const label = status.toUpperCase();
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
  return <Tag color={TASK_COLORS[status] ?? "default"}>{status}</Tag>;
}

export function SeverityTag({ severity }: { severity: string }) {
  const color =
    severity === "critical" ? "red" : severity === "high" ? "volcano" : severity === "medium" ? "orange" : "default";
  return <Tag color={color}>{severity}</Tag>;
}
