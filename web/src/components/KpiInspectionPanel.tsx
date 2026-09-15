import { Card, Col, Row, Typography } from "antd";

import { parseKpiMetadata, summarizeKpiMetadata } from "./kpiCatalogModel";
import { KpiDetailTable } from "./KpiDetailTable";
import { KpiMetricCatalog } from "./KpiMetricCatalog";
import { KpiUnclassifiedList } from "./KpiUnclassifiedList";

interface Props {
  metadata: unknown;
}

export function KpiInspectionPanel({ metadata }: Props) {
  const parsed = parseKpiMetadata(metadata);

  if (!parsed) {
    return <KpiDetailTable metadata={metadata as never} />;
  }

  const summary = summarizeKpiMetadata(parsed);

  return (
    <div>
      <Row gutter={[12, 12]}>
        {[
          { label: "指标总数", value: summary.total },
          { label: "重点指标", value: summary.highlight },
          { label: "越限次数", value: summary.breach },
          { label: "不可用指标", value: summary.unavailable },
        ].map((item) => (
          <Col key={item.label} xs={12} md={6}>
            <Card size="small">
              <Typography.Text type="secondary">{item.label}</Typography.Text>
              <div style={{ fontSize: 24, fontWeight: 600 }}>{item.value}</div>
            </Card>
          </Col>
        ))}
      </Row>
      <div style={{ marginTop: 16 }}>
        <KpiMetricCatalog metadata={parsed} />
      </div>
      <div style={{ marginTop: 20 }}>
        <KpiUnclassifiedList metadata={parsed} />
      </div>
      <Typography.Text type="secondary" style={{ display: "block", marginTop: 16, fontSize: 12 }}>
        配置来源：{parsed.config_source} · 输入时区：{parsed.input_timezone}
      </Typography.Text>
    </div>
  );
}
