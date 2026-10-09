import type { TaskSummary } from "../api/http";

export type TaskConclusionTone = "danger" | "warning" | "success" | "processing" | "neutral";

export type TaskConclusionNextAction = "logs" | "rules" | "report" | null;

export interface TaskConclusion {
  tone: TaskConclusionTone;
  label: string;
  sentence: string;
  detail: string | null;
  nextAction: TaskConclusionNextAction;
}

const FALLBACK_FAILURE_REASON = "任务执行失败，请在执行日志中查看失败阶段与原因。";
const DEFAULT_FAILURE_STAGE = "任务执行";

/**
 * 由既有 TaskSummary 字段推导任务结论。
 *
 * 推导优先级严格按 data-model §2：
 * failed → pending → running → fail/error → warn → 其余（含仅 skip）视为通过。
 */
export function deriveTaskConclusion(
  task: Pick<TaskSummary, "status" | "stats">,
  failureReason?: string | null,
  failureStage?: string | null,
): TaskConclusion {
  const stats = task.stats;
  const reason = failureReason?.trim();
  const stage = failureStage?.trim() || DEFAULT_FAILURE_STAGE;

  if (task.status === "failed") {
    return {
      tone: "danger",
      label: "任务失败",
      sentence: reason || FALLBACK_FAILURE_REASON,
      detail: `失败阶段：${stage}`,
      nextAction: "logs",
    };
  }

  if (task.status === "pending") {
    return {
      tone: "neutral",
      label: "排队中",
      sentence: "任务已创建，正在等待执行。",
      detail: null,
      nextAction: null,
    };
  }

  if (task.status === "running") {
    return {
      tone: "processing",
      label: "执行中",
      sentence: "任务正在执行，结果会随轮询实时更新。",
      detail: null,
      nextAction: null,
    };
  }

  // 结论句只拼接非零状态，不出现"异常 0 条"这类噪音（FR-009、contracts §4）。
  const attentionParts: string[] = [];
  if (stats.fail > 0) attentionParts.push(`失败 ${stats.fail} 条`);
  if (stats.error > 0) attentionParts.push(`异常 ${stats.error} 条`);
  if (attentionParts.length > 0) {
    return {
      tone: "danger",
      label: "需要关注",
      sentence: `发现${attentionParts.join("、")}规则结果，需要处理。`,
      detail: null,
      nextAction: "rules",
    };
  }

  if (stats.warn > 0) {
    return {
      tone: "warning",
      label: "需要关注",
      sentence: `发现告警 ${stats.warn} 条规则结果，建议确认后处理。`,
      detail: null,
      nextAction: "rules",
    };
  }

  const total = stats.total;
  return {
    tone: "success",
    label: "全部通过",
    sentence: total > 0 ? `共执行 ${total} 条规则，未发现失败、告警或异常。` : "任务已完成，暂无规则结果。",
    detail: stats.skip > 0 ? `另有 ${stats.skip} 条规则因不适用被跳过。` : null,
    nextAction: "report",
  };
}
