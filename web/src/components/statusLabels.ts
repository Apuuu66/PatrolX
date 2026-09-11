export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
};

export const RESULT_STATUS_META = [
  { key: "pass", label: "通过", color: "#52c41a" },
  { key: "warn", label: "告警", color: "#faad14" },
  { key: "fail", label: "失败", color: "#ff4d4f" },
  { key: "error", label: "异常", color: "#8c8c8c" },
  { key: "skip", label: "跳过", color: "#1677ff" },
] as const;
