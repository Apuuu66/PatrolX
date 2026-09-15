import assert from "node:assert/strict";
import test from "node:test";

import { getKpiMetricDetailView, getKpiMetricTrendView } from "./kpiCatalogModel.ts";

const item = {
  definition: {
    key: "call_success_rate",
    name_zh: "呼叫成功率",
    name_en: "Call Success Rate",
    aliases: [{ language: "zh", value: "呼叫成功率" }],
    metric_type: "rate",
    semantic_group: "quality",
    display_role: "highlight",
    unit: "%",
    source_type: "derived",
    aggregation: { kind: "ratio_from_inputs" },
    formula: { kind: "ratio", numerator: "call_success_count", denominator: "call_attempts", scale: 100 },
  },
  result: {
    key: "call_success_rate",
    main_value: 90,
    value_available: true,
    display_status: "fail",
    unit: "%",
    aggregation: "ratio_from_inputs",
    threshold: { direction: "min", default: 99, unit: "%" },
    breach_count: 1,
    series: [
      { start_at: "2026-09-01T02:00:00Z", period_minutes: 5, value: 90, status: "fail" },
      { start_at: "2026-09-01T02:05:00Z", period_minutes: 5, value: 99.2, status: "pass" },
    ],
    source_files: ["kpi/kpi-call-5.csv"],
    provenance: {
      formula: "call_success_count / call_attempts * 100",
      inputs: [
        { key: "call_success_count", value: 900, aggregation: "sum" },
        { key: "call_attempts", value: 1000, aggregation: "sum" },
      ],
      missing_inputs: [],
      direct_cross_reference: [
        { source_name: "呼叫成功率", source_file: "kpi/kpi-call-5.csv", value: 99.9 },
      ],
      denominator_zero: false,
      fallback_used: false,
    },
  },
};

test("explains definition, formula, inputs, cross reference and threshold", () => {
  const view = getKpiMetricDetailView(item);
  assert.equal(view.title, "呼叫成功率");
  assert.equal(view.description.includes("Call Success Rate"), true);
  assert.equal(view.formulaText, "call_success_count / call_attempts * 100");
  assert.deepEqual(view.inputRows.map((row) => [row.key, row.valueText]), [
    ["call_success_count", "900"],
    ["call_attempts", "1000"],
  ]);
  assert.deepEqual(view.crossReferenceRows.map((row) => [row.sourceName, row.valueText]), [
    ["呼叫成功率", "99.9"],
  ]);
  assert.equal(view.thresholdText, "阈值 ≥ 99%");
  assert.equal(view.unavailableReasonText, "-");
});

test("explains unavailable formula inputs", () => {
  const unavailable = getKpiMetricDetailView({
    definition: item.definition,
    result: {
      ...item.result,
      main_value: null,
      value_available: false,
      unavailable_reason: "missing_input: call_attempts",
      provenance: {
        formula: "call_success_count / call_attempts * 100",
        inputs: [],
        missing_inputs: ["call_attempts"],
        direct_cross_reference: [],
        denominator_zero: false,
        fallback_used: false,
      },
    },
  });
  assert.equal(unavailable.inputRows.length, 0);
  assert.equal(unavailable.unavailableReasonText, "缺失输入：call_attempts");
});

test("builds trend points and unavailable reason", () => {
  const trend = getKpiMetricTrendView(item.result);
  assert.deepEqual(trend.points.map((point) => point.value), [90, 99.2]);
  assert.equal(trend.points[0]?.x, "2026-09-01T02:00:00Z");
  assert.equal(trend.emptyText, "");
  assert.equal(getKpiMetricTrendView({ ...item.result, series: [] }).emptyText, "暂无可用序列");
});
