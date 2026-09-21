import type { components } from "../api/client";

import { formatKpiNumber } from "./kpiFormat.ts";

export type KpiRecordItem = components["schemas"]["KpiRecordItemV2"];
export type KpiRecordPage = components["schemas"]["KpiRecordPageV2"];
export type KpiRecordStatus = components["schemas"]["KpiDisplayStatusV2"];

export type KpiRecordFilters = {
  sourceFile?: string;
  periodMinutes?: 5 | 15 | 30 | 60;
  status?: KpiRecordStatus;
};

export type KpiRecordQuery = {
  metric_key: string;
  source_file?: string;
  period_minutes?: 5 | 15 | 30 | 60;
  status?: KpiRecordStatus;
  page: number;
  page_size: number;
};

export type KpiRecordRow = {
  id: string;
  metricName: string;
  sourceFile: string;
  lineNumber: number;
  periodText: string;
  startTimeText: string;
  endTimeText: string;
  valueText: string;
  status: KpiRecordStatus;
  statusLabel: string;
  statusColor: string;
  errorsText: string;
};

const STATUS_META: Record<KpiRecordStatus, { label: string; color: string }> = {
  pass: { label: "通过", color: "#52c41a" },
  warn: { label: "告警", color: "#faad14" },
  fail: { label: "失败", color: "#ff4d4f" },
  neutral: { label: "中性", color: "#8c8c8c" },
  unavailable: { label: "不可用", color: "#8c8c8c" },
};

function utcText(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function buildKpiRecordQuery(
  metricKey: string,
  filters: KpiRecordFilters,
  page: number,
  pageSize: number,
): KpiRecordQuery {
  const normalizedPage = Math.max(1, Math.floor(page) || 1);
  const normalizedSize = Math.min(200, Math.max(1, Math.floor(pageSize) || 50));
  return {
    metric_key: metricKey,
    ...(filters.sourceFile ? { source_file: filters.sourceFile } : {}),
    ...(filters.periodMinutes ? { period_minutes: filters.periodMinutes } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    page: normalizedPage,
    page_size: normalizedSize,
  };
}

export function getKpiRecordRows(items: KpiRecordItem[]): KpiRecordRow[] {
  return items.map((item) => {
    const meta = STATUS_META[item.status] ?? STATUS_META.neutral;
    return {
      id: `${item.metric_key}-${item.source_file}-${item.line_number}`,
      metricName: item.metric_name_zh,
      sourceFile: item.source_file,
      lineNumber: item.line_number,
      periodText: `${item.period_minutes} 分钟`,
      startTimeText: utcText(item.start_at),
      endTimeText: utcText(item.end_at),
      valueText: formatKpiNumber(item.value),
      status: item.status,
      statusLabel: meta.label,
      statusColor: meta.color,
      errorsText: item.errors.length ? item.errors.map((error) => String(error.message || error.code)).join("; ") : "-",
    };
  });
}

export function getKpiRecordPageInfo(page: KpiRecordPage | null): string {
  if (!page) return "";
  if (page.total === 0) return "共 0 条";
  const start = (page.page - 1) * page.page_size + 1;
  const end = Math.max(start, start + page.items.length - 1);
  return `${start}-${end} / 共 ${page.total} 条`;
}
