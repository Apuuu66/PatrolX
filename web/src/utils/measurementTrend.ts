import type { MeasurementTrendPoint } from "../api/http";

export type MeasurementTrendChartOption = {
  tooltip: { trigger: "axis" };
  grid: { left: number; right: number; top: number; bottom: number };
  xAxis: { type: "category"; boundaryGap: false; data: string[] };
  yAxis: { type: "value"; name?: string; scale: boolean };
  dataZoom: Array<{ type: "inside" } | { type: "slider" }>;
  series: Array<{ name: string; type: "line"; smooth: boolean; showSymbol: boolean; data: number[] }>;
};

export function buildTrendChartOption(
  points: MeasurementTrendPoint[],
  metricName: string,
  unit?: string | null,
): MeasurementTrendChartOption | null {
  if (points.length < 2) return null;

  return {
    tooltip: { trigger: "axis" },
    grid: { left: 56, right: 24, top: 40, bottom: 56 },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: points.map((point) => point.time),
    },
    yAxis: { type: "value", name: unit || undefined, scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    series: [
      {
        name: metricName,
        type: "line",
        smooth: true,
        showSymbol: false,
        data: points.map((point) => point.value),
      },
    ],
  };
}
