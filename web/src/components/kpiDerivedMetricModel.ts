import type {
  KpiDisplayRoleV4,
  KpiMetricTypeV4,
  KpiRegisteredDomainV4,
  KpiSemanticGroupV4,
} from "../api/http";

export interface KpiDerivedMetricFormValues {
  metric_key?: string;
  name_zh: string;
  name_en: string;
  domain: KpiRegisteredDomainV4;
  metric_type: KpiMetricTypeV4;
  semantic_group: KpiSemanticGroupV4;
  display_role: KpiDisplayRoleV4;
  unit: string;
  description?: string;
  enabled: boolean;
  formula_kind: "ratio" | "inverse_ratio";
  numerator: string;
  denominator: string;
  denominator_fallback_inputs?: string[];
  scale: number;
}

const DERIVED_METRIC_KEY_RE = /^[a-z][a-z0-9_]{2,127}$/;

export function validateKpiDerivedMetricDraft(
  values: Partial<KpiDerivedMetricFormValues>,
  editing: boolean,
): string[] {
  const errors: string[] = [];
  if (!editing) {
    const metricKey = values.metric_key?.trim();
    if (!metricKey) errors.push("请输入派生指标 key");
    else if (!DERIVED_METRIC_KEY_RE.test(metricKey)) errors.push("派生指标 key 格式不正确");
  }
  if (!values.name_zh?.trim()) errors.push("请输入中文名");
  if (!values.name_en?.trim()) errors.push("请输入英文名");
  if (!values.unit?.trim()) errors.push("请输入单位");
  if (!values.numerator) errors.push("请选择分子");
  if (!values.denominator) errors.push("请选择分母");
  if (values.scale === undefined || Number.isNaN(values.scale) || values.scale <= 0) {
    errors.push("请输入大于 0 的倍率");
  }
  return errors;
}

export function buildKpiDerivedMetricPayload(values: KpiDerivedMetricFormValues) {
  return {
    name_zh: values.name_zh.trim(),
    name_en: values.name_en.trim(),
    domain: values.domain,
    metric_type: values.metric_type,
    semantic_group: values.semantic_group,
    display_role: values.display_role,
    unit: values.unit.trim(),
    description: values.description?.trim() || undefined,
    enabled: values.enabled,
    formula: {
      kind: values.formula_kind,
      numerator: values.numerator,
      denominator: values.denominator,
      denominator_fallback_inputs: values.denominator_fallback_inputs ?? [],
      scale: Number(values.scale),
    },
  };
}
