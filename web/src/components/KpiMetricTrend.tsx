import { useEffect, useMemo, useRef } from "react";
import echarts from "../lib/echarts";
import { Empty, Typography } from "antd";

import { getKpiMetricTrendView } from "./kpiCatalogModel";

const STATUS_COLORS: Record<string, string> = {
  pass: "#52c41a",
  warn: "#faad14",
  fail: "#ff4d4f",
  neutral: "#8c8c8c",
  unavailable: "#8c8c8c",
};

interface Props {
  result: unknown;
  metricName: string;
}

export function KpiMetricTrend({ result, metricName }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const view = useMemo(() => getKpiMetricTrendView(result), [result]);

  useEffect(() => {
    if (!ref.current || !view.points.length) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 52, right: 24, top: 24, bottom: 64 },
      xAxis: {
        type: "category",
        data: view.points.map((point) => point.x),
        boundaryGap: false,
        axisLabel: {
          formatter: (value: string) => (value.length >= 16 ? value.slice(11, 16) : value),
        },
      },
      yAxis: { type: "value", scale: true },
      dataZoom: [
        { type: "inside", start: 0, end: 100 },
        { type: "slider", height: 18, bottom: 12 },
      ],
      series: [
        {
          name: metricName,
          type: "line",
          showSymbol: view.points.length === 1,
          data: view.points.map((point) => ({
            value: point.value,
            itemStyle: { color: STATUS_COLORS[point.status] ?? STATUS_COLORS.neutral },
          })),
        },
      ],
    });
    // Drawer 打开动画可能改变容器尺寸；监听容器本身，避免初始化后图表停留在零宽状态。
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [metricName, view]);

  if (!view.points.length) {
    return (
      <div style={{ marginTop: 12 }}>
        <Typography.Text strong>趋势</Typography.Text>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={view.emptyText || "暂无可用序列"} style={{ marginTop: 8 }} />
      </div>
    );
  }

  return (
    <div style={{ marginTop: 12 }}>
      <Typography.Text strong>趋势</Typography.Text>
      <div ref={ref} style={{ height: 260, marginTop: 8 }} />
    </div>
  );
}
