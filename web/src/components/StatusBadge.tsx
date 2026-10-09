import { Badge, Tag } from "antd";

import { RESULT_STATUS_META, TASK_STATUS_LABELS } from "./statusLabels";
import { getStatusTextColor } from "../utils/statusTextColors";

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
  // 填充色保留标准状态色，文字改用文本安全色保证 AA（FR-019、SC-006、R13）。
  const textColor = getStatusTextColor(status, "inherit");
  if (status === "skip" && skipReason) {
    return (
      <Badge
        color="blue"
        text={
          <span title={skipReason} style={{ cursor: "help", color: textColor }}>
            {label}
          </span>
        }
      />
    );
  }
  return (
    <Tag
      color={RULE_COLORS[status] ?? "default"}
      className={status === "error" ? "rule-status-tag rule-status-tag-error" : "rule-status-tag"}
      style={{ color: textColor }}
    >
      {label}
    </Tag>
  );
}

export function TaskStatusTag({ status }: { status: string }) {
  return (
    <Tag color={TASK_COLORS[status] ?? "default"}>{TASK_STATUS_LABELS[status] ?? status}</Tag>
  );
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "red",
  high: "volcano",
  medium: "orange",
};

/** 轻量严重度色点颜色，与 Tag 变体同源，避免两套语义色（FR-013、R10）。 */
const SEVERITY_DOT_COLORS: Record<string, string> = {
  critical: "#cf1322",
  high: "#d4380d",
  medium: "#d46b08",
  low: "#8c8c8c",
};

export interface SeverityTagProps {
  severity: string;
  /**
   * `tag`：彩色标签（默认，用于需要强识别的场景）；
   * `plain`：色点 + 文字，含 `title` 与 `aria-label`，用于发现条目 / 密集表格（FR-013、R10）。
   */
  variant?: "tag" | "plain";
}

export function SeverityTag({ severity, variant = "tag" }: SeverityTagProps) {
  const label = SEVERITY_LABELS[severity] ?? severity;
  if (variant === "plain") {
    return (
      <span
        className="severity-plain"
        data-severity={severity}
        title={`严重程度：${label}`}
        aria-label={`严重程度：${label}`}
      >
        <span
          className="severity-plain-dot"
          aria-hidden="true"
          style={{ background: SEVERITY_DOT_COLORS[severity] ?? "#8c8c8c" }}
        />
        {label}
      </span>
    );
  }
  return <Tag color={SEVERITY_COLORS[severity] ?? "default"}>{label}</Tag>;
}
