import assert from "node:assert/strict";
import test from "node:test";
import type { MeasurementHistoryTrend, MeasurementTrend } from "../api/http";
import {
  buildHistoryTrendChartOption,
  buildTrendSelectionOptions,
  defaultTrendSelection,
  historyMatchAlert,
  historyPeriodLabel,
} from "./measurementHistory.ts";

const trendA: MeasurementTrend = {
  label: "stable",
  signal: "none",
  object_key: "pod-a",
  period_minutes: 15,
  points: [],
};

const trendB: MeasurementTrend = {
  label: "stable",
  signal: "none",
  object_key: "pod-b",
  period_minutes: null,
  points: [],
};

test("buildTrendSelectionOptions 提供去重对象和周期选项", () => {
  const options = buildTrendSelectionOptions([trendA, trendB, { ...trendA, points: [] }]);
  assert.deepEqual(options.objectOptions, [
    { value: "pod-a", label: "pod-a" },
    { value: "pod-b", label: "pod-b" },
  ]);
  assert.deepEqual(options.periodOptions, [
    { value: "15", label: "15 分钟", periodMinutes: 15 },
    { value: "none", label: "未识别周期", periodMinutes: null },
  ]);
});

test("defaultTrendSelection 优先选择 15 分钟周期", () => {
  const selection = defaultTrendSelection([
    { ...trendB, period_minutes: 5 },
    trendA,
  ]);
  assert.deepEqual(selection, { objectKey: "pod-a", periodKey: "15" });
});

test("historyMatchAlert 映射降级原因", () => {
  assert.equal(historyMatchAlert({ status: "no_history", reason_code: null, message: "" }).description, "当前设备还没有可对比的历史任务");
  assert.equal(
    historyMatchAlert({
      status: "no_history",
      reason_code: "history_time_outside_window",
      message: "同设备有 1 个历史任务，但数据时间不在当前 7 天窗口（2026-09-04 ~ 2026-09-10）；最近为 2026-09-01。",
    }).description,
    "同设备有 1 个历史任务，但数据时间不在当前 7 天窗口（2026-09-04 ~ 2026-09-10）；最近为 2026-09-01。",
  );
  assert.equal(historyMatchAlert({ status: "degraded", reason_code: "device_id_missing", message: "" }).description, "当前任务未填写设备 ID，无法匹配历史任务");
  assert.equal(historyMatchAlert({ status: "degraded", reason_code: "history_index_missing", message: "" }).description, "历史索引缺失，请先重跑当前任务生成历史索引");
});

test("historyMatchAlert 映射同设备候选任务未匹配原因", () => {
  const descriptions: Record<string, string> = {
    history_candidate_not_completed: "同设备候选任务未完成或缺少完成时间",
    history_candidate_after_current: "同设备候选任务完成时间晚于当前任务",
    history_candidate_index_missing: "同设备候选任务历史索引缺失",
    history_candidate_index_empty: "同设备候选任务历史索引为空或无效",
    history_candidate_unit_or_metric_missing: "同设备候选任务没有该测量单元或指标",
    history_candidate_object_or_period_mismatch: "同设备候选任务对象或周期不一致",
    history_candidate_mismatch: "同设备候选任务的测量单元、指标、对象、周期或时间窗口不一致",
  };
  for (const [reason_code, description] of Object.entries(descriptions)) {
    assert.equal(
      historyMatchAlert({ status: "no_history", reason_code, message: "" }).description,
      description,
    );
  }
  assert.equal(historyMatchAlert({ status: "degraded", reason_code: "unknown", message: "后端说明" }).description, "后端说明");
});

test("historyPeriodLabel 展示可读周期", () => {
  assert.equal(historyPeriodLabel(15), "15 分钟");
  assert.equal(historyPeriodLabel(null), "未识别周期");
});

test("buildHistoryTrendChartOption 按时刻生成当前任务、历史和基线曲线", () => {
  const payload = {
    current_points: [
      { date: "2026-09-10", time_label: "10:00", value: 30, measured_at: "2026-09-10T10:00:00Z", task_id: "current", source_file: "a.csv", line_number: 1 },
    ],
    history_series: [
      {
        date: "2026-09-09",
        source_task_ids: ["old"],
        points: [
          { date: "2026-09-09", time_label: "10:00", value: 10, measured_at: "2026-09-09T10:00:00Z", task_id: "old", source_file: "a.csv", line_number: 1 },
          { date: "2026-09-09", time_label: "11:00", value: 20, measured_at: "2026-09-09T11:00:00Z", task_id: "old", source_file: "a.csv", line_number: 2 },
        ],
      },
    ],
    baseline_points: [
      { time_label: "10:00", baseline_value: 10, current_value: 30, deviation: 20, deviation_ratio: 2, sample_count: 1, date_count: 1, significance: "higher" },
    ],
  } as unknown as MeasurementHistoryTrend;

  const option = buildHistoryTrendChartOption(payload);
  assert.deepEqual(option?.xAxis.data, ["10:00", "11:00"]);
  assert.deepEqual(option?.series.find((item) => item.name === "当前任务")?.data, [30, null]);
  assert.deepEqual(option?.series.find((item) => item.name === "2026-09-09")?.data, [10, 20]);
  assert.deepEqual(option?.series.find((item) => item.name === "历史基线")?.data, [10, null]);
  const markData = option?.series.find((item) => item.name === "当前任务")?.markPoint?.data;
  assert.equal(markData?.length, 1);
  assert.deepEqual(markData?.[0]?.coord, ["10:00", 30]);
});
