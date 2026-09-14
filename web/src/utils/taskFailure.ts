import type { LogEntry } from "../api/http";

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
