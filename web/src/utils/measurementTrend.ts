import type { MeasurementTrendPoint } from "../api/http";

export type MeasurementTrendChartOption = {
  tooltip: { trigger: "axis" };
  grid: { left: number; right: number; top: number; bottom: number };
  xAxis: { type: "category"; boundaryGap: false; data: string[] };
  yAxis: { type: "value"; name?: string; scale: boolean };
  dataZoom: Array<{ type: "inside" } | { type: "slider" }>;
  series: Array<{ name: string; type: "line"; smooth: boolean; showSymbol: boolean; data: number[] }>;
};

export type MeasurementDailyTrendChartOption = {
  tooltip: { trigger: "axis" };
  legend: { top: 0 };
  grid: { left: number; right: number; top: number; bottom: number };
  xAxis: { type: "category"; boundaryGap: false; data: string[] };
  yAxis: { type: "value"; name?: string; scale: boolean };
  dataZoom: Array<{ type: "inside" } | { type: "slider" }>;
  series: Array<{
    name: string;
    type: "line";
    smooth: boolean;
    showSymbol: boolean;
    connectNulls: boolean;
    lineStyle?: { type: "dashed" };
    data: Array<number | null>;
  }>;
};

export type TrendComparisonMode = "multi_day" | "short_window" | "insufficient";

export type TrendComparison = {
  mode: TrendComparisonMode;
  message: string;
  latestTime?: string;
  latestValue?: number;
  baselineValue?: number | null;
  deviation?: number | null;
  deviationRatio?: number | null;
};

type ParsedTrendPoint = {
  date: string;
  timeLabel: string;
  sortKey: string;
  value: number;
  source: MeasurementTrendPoint;
};

const DATE_TIME_PATTERN = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2})?/;

function parseTrendPoint(point: MeasurementTrendPoint): ParsedTrendPoint | null {
  const match = DATE_TIME_PATTERN.exec(point.time);
  if (!match || typeof point.value !== "number" || !Number.isFinite(point.value)) return null;
  const [, date, timeLabel] = match;
  return {
    date,
    timeLabel,
    sortKey: `${date} ${timeLabel}`,
    value: point.value,
    source: point,
  };
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function deviationRatio(value: number, baseline: number | null): number | null {
  if (baseline === null || baseline === 0) return null;
  return (value - baseline) / Math.abs(baseline);
}

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

export function analyzeTrendComparison(points: MeasurementTrendPoint[]): TrendComparison {
  const parsed = points.map(parseTrendPoint).filter((item): item is ParsedTrendPoint => item !== null);
  parsed.sort((left, right) => left.sortKey.localeCompare(right.sortKey));

  const latest = parsed[parsed.length - 1];
  if (!latest) {
    return { mode: "insufficient", message: "趋势点不足，无法生成基线对比" };
  }
  if (parsed.length < 2) {
    return {
      mode: "insufficient",
      message: "趋势点不足，无法生成基线对比",
      latestTime: latest.source.time,
      latestValue: latest.value,
      baselineValue: null,
      deviation: null,
      deviationRatio: null,
    };
  }

  const dates = [...new Set(parsed.map((item) => item.date))].sort();
  if (dates.length > 1) {
    const latestDate = latest.date;
    const history = parsed.filter((item) => item.date < latestDate);
    const historyDates = new Set(history.map((item) => item.date));
    const baseline = median(history.filter((item) => item.timeLabel === latest.timeLabel).map((item) => item.value));
    const deviation = baseline === null ? null : latest.value - baseline;

    return {
      mode: "multi_day",
      message: `按最近 ${historyDates.size} 天同时刻基线对比`,
      latestTime: latest.source.time,
      latestValue: latest.value,
      baselineValue: baseline,
      deviation,
      deviationRatio: deviationRatio(latest.value, baseline),
    };
  }

  if (parsed.length < 3) {
    return {
      mode: "insufficient",
      message: "趋势点不足，无法生成短期基线对比",
      latestTime: latest.source.time,
      latestValue: latest.value,
      baselineValue: null,
      deviation: null,
      deviationRatio: null,
    };
  }

  const recentBaselinePoints = parsed.slice(Math.max(0, parsed.length - 9), -1);
  const baseline = median(recentBaselinePoints.map((item) => item.value));
  const deviation = baseline === null ? null : latest.value - baseline;

  return {
    mode: "short_window",
    message: "单日数据，仅做短期突变对比",
    latestTime: latest.source.time,
    latestValue: latest.value,
    baselineValue: baseline,
    deviation,
    deviationRatio: deviationRatio(latest.value, baseline),
  };
}

export function buildDailyTrendChartOption(
  points: MeasurementTrendPoint[],
  _metricName: string,
  unit?: string | null,
): MeasurementDailyTrendChartOption | null {
  const parsed = points.map(parseTrendPoint).filter((item): item is ParsedTrendPoint => item !== null);
  const dates = [...new Set(parsed.map((item) => item.date))].sort();
  if (dates.length < 2) return null;

  const timeLabels = [...new Set(parsed.map((item) => item.timeLabel))].sort();
  const latestDate = dates[dates.length - 1] ?? dates[0];
  const historyDates = dates.filter((date) => date < latestDate);

  const grouped = new Map<string, Map<string, number>>();
  for (const item of parsed) {
    const dateGroup = grouped.get(item.date) ?? new Map<string, number>();
    dateGroup.set(item.timeLabel, item.value);
    grouped.set(item.date, dateGroup);
  }

  const series: MeasurementDailyTrendChartOption["series"] = dates.map((date) => ({
    name: date,
    type: "line" as const,
    smooth: true,
    showSymbol: false,
    connectNulls: true,
    data: timeLabels.map((timeLabel) => grouped.get(date)?.get(timeLabel) ?? null),
  }));

  const baselineValues = timeLabels.map((timeLabel) =>
    median(historyDates.map((date) => grouped.get(date)?.get(timeLabel)).filter((value): value is number => value !== undefined)),
  );
  series.push({
    name: "历史基线",
    type: "line",
    smooth: true,
    showSymbol: false,
    connectNulls: true,
    lineStyle: { type: "dashed" },
    data: baselineValues,
  });

  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 56, right: 24, top: 48, bottom: 56 },
    xAxis: { type: "category", boundaryGap: false, data: timeLabels },
    yAxis: { type: "value", name: unit || undefined, scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    series,
  };
}
