import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { MeasurementVersionComparison } from "../api/http";

import {
  buildVersionCompareChartOption,
  versionCandidateLabel,
  versionSummaryMessage,
} from "./measurementVersionCompare.ts";

describe("measurement version compare utils", () => {
  const comparison: MeasurementVersionComparison = {
    task_id: "task-current",
    baseline_task_id: "task-baseline",
    rule_code: "kpi.measurement",
    measurement_unit_id: "unit-1",
    metric_resource_id: "metric-1",
    device_id: "device-1",
    object_key: "object-1",
    period_minutes: 15,
    current_version: "V2",
    baseline_version: "V1",
    current_task: { task_id: "task-current", completed_at: null, version: "V2", version_known: true },
    baseline_task: { task_id: "task-baseline", completed_at: null, version: "V1", version_known: true },
    current_points: [
      {
        measured_at: "2026-09-23T10:00:00Z",
        date: "2026-09-23",
        time_label: "10:00",
        value: 130,
        task_id: "task-current",
        source_file: "current.csv",
        line_number: 1,
      },
    ],
    baseline_points: [
      {
        measured_at: "2026-09-22T10:00:00Z",
        date: "2026-09-22",
        time_label: "10:00",
        value: 105,
        task_id: "task-baseline",
        source_file: "baseline.csv",
        line_number: 1,
      },
    ],
    summary: {
      current_value: 130,
      baseline_value: 105,
      absolute_change: 25,
      change_ratio: 25 / 105,
      direction: "up",
      sample_count: 1,
      message: "当前版本均值较基线版本均值上涨 25（23.81%）。",
    },
    match: { by: "device_id", reason: "同设备", device_id: "device-1" },
  };

  it("builds two version curves with task-traceable values", () => {
    const option = buildVersionCompareChartOption(comparison, "呼叫量");

    assert.ok(option);
    assert.equal(option.series.length, 2);
    assert.deepEqual(option.xAxis.data, ["10:00"]);
    assert.deepEqual(option.series[0].name, "当前版本 V2");
    assert.deepEqual(option.series[0].data, [130]);
    assert.deepEqual(option.series[1].name, "基线版本 V1");
    assert.deepEqual(option.series[1].data, [105]);
    assert.deepEqual(
      comparison.current_points.map((point) => point.task_id),
      ["task-current"],
    );
    assert.deepEqual(
      comparison.baseline_points.map((point) => point.task_id),
      ["task-baseline"],
    );
  });

  it("renders unknown versions explicitly", () => {
    assert.equal(versionCandidateLabel({ version: null, version_known: false }), "版本未知");
    assert.equal(versionCandidateLabel({ version: "V1", version_known: true }), "V1");
  });

  it("explains mean change direction", () => {
    assert.match(
      versionSummaryMessage({
        current_value: 130,
        baseline_value: 105,
        absolute_change: 25,
        change_ratio: 25 / 105,
        direction: "up",
        message: "当前版本均值较基线版本均值上涨 25（23.81%）。",
      }),
      /上涨/,
    );
    assert.match(
      versionSummaryMessage({
        current_value: 90,
        baseline_value: 105,
        absolute_change: -15,
        change_ratio: -15 / 105,
        direction: "down",
        message: "当前版本均值较基线版本均值下降 15（14.29%）。",
      }),
      /下降/,
    );
    assert.match(
      versionSummaryMessage({
        current_value: null,
        baseline_value: 105,
        absolute_change: null,
        change_ratio: null,
        direction: "unknown",
        message: "缺少数据",
      }),
      /无法/,
    );
  });
});
