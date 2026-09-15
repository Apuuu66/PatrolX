import type {
  DataPreparation,
  PreparationItem,
  PreparationIssue,
} from "../api/http";

const ABNORMAL_STATUSES = new Set<PreparationItem["status"]>(["warn", "fail", "error"]);
const NORMAL_STATUSES = new Set<PreparationItem["status"]>(["pass", "skip"]);
const CATEGORY_LABELS: Record<string, string> = {
  main: "主包",
  logs: "日志",
  kpi: "KPI",
  traffic: "流量",
  alarm: "告警",
  config: "配置",
  resource: "资源",
  other: "其他",
};
const MAX_VISIBLE_ABNORMAL_ITEMS = 3;
const DEFAULT_PATH_LENGTH = 80;

export type PreparationDisplay = {
  summary: string;
  abnormalItems: PreparationItem[];
  visibleAbnormalItems: PreparationItem[];
  hiddenAbnormalCount: number;
  normalSummary: string;
  issueCount: number;
  hasAbnormal: boolean;
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function truncateMiddle(value: string, maxLength = DEFAULT_PATH_LENGTH): string {
  if (value.length <= maxLength) {
    return value;
  }
  const reserve = maxLength - 1;
  const headLength = Math.ceil(reserve / 2);
  const tailLength = Math.floor(reserve / 2);
  return `${value.slice(0, headLength)}…${value.slice(-tailLength)}`;
}

export function formatPreparationIssuePath(issue: PreparationIssue): string {
  const source = issue.source ? truncateMiddle(issue.source) : "-";
  const target = issue.target ? truncateMiddle(issue.target) : "-";
  let text = `${source} → ${target}`;
  if (issue.path_length !== undefined && issue.path_length !== null) {
    text += ` · 长度 ${issue.path_length}`;
    if (issue.path_limit !== undefined && issue.path_limit !== null) {
      text += `/${issue.path_limit}`;
    }
  }
  return text;
}

export function getPreparationDisplay(
  preparation: DataPreparation,
  showAllAbnormal = false,
): PreparationDisplay {
  const abnormalItems = preparation.items.filter((item) => ABNORMAL_STATUSES.has(item.status));
  const normalItems = preparation.items.filter((item) => NORMAL_STATUSES.has(item.status));
  const issueCount = abnormalItems.reduce((total, item) => total + item.issues.length, 0);
  const hasAbnormal = abnormalItems.length > 0;
  const visibleAbnormalItems = showAllAbnormal
    ? abnormalItems
    : abnormalItems.slice(0, MAX_VISIBLE_ABNORMAL_ITEMS);

  return {
    summary: hasAbnormal
      ? `⚠ ${abnormalItems.length} 类异常 · ${issueCount} 个问题 · 正常 ${normalItems.length} 类`
      : `✓ 正常 ${normalItems.length} 类`,
    abnormalItems,
    visibleAbnormalItems,
    hiddenAbnormalCount: abnormalItems.length - visibleAbnormalItems.length,
    normalSummary: normalItems.length
      ? `正常：${normalItems.map((item) => categoryLabel(item.category)).join(" · ")}`
      : "",
    issueCount,
    hasAbnormal,
  };
}

export { categoryLabel, MAX_VISIBLE_ABNORMAL_ITEMS };
