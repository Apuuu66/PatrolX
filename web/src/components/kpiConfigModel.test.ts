import assert from "node:assert/strict";
import { test } from "node:test";
import { buildMetricRulePayload, buildThresholdPayload, KPI_AGGREGATION_OPTIONS } from "./kpiConfigModel.ts";

test("builds raw metric rule payload with simple aggregations", () => {
  assert.deepEqual(
    buildMetricRulePayload(
      " me_1 ",
      {
        metric_type: "count",
        semantic_group: "traffic",
        display_role: "context",
        unit: " 次 ",
        source_type: "raw",
        aggregation_kind: "median",
        description: " ",
      },
      "alice",
    ),
    {
      metric_type: "count",
      semantic_group: "traffic",
      display_role: "context",
      unit: "次",
      source_type: "raw",
      aggregation_kind: "median",
      description: null,
      operator: "alice",
      formula: null,
    },
  );
  assert.deepEqual(
    KPI_AGGREGATION_OPTIONS.map((item) => item.value),
    ["sum", "min", "max", "mean", "count", "median", "stddev", "success_rate"],
  );
});

test("builds controlled success rate formula payload", () => {
  assert.deepEqual(
    buildMetricRulePayload(
      "me_call_success_rate",
      {
        metric_type: "rate",
        semantic_group: "quality",
        display_role: "highlight",
        unit: "%",
        source_type: "derived",
        aggregation_kind: "success_rate",
        numerator: " me_call_success_count ",
        denominator: " me_call_attempts ",
        denominator_fallback_inputs: " a , , b ",
        scale: 100,
      },
      "bob",
    ),
    {
      metric_type: "rate",
      semantic_group: "quality",
      display_role: "highlight",
      unit: "%",
      source_type: "derived",
      aggregation_kind: "success_rate",
      description: null,
      operator: "bob",
      formula: {
        kind: "ratio",
        numerator: "me_call_success_count",
        denominator: "me_call_attempts",
        denominator_fallback_inputs: ["a", "b"],
        scale: 100,
      },
    },
  );
});

test("builds threshold payload with non-empty periods only", () => {
  assert.deepEqual(
    buildThresholdPayload(
      {
        domain: "call",
        metric_key: " me_call_success_rate ",
        label: " 成功率 ",
        direction: "min",
        unit: "%",
        default: 99,
        periods: { "5": 98, "15": null, "30": undefined, "60": 95 },
      },
      "carol",
    ),
    {
      domain: "call",
      metric_key: "me_call_success_rate",
      label: "成功率",
      direction: "min",
      unit: "%",
      default: 99,
      periods: { "5": 98, "60": 95 },
      operator: "carol",
    },
  );
});
