import { Card } from "antd";
import { useEffect, useRef } from "react";
import type { components } from "../api/client";
import echarts from "../lib/echarts";

type Metric = components["schemas"]["Metric"];

export default function MetricTrendChart({ metric }: { metric: Metric }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !metric.series?.length) return;
    const chart = echarts.init(ref.current);
    const points = metric.series.map((series) => ({ x: String(series.t ?? ""), y: Number(series.v ?? 0) }));
    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 24, top: 40, bottom: 32 },
      xAxis: { type: "category", data: points.map((point) => point.x), boundaryGap: false },
      yAxis: { type: "value" },
      series: [
        {
          name: metric.label,
          type: "line",
          smooth: true,
          showSymbol: false,
          data: points.map((point) => point.y),
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
