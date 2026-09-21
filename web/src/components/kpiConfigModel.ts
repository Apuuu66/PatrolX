import type {
  KpiAggregationKindV4,
  KpiDisplayRoleV4,
  KpiMetricRuleRequestV4,
  KpiMetricRuleV4,
  KpiMetricTypeV4,
  KpiRegisteredDomainV4,
  KpiSemanticGroupV4,
  KpiSourceTypeV4,
  KpiThresholdDirectionV4,
  KpiThresholdRequestV4,
  KpiThresholdV4,
} from "../api/http";

export const KPI_AGGREGATION_OPTIONS: { value: KpiAggregationKindV4; label: string }[] = [
  { value: "sum", label: "求和 (sum)" },
  { value: "min", label: "最小值 (min)" },
  { value: "max", label: "最大值 (max)" },
  { value: "mean", label: "均值 (mean)" },
  { value: "count", label: "计数 (count)" },
  { value: "median", label: "中位数 (median)" },
  { value: "stddev", label: "标准差 (stddev)" },
  { value: "success_rate", label: "成功率 (success_rate)" },
];

export const KPI_THRESHOLD_PERIODS = ["5", "15", "30", "60"] as const;

export interface KpiMetricRuleFormValues {
  metric_type: KpiMetricTypeV4;
  semantic_group: KpiSemanticGroupV4;
  display_role: KpiDisplayRoleV4;
  unit: string;
  source_type: KpiSourceTypeV4;
  aggregation_kind: KpiAggregationKindV4;
  description?: string;
  numerator?: string;
  denominator?: string;
  scale?: number;
  denominator_fallback_inputs?: string;
}

export interface KpiThresholdFormValues {
  domain: KpiRegisteredDomainV4;
  metric_key: string;
  label: string;
  direction: KpiThresholdDirectionV4;
  unit: string;
  threshold_id?: number;
  default: number | undefined;
  periods: Partial<Record<(typeof KPI_THRESHOLD_PERIODS)[number], number | null>>;
}

export function buildMetricRulePayload(
  metricKey: string,
  values: KpiMetricRuleFormValues,
  operator: string,
): KpiMetricRuleRequestV4 {
  if (!metricKey.trim()) throw new Error("请输入指标 Key");
  const derived = values.source_type === "derived";
  return {
    metric_type: values.metric_type,
    semantic_group: values.semantic_group,
    display_role: values.display_role,
    unit: values.unit.trim(),
    source_type: values.source_type,
    aggregation_kind: values.aggregation_kind,
    description: values.description?.trim() || null,
    operator,
    formula: derived
      ? {
          kind: "ratio",
          numerator: values.numerator?.trim() ?? "",
          denominator: values.denominator?.trim() ?? "",
          denominator_fallback_inputs: (values.denominator_fallback_inputs ?? "")
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          scale: values.scale ?? 100,
        }
      : null,
  };
}

export function buildThresholdPayload(
  values: KpiThresholdFormValues,
  operator: string,
): KpiThresholdRequestV4 {
  return {
    domain: values.domain,
    metric_key: values.metric_key.trim(),
    label: values.label.trim(),
    direction: values.direction,
    unit: values.unit.trim(),
    default: Number(values.default),
    periods: Object.fromEntries(
      KPI_THRESHOLD_PERIODS.filter((period) => values.periods?.[period] !== null && values.periods?.[period] !== undefined).map(
        (period) => [period, Number(values.periods?.[period])],
      ),
    ),
    operator,
  };
}


export function groupThresholdsByMetricKey(thresholds: KpiThresholdV4[]): Map<string, KpiThresholdV4> {
  return new Map(thresholds.map((threshold) => [threshold.metric_key, threshold]));
}

export function formatKpiThresholdSummary(threshold?: KpiThresholdV4 | null): string {
  if (!threshold) return "未配置";
  const prefix = threshold.direction === "max" ? "上限 ≤" : "下限 ≥";
  return `${prefix} ${Number(threshold.default)}${threshold.unit}`;
}

export function buildThresholdFormValuesForMetric(
  metricRule: Pick<KpiMetricRuleV4, "metric_key" | "domain" | "unit">,
  threshold?: KpiThresholdV4 | null,
  metricName?: string,
): KpiThresholdFormValues {
  const domain = threshold?.domain ?? metricRule.domain;
  if (!domain) throw new Error("当前指标缺少业务域，无法配置阈值");
  return {
    ...(threshold ? { threshold_id: threshold.id } : {}),
    domain,
    metric_key: metricRule.metric_key,
    label: threshold?.label ?? metricName ?? metricRule.metric_key,
    direction: threshold?.direction ?? "min",
    unit: threshold?.unit ?? metricRule.unit,
    default: threshold === undefined || threshold === null ? undefined : Number(threshold.default),
    periods: threshold
      ? Object.fromEntries(KPI_THRESHOLD_PERIODS.map((period) => [period, threshold.periods[period] ?? null]))
      : {},
  };
}
