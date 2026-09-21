export type ResourceDomain = "unclassified" | "call" | "api" | "media" | "reserved";

export interface ResourceQueryInput {
  search?: string;
  domain?: ResourceDomain;
  page?: number;
  pageSize?: number;
}

export interface ResourceQuery {
  search?: string;
  domain?: ResourceDomain;
  page: number;
  page_size: number;
}

export const RESOURCE_DOMAIN_LABELS: Record<ResourceDomain, string> = {
  unclassified: "未分类",
  call: "呼叫",
  api: "API",
  media: "媒体",
  reserved: "预留",
};

export function resourceDomainLabel(value: string): string {
  return RESOURCE_DOMAIN_LABELS[value as ResourceDomain] ?? value;
}

export function buildResourceQuery(input: ResourceQueryInput = {}): ResourceQuery {
  const search = input.search?.trim();
  return {
    search: search || undefined,
    domain: input.domain,
    page: Math.max(1, input.page ?? 1),
    page_size: Math.min(200, Math.max(1, input.pageSize ?? 20)),
  };
}

export function resourceRowSelection<T extends { key: string }>(
  selectedKeys: string[],
  onChange: (keys: string[]) => void,
) {
  return {
    selectedRowKeys: selectedKeys,
    onChange: (keys: (string | number)[]) => onChange(keys.map(String)),
    getCheckboxProps: (row: T) => ({ disabled: row.key.length === 0 }),
  };
}


export type ResourceDomainSummary = Record<ResourceDomain, number>;
export type ResourceDomainFilterValue = "all" | ResourceDomain;

export interface ResourceDomainFilterOption {
  value: ResourceDomainFilterValue;
  label: string;
  count: number;
}

export function buildResourceDomainFilterOptions(
  summary: ResourceDomainSummary,
  total: number,
): ResourceDomainFilterOption[] {
  return [
    { value: "all", label: "全部", count: total },
    ...(Object.keys(RESOURCE_DOMAIN_LABELS) as ResourceDomain[]).map((domain) => ({
      value: domain,
      label: RESOURCE_DOMAIN_LABELS[domain],
      count: summary[domain] ?? 0,
    })),
  ];
}
