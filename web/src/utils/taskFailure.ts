import type { LogEntry, TaskSummary } from "../api/http";

export function latestTaskFailure(entries: LogEntry[]): string | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry.level !== "error") continue;

    const detailError = entry.detail?.error;
    const reason = typeof detailError === "string" ? detailError.trim() : "";
    if (!reason || entry.message.includes(reason)) return entry.message;
    return `${entry.message}：${reason}`;
  }
  return null;
}

/**
 * 失败阶段：只消费结构化字段，不解析后端文案。
 * 数据准备失败归入数据准备阶段，其余失败归入任务执行阶段。
 */
export function getTaskFailureStage(
  task: Pick<TaskSummary, "status" | "preparation">,
): string | null {
  if (task.status !== "failed") return null;
  if (task.preparation?.status === "fail") return "数据准备";
  return "任务执行";
}
