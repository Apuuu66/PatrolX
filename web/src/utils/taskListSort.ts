import type { TaskSummary } from "../api/http";

/** 列表默认优先级：failed → 异常 completed → running → pending → 正常 completed。 */
const STATUS_PRIORITY: Record<TaskSummary["status"], number> = {
  failed: 0,
  running: 2,
  pending: 3,
  completed: 4,
};

const ABNORMAL_COMPLETED_PRIORITY = 1;
const FALLBACK_FAILURE_REASON = "任务执行失败，请查看执行日志";

/**
 * 任务列表默认排序：
 * 1. failed → 异常 completed → running → pending → completed；completed 且 fail + error > 0 视为异常提前。
 * 2. 同优先级按 created_at 倒序。
 * 不修改入参数组；本轮不提供排序切换控件（FR-007、Clarifications）。
 */
export function sortTasksForList(tasks: readonly TaskSummary[]): TaskSummary[] {
  return [...tasks].sort((left, right) => {
    const priorityDelta = getPriority(left) - getPriority(right);
    if (priorityDelta !== 0) return priorityDelta;
    return toTimestamp(right.created_at) - toTimestamp(left.created_at);
  });
}

function getPriority(task: TaskSummary): number {
  if (task.status === "completed" && task.stats.fail + task.stats.error > 0) {
    return ABNORMAL_COMPLETED_PRIORITY;
  }
  return STATUS_PRIORITY[task.status];
}

function toTimestamp(value: string): number {
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
}

/**
 * 任务行内失败原因摘要：只用于任务状态为 failed 的行（FR-008）。
 * 优先使用数据准备阶段记录的问题原因，缺失时给出可执行兜底文案。
 */
export function getTaskFailureReason(task: TaskSummary): string | null {
  if (task.status !== "failed") return null;

  const failedItem = (task.preparation?.items ?? []).find(
    (item) => item.status === "fail" && (item.issues ?? []).some((issue) => issue.reason?.trim()),
  );
  const reason = failedItem?.issues?.find((issue) => issue.reason?.trim())?.reason.trim();
  return reason && reason.length > 0 ? reason : FALLBACK_FAILURE_REASON;
}
