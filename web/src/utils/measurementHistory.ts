import type {
  MeasurementHistoryTrend,
  MeasurementTrend,
  MeasurementTrendPoint,
} from "../api/http";
import type { MeasurementDailyTrendChartOption } from "./measurementTrend";

export type TrendSelection = { objectKey: string; periodKey: string };

export type TrendSelectionOption = {
  value: string;
  label: string;
  periodMinutes?: number | null;
};

export type TrendSelectionOptions = {
  objectOptions: TrendSelectionOption[];
  periodOptions: TrendSelectionOption[];
};

export type HistoryMatchAlert = {
  type: "info" | "warning" | "error";
  title: string;
  description: string;
};

const ALL_OBJECT = "__all__";
const NO_PERIOD = "none";

function periodKey(value: number | null | undefined): string {
  return value === null || value === undefined ? NO_PERIOD : String(value);
}

export function historyPeriodLabel(periodMinutes: number | null | undefined): string {
  if (periodMinutes === null || periodMinutes === undefined) return "未识别周期";
  return `${periodMinutes} 分钟`;
}

function objectLabel(objectKey: string): string {
  return objectKey === ALL_OBJECT ? "全部对象" : objectKey;
}

export function buildTrendSelectionOptions(trends: MeasurementTrend[] = []): TrendSelectionOptions {
  const objects = [...new Set(trends.map((trend) => trend.object_key ?? ALL_OBJECT))].sort((left, right) =>
    objectLabel(left).localeCompare(objectLabel(right), "zh-Hans-CN"),
  );
  const periods = [
    ...new Map(
      trends.map((trend) => [
        periodKey(trend.period_minutes),
        { value: periodKey(trend.period_minutes), label: historyPeriodLabel(trend.period_minutes), periodMinutes: trend.period_minutes ?? null },
      ]),
    ).values(),
  ].sort((left, right) => (left.periodMinutes ?? Number.POSITIVE_INFINITY) - (right.periodMinutes ?? Number.POSITIVE_INFINITY));

  return {
    objectOptions: objects.map((value) => ({ value, label: objectLabel(value) })),
    periodOptions: periods,
  };
}

export function defaultTrendSelection(trends: MeasurementTrend[] = []): TrendSelection {
  const withPoints = trends.filter((trend) => (trend.points ?? []).length > 0);
  const preferred = withPoints.find((trend) => trend.period_minutes === 15) ?? withPoints.find((trend) => trend.period_minutes === 5) ?? withPoints[0];
  const fallback = trends.find((trend) => trend.period_minutes === 15) ?? trends.find((trend) => trend.period_minutes === 5) ?? trends[0];
  const trend = preferred ?? fallback;
  return {
    objectKey: trend?.object_key ?? ALL_OBJECT,
    periodKey: periodKey(trend?.period_minutes),
  };
}

export function historyMatchAlert(match: MeasurementHistoryTrend["match"]): HistoryMatchAlert {
  const descriptions: Record<string, string> = {
    device_id_missing: "当前任务未填写设备 ID，无法匹配历史任务",
    current_measurement_time_missing: "当前任务缺少有效测量时间，无法生成 7 天窗口",
    history_index_missing: "历史索引缺失，请先重跑当前任务生成历史索引",
    metric_dimension_missing: "当前任务没有该指标、对象和周期的有效趋势点",
    period_mismatch: "历史任务周期与当前任务不一致",
    metric_not_supported: "该指标不支持历史对比",
  };

  if (match.status === "no_history") {
    return {
      type: "warning",
      title: "暂无历史",
      description: match.message || "当前设备还没有可对比的历史任务",
    };
  }
  if (match.status === "degraded") {
    return {
      type: "warning",
      title: "历史对比降级",
      description: descriptions[match.reason_code ?? ""] ?? match.message,
    };
  }
  return {
    type: "info",
    title: "历史对比",
    description: match.message || "已按设备、测量单元、指标、行对象和周期匹配历史任务",
  };
}

export function insufficientSampleCount(trend: MeasurementHistoryTrend): number {
  return trend.baseline_points.filter((point) => point.significance === "insufficient").length;
}

type MarkPoint = {
  coord: [string, number];
  value: number;
  significance: "higher" | "lower";
};

function addToHistory(
  grouped: Map<string, Map<string, number>>,
  points: Array<{ date: string; time_label: string; value: number }>,
): void {
  for (const point of points) {
    if (!Number.isFinite(point.value)) continue;
    const dateGroup = grouped.get(point.date) ?? new Map<string, number>();
    dateGroup.set(point.time_label, point.value);
    grouped.set(point.date, dateGroup);
  }
}

export function buildHistoryTrendChartOption(
  trend: MeasurementHistoryTrend,
  unit?: string | null,
): MeasurementDailyTrendChartOption | null {
  const history = new Map<string, Map<string, number>>();
  addToHistory(history, trend.history_series.flatMap((series) => series.points));
  const currentDate = trend.current_points[0]?.date ?? trend.window.end_date;
  const current = new Map<string, Map<string, number>>();
  addToHistory(current, trend.current_points.map((point) => ({ ...point })));

  const timeLabels = [
    ...new Set([
      ...trend.current_points.map((point) => point.time_label),
      ...trend.history_series.flatMap((series) => series.points.map((point) => point.time_label)),
    ]),
  ].sort();

  if (!timeLabels.length) return null;
  const dates = [...history.keys()].sort();
  const marksByLabel = new Map<string, MarkPoint>();
  for (const point of trend.baseline_points) {
    if ((point.significance === "higher" || point.significance === "lower") && point.current_value !== null) {
      marksByLabel.set(point.time_label, {
        coord: [point.time_label, point.current_value],
        value: point.current_value,
        significance: point.significance,
      });
    }
  }

  const series: MeasurementDailyTrendChartOption["series"] = [];
  const currentData = timeLabels.map((timeLabel) => current.get(currentDate)?.get(timeLabel) ?? null);
  if (currentData.some((value) => value !== null)) {
    series.push({
      name: "当前任务",
      type: "line",
      smooth: true,
      showSymbol: true,
      connectNulls: true,
      data: currentData,
      markPoint: marksByLabel.size
        ? { data: [...marksByLabel.values()], symbolSize: 8, itemStyle: { color: "#faad14" } }
        : undefined,
    });
  }
  for (const date of dates) {
    const values = history.get(date) ?? new Map<string, number>();
    series.push({
      name: date,
      type: "line",
      smooth: true,
      showSymbol: false,
      connectNulls: true,
      data: timeLabels.map((timeLabel) => values.get(timeLabel) ?? null),
    });
  }

  const baselineByLabel = new Map(trend.baseline_points.map((point) => [point.time_label, point.baseline_value]));
  series.push({
    name: "历史基线",
    type: "line",
    smooth: true,
    showSymbol: false,
    connectNulls: true,
    lineStyle: { type: "dashed" },
    data: timeLabels.map((timeLabel) => baselineByLabel.get(timeLabel) ?? null),
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

export function selectedTrendPoints(
  points: MeasurementTrendPoint[] | undefined,
  trends: MeasurementTrend[] | undefined,
  selection: TrendSelection,
): MeasurementTrendPoint[] {
  const matched = (trends ?? []).find(
    (trend) => (trend.object_key ?? ALL_OBJECT) === selection.objectKey && periodKey(trend.period_minutes) === selection.periodKey,
  );
  return matched?.points ?? points ?? [];
}
