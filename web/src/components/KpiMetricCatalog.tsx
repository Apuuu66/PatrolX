import { useMemo, useState } from "react";
import { Button, Col, Empty, Input, Row, Select, Space, Tabs, Typography } from "antd";

import type { KpiCatalogItem, KpiDisplayStatus } from "./kpiCatalogModel";
import {
  buildKpiMetricNameIndex,
  filterKpiMetricGroups,
  KPI_STATUS_OPTIONS,
  summarizeKpiMetadata,
} from "./kpiCatalogModel";
import { KpiMetricCard } from "./KpiMetricCard";
import { KpiMetricDrawer } from "./KpiMetricDrawer";

interface Props {
  metadata: unknown;
  taskId?: string;
  ruleCode?: string;
  focusItems: KpiCatalogItem[];
  focusTotal: number;
}

const FOCUS_LIMIT = 8;

export function KpiMetricCatalog({ metadata, taskId, ruleCode, focusItems, focusTotal }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<KpiDisplayStatus | undefined>();
  const [threshold, setThreshold] = useState<"with" | "without" | undefined>();
  const [selected, setSelected] = useState<KpiCatalogItem | null>(null);
  const [activeTab, setActiveTab] = useState(focusItems.length ? "focus" : "all");

  const filtered = useMemo(() => filterKpiMetricGroups(metadata, { query, status, threshold }), [metadata, query, status, threshold]);
  const summary = useMemo(() => summarizeKpiMetadata(metadata), [metadata]);
  const metricNames = useMemo(() => buildKpiMetricNameIndex(metadata), [metadata]);

  const renderCards = (items: KpiCatalogItem[]) => (
    <Row gutter={[12, 12]}>
      {items.map((item) => (
        <Col key={item.definition.key} xs={24} sm={12} lg={8} xl={6}>
          <KpiMetricCard
            item={item}
            variant={item.definition.display_role as never}
            onClick={() => setSelected(item)}
          />
        </Col>
      ))}
    </Row>
  );

  const focusTab = focusItems.length ? (
    <div>
      {renderCards(focusItems)}
      {focusTotal > focusItems.length && (
        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <Typography.Text type="secondary">
            还有 {focusTotal - focusItems.length} 个关注项
          </Typography.Text>
          <Button size="small" type="link" onClick={() => setActiveTab("all")}>
            查看全部指标
          </Button>
        </div>
      )}
    </div>
  ) : (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有异常或重点指标" />
  );

  const allTab = (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
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

      {filtered.length === 0 ? (
        <Empty style={{ marginTop: 24 }} description="没有匹配的指标" />
      ) : (
        filtered.map((group) => (
          <div key={group.key} style={{ marginBottom: 20 }}>
            <Typography.Title level={5} style={{ marginBottom: 12 }}>
              {group.label}
              <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                {group.items.length} 项
              </Typography.Text>
            </Typography.Title>
            {renderCards(group.items)}
          </div>
        ))
      )}
    </div>
  );

  return (
    <div style={{ marginTop: 16 }}>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          ...(focusTotal > 0
            ? [{ key: "focus", label: `重点关注（${focusTotal}）`, children: focusTab }]
            : []),
          { key: "all", label: `全部指标（${summary.total}）`, children: allTab },
        ]}
      />
      <KpiMetricDrawer
        item={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        taskId={taskId}
        ruleCode={ruleCode}
        metricNames={metricNames}
      />
    </div>
  );
}

export { FOCUS_LIMIT };
