import type { DictsResponse, TaskSummary } from "../api/http";

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

  const totalSeconds = Math.floor((end - start) / 1000);
  if (totalSeconds < 1) return "<1 秒";
  if (totalSeconds < 60) return `${totalSeconds} 秒`;

  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) return `${days} 天 ${hours} 小时`;
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`;
  return `${minutes} 分 ${seconds} 秒`;
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
      label: "产品形态",
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
