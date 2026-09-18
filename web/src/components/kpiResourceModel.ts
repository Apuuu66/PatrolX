export type ResourceDomain = "unclassified" | "call" | "api" | "media";

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
