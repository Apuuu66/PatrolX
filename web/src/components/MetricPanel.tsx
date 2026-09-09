import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { Card, Col, Row, Table, Typography } from "antd";
import type { components } from "../api/client";

type Metric = components["schemas"]["Metric"];

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function MetricPanel({ metrics }: { metrics: Metric[] }) {
  if (!metrics?.length) {
    return <Typography.Text type="secondary">无指标数据</Typography.Text>;
  }

  const scalar = metrics.filter((m) => !m.series || m.series.length === 0);
  const trend = metrics.filter((m) => m.series && m.series.length > 0);

  return (
    <div>
      {scalar.length > 0 && (
        <Row gutter={[12, 12]}>
          {scalar.map((m) => (
            <Col key={m.key} xs={12} sm={8} md={6}>
              <Card size="small">
                <Typography.Text type="secondary">{m.label}</Typography.Text>
                <div style={{ fontSize: 24, fontWeight: 600, marginTop: 4 }}>
                  {String(m.value)}
                  {m.unit && <span style={{ fontSize: 13, color: "#8c8c8c", marginLeft: 4 }}>{m.unit}</span>}
                </div>
                {m.threshold && Object.keys(m.threshold).length > 0 && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    阈值 {JSON.stringify(m.threshold)}
                  </Typography.Text>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
      {trend.map((m) => (
        <TrendChart key={m.key} metric={m} />
      ))}
      {metrics.every((m) => !isNumber(m.value)) && <FallbackTable metrics={metrics} />}
    </div>
  );
}

function TrendChart({ metric }: { metric: Metric }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !metric.series?.length) return;
    const chart = echarts.init(ref.current);
    const points = metric.series.map((s) => ({ x: String(s.t ?? ""), y: Number(s.v ?? 0) }));
    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 24, top: 40, bottom: 32 },
      xAxis: { type: "category", data: points.map((p) => p.x), boundaryGap: false },
      yAxis: { type: "value" },
      series: [
        {
          name: metric.label,
        type: "line",
        smooth: true,
        showSymbol: false,
          data: points.map((p) => p.y),
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [metric]);
  return (
    <Card size="small" title={`${metric.label}（趋势）`} style={{ marginTop: 12 }}>
      <div ref={ref} style={{ height: 280 }} />
    </Card>
  );
}

function FallbackTable({ metrics }: { metrics: Metric[] }) {
  const rows = metrics
    .filter((m) => !isNumber(m.value))
    .map((m) => ({
      key: m.key,
      label: m.label,
      value: String(m.value),
      unit: m.unit ?? "-",
      threshold: m.threshold ? JSON.stringify(m.threshold) : "-",
    }));
  if (!rows.length) return null;
  return (
    <Table
      size="small"
      style={{ marginTop: 12 }}
      dataSource={rows}
      pagination={false}
      columns={[
        { title: "指标", dataIndex: "label" },
        { title: "值", dataIndex: "value" },
        { title: "单位", dataIndex: "unit" },
        { title: "阈值", dataIndex: "threshold" },
      ]}
    />
  );
}
