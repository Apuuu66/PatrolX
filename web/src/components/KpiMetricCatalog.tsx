import { useMemo, useState } from "react";
import { Col, Empty, Input, Row, Select, Space, Typography } from "antd";

import type { KpiCatalogItem, KpiDisplayStatus } from "./kpiCatalogModel";
import {
  buildKpiMetricGroups,
  filterKpiMetricGroups,
  KPI_STATUS_OPTIONS,
  summarizeKpiMetadata,
} from "./kpiCatalogModel";
import { KpiMetricCard } from "./KpiMetricCard";
import { KpiMetricDrawer } from "./KpiMetricDrawer";

interface Props {
  metadata: unknown;
}

export function KpiMetricCatalog({ metadata }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<KpiDisplayStatus | undefined>();
  const [threshold, setThreshold] = useState<"with" | "without" | undefined>();
  const [selected, setSelected] = useState<KpiCatalogItem | null>(null);

  const groups = useMemo(() => buildKpiMetricGroups(metadata), [metadata]);
  const filtered = useMemo(() => filterKpiMetricGroups(metadata, { query, status, threshold }), [metadata, query, status, threshold]);
  const summary = useMemo(() => summarizeKpiMetadata(metadata), [metadata]);

  if (!groups.length) {
    return <Empty description="暂无 KPI 目录" />;
  }

  return (
    <div>
      <Space direction="vertical" style={{ width: "100%" }} size={12}>
        <Typography.Text type="secondary">
          {summary.total} 个指标 · {summary.highlight} 个重点 · {summary.breach} 次越限 · {summary.unavailable} 个不可用
        </Typography.Text>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder="搜索中文名、英文名、key 或别名"
            style={{ width: 280 }}
            onSearch={setQuery}
            onChange={(event) => setQuery(event.target.value)}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={status}
            options={KPI_STATUS_OPTIONS}
            onChange={(value) => setStatus(value)}
          />
          <Select
            allowClear
            placeholder="阈值"
            style={{ width: 130 }}
            value={threshold}
            options={[
              { value: "with", label: "有阈值" },
              { value: "without", label: "无阈值" },
            ]}
            onChange={(value) => setThreshold(value)}
          />
        </Space>
      </Space>

      {filtered.length === 0 ? (
        <Empty style={{ marginTop: 24 }} description="没有匹配的指标" />
      ) : (
        filtered.map((group) => (
          <div key={group.key} style={{ marginTop: 20 }}>
            <Typography.Title level={5} style={{ marginBottom: 12 }}>
              {group.label}
              <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                {group.items.length} 项
              </Typography.Text>
            </Typography.Title>
            <Row gutter={[12, 12]}>
              {group.items.map((item) => (
                <Col key={item.definition.key} xs={24} sm={12} lg={8} xl={6}>
                  <KpiMetricCard
                    item={item}
                    variant={item.definition.display_role as never}
                    onClick={() => setSelected(item)}
                  />
                </Col>
              ))}
            </Row>
          </div>
        ))
      )}

      <KpiMetricDrawer item={selected} open={Boolean(selected)} onClose={() => setSelected(null)} />
    </div>
  );
}
