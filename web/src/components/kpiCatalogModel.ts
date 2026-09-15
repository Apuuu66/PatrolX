export type KpiDisplayStatus = "pass" | "warn" | "fail" | "neutral" | "unavailable";

export type KpiMetricDefinition = {
  key: string;
  name_zh: string;
  name_en: string;
  aliases: Array<{ language?: string; value?: string }>;
  metric_type: string;
  semantic_group: string;
  display_role: string;
  unit: string | null;
  source_type: string;
  aggregation: Record<string, unknown>;
  formula?: Record<string, unknown> | null;
};

export type KpiMetricResult = {
  key: string;
  main_value: number | string | null;
  value_available: boolean;
  unavailable_reason?: string | null;
  display_status: KpiDisplayStatus;
  unit: string | null;
  aggregation: string;
  threshold?: Record<string, unknown> | null;
  breach_count: number;
  series: Record<string, unknown>[];
  source_files: string[];
  provenance: Record<string, unknown>;
};

export type KpiCatalogItem = {
  definition: KpiMetricDefinition;
  result: KpiMetricResult | null;
};

export type KpiMetricGroup = {
  key: string;
  label: string;
  items: KpiCatalogItem[];
};

export type KpiUnclassifiedMetric = {
  source_name: string;
  source_files: string[];
  record_count: number;
  sample_values: unknown[];
  reason: string;
};

export type KpiMetadata = {
  version: number;
  domain: string;
  config_source: string;
  input_timezone: string;
  metric_catalog: KpiMetricDefinition[];
  kpi_results: KpiMetricResult[];
  unclassified_metrics: KpiUnclassifiedMetric[];
  kpi_files: Record<string, unknown>[];
};

const SEMANTIC_GROUP_LABELS: Record<string, string> = {
  quality: "质量",
  traffic: "流量",
  capacity: "容量",
  latency: "时延",
  other: "其他",
};

const STATUS_META: Record<KpiDisplayStatus, { label: string; color: string }> = {
  pass: { label: "通过", color: "#52c41a" },
  warn: { label: "告警", color: "#faad14" },
  fail: { label: "失败", color: "#ff4d4f" },
  neutral: { label: "中性", color: "#8c8c8c" },
  unavailable: { label: "不可用", color: "#8c8c8c" },
};

export const KPI_STATUS_OPTIONS: Array<{ value: KpiDisplayStatus; label: string }> = Object.entries(STATUS_META).map(
  ([value, meta]) => ({ value: value as KpiDisplayStatus, label: meta.label }),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function readOptionalRecord(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function readDefinition(value: unknown): KpiMetricDefinition | null {
  if (!isRecord(value) || typeof value.key !== "string" || !value.key) return null;
  return {
    key: value.key,
    name_zh: readString(value.name_zh, value.key),
    name_en: readString(value.name_en, value.key),
    aliases: asArray(value.aliases)
      .map((item) => readRecord(item))
      .map((item) => ({ language: readString(item.language), value: readString(item.value) })),
    metric_type: readString(value.metric_type, "gauge"),
    semantic_group: readString(value.semantic_group, "other"),
    display_role: readString(value.display_role, "catalog"),
    unit: typeof value.unit === "string" ? value.unit : null,
    source_type: readString(value.source_type, "raw"),
    aggregation: readRecord(value.aggregation),
    formula: readOptionalRecord(value.formula),
  };
}

function readResult(value: unknown): KpiMetricResult | null {
  if (!isRecord(value) || typeof value.key !== "string") return null;
  const status = readString(value.display_status, "neutral") as KpiDisplayStatus;
  return {
    key: value.key,
    main_value: typeof value.main_value === "number" || typeof value.main_value === "string" ? value.main_value : null,
    value_available: value.value_available === true,
    unavailable_reason: typeof value.unavailable_reason === "string" ? value.unavailable_reason : null,
    display_status: STATUS_META[status] ? status : "neutral",
    unit: typeof value.unit === "string" ? value.unit : null,
    aggregation: readString(value.aggregation, "-"),
    threshold: readOptionalRecord(value.threshold),
    breach_count: readNumber(value.breach_count) ?? 0,
    series: asArray(value.series).map((item) => readRecord(item)),
    source_files: asArray(value.source_files).map((item) => readString(item)).filter(Boolean),
    provenance: readRecord(value.provenance),
  };
}

function readUnclassified(value: unknown): KpiUnclassifiedMetric | null {
  if (!isRecord(value) || typeof value.source_name !== "string") return null;
  return {
    source_name: value.source_name,
    source_files: asArray(value.source_files).map((item) => readString(item)).filter(Boolean),
    record_count: readNumber(value.record_count) ?? 0,
    sample_values: asArray(value.sample_values),
    reason: readString(value.reason, "metric_not_registered"),
  };
}

export function parseKpiMetadata(metadata: unknown): KpiMetadata | null {
  const record = readRecord(metadata);
  const version = readNumber(record.version);
  if (!record.metric_catalog || !record.kpi_results || version === null || version < 2) return null;
  const definitions = asArray(record.metric_catalog)
    .map(readDefinition)
    .filter((item): item is KpiMetricDefinition => item !== null);
  const results = asArray(record.kpi_results)
    .map(readResult)
    .filter((item): item is KpiMetricResult => item !== null);
  return {
    version,
    domain: readString(record.domain, "-"),
    config_source: readString(record.config_source, "deploy/config/kpi"),
    input_timezone: readString(record.input_timezone, "UTC"),
    metric_catalog: definitions,
    kpi_results: results,
    unclassified_metrics: asArray(record.unclassified_metrics)
      .map(readUnclassified)
      .filter((item): item is KpiUnclassifiedMetric => item !== null),
    kpi_files: asArray(record.kpi_files).map((item) => readRecord(item)),
  };
}

export function buildKpiMetricItems(metadata: unknown): KpiCatalogItem[] {
  const parsed = parseKpiMetadata(metadata);
  if (!parsed) return [];
  const resultByKey = new Map(parsed.kpi_results.map((result) => [result.key, result]));
  return parsed.metric_catalog.map((definition) => ({
    definition,
    result: resultByKey.get(definition.key) ?? null,
  }));
}

export function buildKpiMetricGroups(metadata: unknown): KpiMetricGroup[] {
  const grouped = new Map<string, KpiCatalogItem[]>();
  buildKpiMetricItems(metadata).forEach((item) => {
    const key = item.definition.semantic_group;
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  });
  return [...grouped.entries()].map(([key, items]) => ({
    key,
    label: SEMANTIC_GROUP_LABELS[key] ?? key,
    items,
  }));
}

export type KpiCatalogFilter = {
  query?: string;
  status?: KpiDisplayStatus;
  threshold?: "with" | "without";
};

export function filterKpiMetricGroups(metadata: unknown, filter: KpiCatalogFilter): KpiMetricGroup[] {
  const query = filter.query?.trim().toLowerCase() ?? "";
  return buildKpiMetricGroups(metadata)
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        const { definition, result } = item;
        if (filter.status && result?.display_status !== filter.status) return false;
        if (filter.threshold === "with" && !result?.threshold) return false;
        if (filter.threshold === "without" && result?.threshold) return false;
        if (!query) return true;
        const haystack = [
          definition.name_zh,
          definition.name_en,
          definition.key,
          ...definition.aliases.map((alias) => alias.value ?? ""),
        ]
          .join("\n")
          .toLowerCase();
        return haystack.includes(query);
      }),
    }))
    .filter((group) => group.items.length > 0);
}

export function summarizeKpiMetadata(metadata: unknown): {
  total: number;
  highlight: number;
  breach: number;
  unavailable: number;
} {
  const items = buildKpiMetricItems(metadata);
  return {
    total: items.length,
    highlight: items.filter((item) => item.definition.display_role === "highlight").length,
    breach: items.reduce((sum, item) => sum + (item.result?.breach_count ?? 0), 0),
    unavailable: items.filter((item) => item.result?.display_status === "unavailable").length,
  };
}

export function getKpiMetricCardView(item: {
  definition: unknown;
  result?: unknown;
}): {
  title: string;
  subtitle: string;
  mainValueText: string;
  unitText: string;
  statusLabel: string;
  statusColor: string;
  thresholdText: string;
  aggregationText: string;
  breachText: string;
} {
  const definition = readRecord(item.definition);
  const result = readRecord(item.result);
  const key = readString(definition.key, "-");
  const nameZh = readString(definition.name_zh, key);
  const nameEn = readString(definition.name_en, key);
  const status = readString(result.display_status, "neutral") as KpiDisplayStatus;
  const meta = STATUS_META[STATUS_META[status] ? status : "neutral"];
  const unit = typeof result.unit === "string" ? result.unit : typeof definition.unit === "string" ? definition.unit : "";
  const available = result.value_available === true;
  const mainValue = available && (typeof result.main_value === "number" || typeof result.main_value === "string") ? result.main_value : null;
  const threshold = readRecord(result.threshold);
  const direction = readString(threshold.direction);
  const limit = readNumber(threshold.default);
  const limitUnit = typeof threshold.unit === "string" ? threshold.unit : unit;
  const thresholdText = !Object.keys(threshold).length
    ? "无阈值"
    : direction === "min" && limit !== null
      ? `阈值 ≥ ${limit}${limitUnit}`
      : direction === "max" && limit !== null
        ? `阈值 ≤ ${limit}${limitUnit}`
        : "已配置阈值";
  const breachCount = readNumber(result.breach_count) ?? 0;
  const aggregation = readRecord(definition.aggregation);
  const aggregationKind = readString(aggregation.kind, readString(result.aggregation, "-"));

  return {
    title: nameZh,
    subtitle: nameEn,
    mainValueText: mainValue === null ? "-" : String(mainValue),
    unitText: unit,
    statusLabel: meta.label,
    statusColor: meta.color,
    thresholdText,
    aggregationText: aggregationKind,
    breachText: breachCount > 0 ? `越限 ${breachCount}` : "",
  };
}
