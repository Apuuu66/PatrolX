import type { KpiRegisteredDomainV4, KpiResourceDomain, KpiResourceMetric } from "../api/http";

export interface KpiMetricSelectOption {
  value: string;
  label: string;
  domain: KpiResourceDomain;
  resourceId: string;
  search: string;
}

export function getKpiMetricDisplayName(
  metrics: KpiResourceMetric[],
  metricKey: string,
  index?: Map<string, KpiResourceMetric>,
): string {
  const metric = index?.get(metricKey) ?? metrics.find((item) => item.key === metricKey);
  return metric?.name_zh || metric?.name_en || metricKey;
}

export function matchesKpiMetric(metric: KpiResourceMetric, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return [
    metric.name_zh,
    metric.name_en,
    metric.key,
    metric.resource_id,
  ].some((value) => value.toLowerCase().includes(normalizedQuery));
}

export function buildKpiMetricOptions(
  metrics: KpiResourceMetric[],
  { excludedKeys = new Set<string>() }: { excludedKeys?: Set<string> } = {},
): KpiMetricSelectOption[] {
  return metrics
    .filter((metric) => !excludedKeys.has(metric.key))
    .map((metric) => ({
      value: metric.key,
      label: getKpiMetricDisplayName(metrics, metric.key),
      domain: metric.domain,
      resourceId: metric.resource_id,
      search: [
        metric.name_zh,
        metric.name_en,
        metric.key,
        metric.resource_id,
        metric.name_zh,
      ].join(" "),
    }));
}

export function toKpiRegisteredDomain(domain: KpiResourceDomain): KpiRegisteredDomainV4 | undefined {
  return domain === "call" || domain === "api" || domain === "media" ? domain : undefined;
}
