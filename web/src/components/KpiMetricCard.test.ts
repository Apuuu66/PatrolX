import assert from "node:assert/strict";
import test from "node:test";

import { getKpiMetricCardView } from "./kpiCatalogModel.ts";

const base = {
  key: "call_success_rate",
  name_zh: "呼叫成功率",
  name_en: "Call Success Rate",
  aliases: [],
  metric_type: "rate",
  semantic_group: "quality",
  display_role: "highlight",
  unit: "%",
  source_type: "derived",
  aggregation: { kind: "ratio_from_inputs" },
} as const;

test("formats main value and threshold direction", () => {
  const view = getKpiMetricCardView({
    definition: base,
    result: {
      key: base.key,
      main_value: 98.8,
      value_available: true,
      display_status: "fail",
      unit: "%",
      aggregation: "ratio_from_inputs",
      threshold: { direction: "min", default: 99 },
      breach_count: 1,
      series: [],
      source_files: [],
      provenance: {},
    },
  });

  assert.equal(view.mainValueText, "98.8");
  assert.equal(view.unitText, "%");
  assert.equal(view.thresholdText, "阈值 ≥ 99%");
  assert.equal(view.statusColor, "#ff4d4f");
});

test("marks unavailable and neutral metrics", () => {
  const unavailable = getKpiMetricCardView({
    definition: base,
    result: {
      key: base.key,
      main_value: null,
      value_available: false,
      unavailable_reason: "公式必要输入缺失: call_attempts",
      display_status: "unavailable",
      unit: "%",
      aggregation: "ratio_from_inputs",
      threshold: null,
      breach_count: 0,
      series: [],
      source_files: [],
      provenance: {},
    },
  });
  assert.equal(unavailable.mainValueText, "-");
  assert.equal(unavailable.statusLabel, "不可用");
  assert.equal(unavailable.statusColor, "#8c8c8c");

  const neutral = getKpiMetricCardView({
    definition: base,
    result: {
      key: base.key,
      main_value: 123,
      value_available: true,
      display_status: "neutral",
      unit: "次",
      aggregation: "sum",
      threshold: null,
      breach_count: 0,
      series: [],
      source_files: [],
      provenance: {},
    },
  });
  assert.equal(neutral.mainValueText, "123");
  assert.equal(neutral.statusLabel, "中性");
  assert.equal(neutral.statusColor, "#8c8c8c");
  assert.equal(neutral.thresholdText, "无阈值");
});

test("limits displayed fractional values to three decimal places", () => {
  const view = getKpiMetricCardView({
    definition: base,
    result: {
      key: base.key,
      main_value: 99.44444444444444,
      value_available: true,
      display_status: "pass",
      unit: "%",
      aggregation: "ratio_from_inputs",
      threshold: { direction: "min", default: 99 },
      breach_count: 0,
      series: [],
      source_files: [],
      provenance: {},
    },
  });
  assert.equal(view.mainValueText, "99.444");
});
