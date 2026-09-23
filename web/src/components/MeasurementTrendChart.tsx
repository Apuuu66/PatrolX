import { Button, Empty, Modal } from "antd";
import { useEffect, useRef, useState } from "react";
import type { MeasurementMetadataMetric, MeasurementTrendPoint } from "../api/http";
import echarts from "../lib/echarts";
import { buildTrendChartOption } from "../utils/measurementTrend";

function MetricDisplayName(metric: { metric_resource_id: string; metric_resource_name_zh?: string | null; base_source_name?: string }) {
  return metric.metric_resource_name_zh || metric.base_source_name || metric.metric_resource_id;
}

function MiniTrend({ points }: { points: MeasurementTrendPoint[] }) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 96;
      const y = 28 - ((point.value - min) / range) * 24;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg width="104" height="32" role="img" aria-label="任务内迷你趋势">
      <path d={path} fill="none" stroke="#1677ff" strokeWidth={2} />
    </svg>
  );
}

function TrendChart({ metricName, points, unit }: { metricName: string; points: MeasurementTrendPoint[]; unit?: string | null }) {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = chartRef.current;
    const option = buildTrendChartOption(points, metricName, unit);
    if (!element || !option) return;

    const chart = echarts.init(element);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [metricName, points, unit]);

  if (points.length < 2) {
    return <Empty description="趋势点不足" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return <div ref={chartRef} style={{ height: 380 }} />;
}

type MetricTrendCellMetric = Pick<
  MeasurementMetadataMetric,
  "base_source_name" | "display_unit" | "metric_resource_id" | "metric_resource_name_zh" | "trend_points"
>;

export function MetricTrendCell({ metric }: { metric: MetricTrendCellMetric }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const points = metric.trend_points ?? [];
  const metricName = MetricDisplayName(metric);

  if (points.length < 2) {
    return <span style={{ color: "rgba(0, 0, 0, 0.45)" }}>趋势点不足</span>;
  }

  return (
    <>
      <Button
        type="text"
        style={{ height: "auto", padding: 0 }}
        title="查看完整趋势"
        aria-label={`查看${metricName}完整趋势`}
        onClick={() => setIsModalOpen(true)}
      >
        <MiniTrend points={points} />
      </Button>
      <Modal
        destroyOnClose
        footer={null}
        open={isModalOpen}
        title={metricName}
        width={960}
        onCancel={() => setIsModalOpen(false)}
      >
        <TrendChart metricName={metricName} points={points} unit={metric.display_unit} />
      </Modal>
    </>
  );
}
