import type { DictsResponse, TaskSummary } from "../api/http";
import { formatDurationMs } from "./timeDisplay.ts";

export interface TaskMetadataTag {
  key: "province" | "operator" | "product" | "version" | "device_id";
  label: string;
  value: string;
}

type DictGroup = NonNullable<DictsResponse["province"]> extends unknown ? "province" | "operator" | "product" | "version" : never;

function dictName(
  dicts: DictsResponse | null,
  group: DictGroup,
  code: string,
): string {
  const item = dicts?.[group]?.find((dict) => dict.code === code);
  return item?.name || code;
}

export function formatTaskDuration(created_at: string, completed_at?: string | null): string | null {
  const start = new Date(created_at).getTime();
  const end = completed_at ? new Date(completed_at).getTime() : Number.NaN;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return formatDurationMs(end - start);
}

/**
 * 任务时长展示文案（FR-008、FR-009、SC-004）：
 * 已运行任务展示最近一次运行的耗时；运行中只表明尚未结束，不回退展示上一次耗时；
 * 从未运行或尚未完成的任务返回占位符，避免误导性数值。
 */
export function getTaskDurationDisplay(task: Pick<TaskSummary, "status" | "duration_ms">): string {
  if (task.status === "running") return "运行中";
  return formatDurationMs(task.duration_ms) ?? "-";
}

export function getTaskMetadataTags(
  task: Pick<TaskSummary, "customer_province" | "customer_operator" | "customer_product" | "customer_version" | "device_id">,
  dicts: DictsResponse | null,
): TaskMetadataTag[] {
  const tags: TaskMetadataTag[] = [];

  if (task.customer_province) {
    tags.push({
      key: "province",
      label: "省份",
      value: dictName(dicts, "province", task.customer_province),
    });
  }
  if (task.customer_operator) {
    tags.push({
      key: "operator",
      label: "运营商",
      value: dictName(dicts, "operator", task.customer_operator),
    });
  }
  if (task.customer_product) {
    tags.push({
      key: "product",
      label: "网元类型",
      value: dictName(dicts, "product", task.customer_product),
    });
  }
  if (task.customer_version) {
    tags.push({
      key: "version",
      label: "版本",
      value: dictName(dicts, "version", task.customer_version),
    });
  }
  if (task.device_id?.trim()) {
    tags.push({ key: "device_id", label: "设备 ID", value: task.device_id.trim() });
  }

  return tags;
}
