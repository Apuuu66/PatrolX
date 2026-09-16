import { Card, Col, Row, Typography } from "antd";

import { getKpiFocusItems, parseKpiMetadata, summarizeKpiMetadata } from "./kpiCatalogModel";
import { KpiDetailTable } from "./KpiDetailTable";
import { KpiMetricCatalog } from "./KpiMetricCatalog";
import { KpiUnclassifiedList } from "./KpiUnclassifiedList";

interface Props {
  metadata: unknown;
  taskId?: string;
  ruleCode?: string;
}

const FOCUS_LIMIT = 8;

export function KpiInspectionPanel({ metadata, taskId, ruleCode }: Props) {
  const parsed = parseKpiMetadata(metadata);

  if (!parsed) {
    return <KpiDetailTable metadata={metadata as never} />;
  }

  const summary = summarizeKpiMetadata(parsed);
  const abnormal = summary.abnormal;
  const focusTotal = getKpiFocusItems(parsed, Number.MAX_SAFE_INTEGER).length;
  const focusItems = getKpiFocusItems(parsed, FOCUS_LIMIT);

  return (
    <div>
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={8}>
          <Card size="small" styles={{ body: { borderColor: abnormal ? "#ffa39e" : "#b7eb8f" } }}>
            <Typography.Text type="secondary">异常指标</Typography.Text>
            <div style={{ fontSize: 28, fontWeight: 700, color: abnormal ? "#cf1322" : "#389e0d" }}>
              {abnormal}
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small">
            <Typography.Text type="secondary">重点指标</Typography.Text>
            <div style={{ fontSize: 28, fontWeight: 600 }}>{summary.highlight}</div>
          </Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small">
            <Typography.Text type="secondary">越限次数</Typography.Text>
            <div style={{ fontSize: 28, fontWeight: 600 }}>{summary.breach}</div>
          </Card>
        </Col>
      </Row>

      <KpiMetricCatalog
        metadata={parsed}
        taskId={taskId}
        ruleCode={ruleCode}
        focusItems={focusItems}
        focusTotal={focusTotal}
      />

      <div style={{ marginTop: 20 }}>
        <KpiUnclassifiedList metadata={parsed} />
      </div>

      <Typography.Text type="secondary" style={{ display: "block", marginTop: 16, fontSize: 12 }}>
        配置来源：{parsed.config_source} · 输入时区：{parsed.input_timezone}
      </Typography.Text>
    </div>
  );
}
