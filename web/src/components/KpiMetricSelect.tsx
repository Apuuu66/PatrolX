import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Input, Select, Spin, Typography } from "antd";
import { api, type KpiResourceDomain, type KpiResourceMetric } from "../api/http";
import {
  buildKpiMetricOptions,
  getKpiMetricDisplayName,
  type KpiMetricSelectOption,
} from "./kpiMetricCatalogModel";

interface KpiMetricCatalogContextValue {
  metrics: KpiResourceMetric[];
  metricIndex: Map<string, KpiResourceMetric>;
  loading: boolean;
  error: string | null;
}

const KpiMetricCatalogContext = createContext<KpiMetricCatalogContextValue>({
  metrics: [],
  metricIndex: new Map(),
  loading: false,
  error: null,
});

const PAGE_SIZE = 200;

export function KpiMetricCatalogProvider({ children }: { children: ReactNode }) {
  const [metrics, setMetrics] = useState<KpiResourceMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const firstPage = await api.listKpiResourceMetrics({ page: 1, page_size: PAGE_SIZE });
        const items = [...firstPage.items];
        const totalPages = Math.ceil(firstPage.total / PAGE_SIZE);
        for (let page = 2; page <= totalPages; page += 1) {
          const nextPage = await api.listKpiResourceMetrics({ page, page_size: PAGE_SIZE });
          items.push(...nextPage.items);
        }
        if (active) setMetrics(Object.values(Object.fromEntries(items.map((item) => [item.key, item]))));
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "指标目录加载失败");
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo<KpiMetricCatalogContextValue>(() => ({
    metrics,
    metricIndex: new Map(metrics.map((metric) => [metric.key, metric])),
    loading,
    error,
  }), [error, loading, metrics]);

  return <KpiMetricCatalogContext.Provider value={value}>{children}</KpiMetricCatalogContext.Provider>;
}

export function useKpiMetricCatalog() {
  return useContext(KpiMetricCatalogContext);
}

export function KpiMetricName({ metricKey }: { metricKey: string }) {
  const { metricIndex, metrics } = useKpiMetricCatalog();
  const displayName = getKpiMetricDisplayName(metrics, metricKey, metricIndex);

  return (
    <div style={{ minWidth: 0 }}>
      <div>{displayName}</div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {metricKey}
      </Typography.Text>
    </div>
  );
}

interface KpiMetricSelectProps {
  id?: string;
  testId?: string;
  value?: string | string[];
  onChange?: (value: string | string[]) => void;
  mode?: "multiple";
  domain?: KpiResourceDomain;
  excludedKeys?: Set<string>;
  placeholder?: string;
  disabled?: boolean;
}

function renderDomainOption(option: KpiMetricSelectOption) {
  return (
    <div>
      <div>{option.label}</div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {option.value} · {option.resourceId} · {option.domain}
      </Typography.Text>
    </div>
  );
}

export function KpiMetricSelect({
  id,
  testId,
  value,
  onChange,
  mode,
  domain,
  excludedKeys,
  placeholder = "选择指标",
  disabled,
}: KpiMetricSelectProps) {
  const { metrics, loading, error } = useKpiMetricCatalog();
  const options = useMemo(() => {
    const selectedKeys = new Set(Array.isArray(value) ? value : value ? [value] : []);
    const visibleMetrics = metrics.filter((metric) => {
      if (domain && metric.domain !== domain) return false;
      if (excludedKeys?.has(metric.key) && !selectedKeys.has(metric.key)) return false;
      return true;
    });
    return buildKpiMetricOptions(visibleMetrics, { excludedKeys });
  }, [domain, excludedKeys, metrics, value]);

  if (error) {
    return (
      <Input
        value={Array.isArray(value) ? value.join(",") : value}
        onChange={(event) => onChange?.(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
    );
  }

  return (
    <Select<string | string[], KpiMetricSelectOption>
      id={id}
      data-testid={testId}
      value={value}
      onChange={onChange as never}
      mode={mode}
      showSearch
      allowClear
      disabled={disabled || loading}
      loading={loading}
      placeholder={placeholder}
      options={options}
      optionFilterProp="search"
      filterOption={(input, option) =>
        String(option?.search ?? "").toLowerCase().includes(input.trim().toLowerCase())
      }
      optionRender={(option) => renderDomainOption(option.data as KpiMetricSelectOption)}
      notFoundContent={loading ? <Spin size="small" /> : "没有匹配指标"}
    />
  );
}
