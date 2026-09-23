import type { MeasurementVersionCandidate, MeasurementVersionComparison } from "../api/http";

type VersionOption = {
  version: string | null;
  version_known: boolean;
};

export function versionCandidateLabel(candidate: VersionOption): string {
  return candidate.version_known && candidate.version ? candidate.version : "版本未知";
}

export function versionSummaryMessage(summary: {
  current_value: number | null;
  baseline_value: number | null;
  absolute_change: number | null;
  change_ratio: number | null;
  direction: "up" | "down" | "flat" | "unknown";
  message: string;
}): string {
  if (summary.direction === "unknown") {
    return "当前或基线缺少有效数据，无法计算版本对比摘要。";
  }
  return summary.message;
}

export function formatVersionDateTime(value: string | null | undefined): string {
  if (!value) return "未知";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "未知" : parsed.toLocaleString();
}

type VersionChartOption = {
  tooltip: { trigger: "axis" };
  legend: { top: number };
  grid: { left: number; right: number; top: number; bottom: number };
  xAxis: { type: "category"; boundaryGap: boolean; data: string[] };
  yAxis: { type: "value"; name?: string; scale: boolean };
  dataZoom: Array<{ type: "inside" | "slider" }>;
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

export function buildVersionCompareChartOption(
  comparison: MeasurementVersionComparison,
  unit?: string | null,
): VersionChartOption | null {
  const timeLabels = [
    ...new Set([
      ...comparison.current_points.map((point) => point.time_label),
      ...comparison.baseline_points.map((point) => point.time_label),
    ]),
  ].sort();
  if (!timeLabels.length) return null;

  const valueByLabel = (points: MeasurementVersionComparison["current_points"]) => {
    const grouped = new Map(points.map((point) => [point.time_label, point.value]));
    return timeLabels.map((label) => grouped.get(label) ?? null);
  };

  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 56, right: 24, top: 48, bottom: 56 },
    xAxis: { type: "category", boundaryGap: false, data: timeLabels },
    yAxis: { type: "value", name: unit || undefined, scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    series: [
      {
        name: `当前版本 ${versionCandidateLabel({ version: comparison.current_version, version_known: comparison.current_version !== null })}`,
        type: "line",
        smooth: true,
        showSymbol: true,
        connectNulls: true,
        data: valueByLabel(comparison.current_points),
      },
      {
        name: `基线版本 ${versionCandidateLabel({
          version: comparison.baseline_version,
          version_known: comparison.baseline_version !== null,
        })}`,
        type: "line",
        smooth: true,
        showSymbol: true,
        connectNulls: true,
        lineStyle: { type: "dashed" },
        data: valueByLabel(comparison.baseline_points),
      },
    ],
  };
}

export function versionCandidateOption(
  candidate: MeasurementVersionCandidate,
  currentVersion: string | null,
): { value: string; label: string; disabled: boolean } {
  const sameKnownVersion =
    currentVersion !== null && candidate.version_known && candidate.version === currentVersion;
  return {
    value: candidate.latest_task_id,
    label: `${versionCandidateLabel(candidate)} · ${candidate.latest_task_id}`,
    disabled: sameKnownVersion,
  };
}
