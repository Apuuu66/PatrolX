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
import {
  buildThresholdFormValuesForMetric,
  formatKpiThresholdSummary,
  groupThresholdsByMetricKey,
} from "./kpiConfigModel.ts";
import type { KpiMetricRuleV4, KpiThresholdV4 } from "../api/http";

const metricRule = {
  metric_key: "me_call_success_rate",
  metric_type: "rate",
  semantic_group: "quality",
  display_role: "highlight",
  unit: "%",
  source_type: "derived",
  aggregation_kind: "success_rate",
  description: null,
  formula: null,
  domain: "call",
  updated_at: "2026-01-01T00:00:00Z",
  rule_config_version: 1,
} as KpiMetricRuleV4;

const threshold = {
  id: 3,
  domain: "call",
  metric_key: "me_call_success_rate",
  label: "呼叫成功率",
  direction: "max",
  unit: "%",
  default: 1,
  periods: { "5": 1.5 },
  updated_at: "2026-01-01T00:00:00Z",
  rule_config_version: 1,
} as KpiThresholdV4;

test("builds threshold form values from the selected metric rule", () => {
  assert.deepEqual(
    buildThresholdFormValuesForMetric(metricRule, undefined, "呼叫成功率"),
    {
      domain: "call",
      metric_key: "me_call_success_rate",
      label: "呼叫成功率",
      direction: "min",
      unit: "%",
      default: undefined,
      periods: {},
    },
  );
});

test("builds threshold form values from an existing threshold", () => {
  assert.deepEqual(buildThresholdFormValuesForMetric(metricRule, threshold, "呼叫成功率"), {
    threshold_id: 3,
    domain: "call",
    metric_key: "me_call_success_rate",
    label: "呼叫成功率",
    direction: "max",
    unit: "%",
    default: 1,
    periods: { "5": 1.5, "15": null, "30": null, "60": null },
  });
});

test("groups thresholds and renders threshold summaries", () => {
  const index = groupThresholdsByMetricKey([threshold]);
  assert.equal(index.get("me_call_success_rate"), threshold);
  assert.equal(formatKpiThresholdSummary(undefined), "未配置");
  assert.equal(formatKpiThresholdSummary(threshold), "上限 ≤ 1%");
  assert.equal(formatKpiThresholdSummary({ ...threshold, direction: "min", default: 99.0 }), "下限 ≥ 99%");
});
