import assert from "node:assert/strict";
import { test } from "node:test";

import { buildKpiDerivedMetricPayload, validateKpiDerivedMetricDraft } from "./kpiDerivedMetricModel.ts";

const base = {
  name_zh: " 在线成功率 ",
  name_en: "Online Success Rate",
  domain: "call",
  metric_type: "rate",
  semantic_group: "quality",
  display_role: "highlight",
  unit: " % ",
  enabled: true,
  formula_kind: "inverse_ratio",
  numerator: "me_call_failure_count",
  denominator: "me_call_attempts",
  denominator_fallback_inputs: ["me_call_success_count"],
  scale: 100,
} as const;

test("validates representative derived metric fields", () => {
  const errors = validateKpiDerivedMetricDraft({}, false);
  assert.ok(!errors.includes("请输入派生指标 key"));
  assert.ok(errors.includes("请选择分子"));
  assert.ok(errors.includes("请选择分母"));
  assert.ok(errors.includes("请输入大于 0 的倍率"));

  assert.deepEqual(validateKpiDerivedMetricDraft({ ...base, metric_key: "online_success_rate" }, false), []);
  assert.deepEqual(validateKpiDerivedMetricDraft({ ...base, metric_key: "online_success_rate" }, true), []);
  assert.deepEqual(validateKpiDerivedMetricDraft({ ...base, metric_key: "Bad-Key" }, false), [
    "派生指标 key 格式不正确",
  ]);
});

test("builds normalized controlled formula payload", () => {
  const payload = buildKpiDerivedMetricPayload({ ...base, metric_key: "online_success_rate" });
  assert.equal(payload.name_zh, "在线成功率");
  assert.equal(payload.unit, "%");
  assert.deepEqual(payload.formula, {
    kind: "inverse_ratio",
    numerator: "me_call_failure_count",
    denominator: "me_call_attempts",
    denominator_fallback_inputs: ["me_call_success_count"],
    scale: 100,
  });
});
