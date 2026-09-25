const CATEGORY_LABELS: Record<string, string> = {
  log: "日志",
  kpi: "KPI",
  traffic: "话统",
  alarm: "告警",
  config: "配置",
  resource: "资源",
  other: "其他",
};

export function getRuleCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function getRuleCategoryOptionsText(category: string, count: number): string {
  return `${getRuleCategoryLabel(category)} ${count}`;
}
