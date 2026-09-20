import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildKpiMetricOptions,
  getKpiMetricDisplayName,
  matchesKpiMetric,
  formatKpiMetricFormula,
  formatKpiMetricNames,
  toKpiRegisteredDomain,
} from "./kpiMetricCatalogModel.ts";
import type { KpiResourceMetric } from "../api/http";

const metric = (overrides: Partial<KpiResourceMetric>): KpiResourceMetric => ({
  key: "me_call_success_rate",
  resource_id: "ME_CALL_SUCCESS_RATE",
  name_zh: "呼叫成功率",
  name_en: "Call Success Rate",
  domain: "call",
  missing_from_base: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const metrics: KpiResourceMetric[] = [
  metric({}),
  metric({
    key: "me_call_attempts",
    resource_id: "ME_CALL_ATTEMPTS",
    name_zh: "呼叫请求次数",
    name_en: "Call Attempts",
    domain: "call",
  }),
  metric({
    key: "me_api_success_rate",
    resource_id: "ME_API_SUCCESS_RATE",
    name_zh: "",
    name_en: "API Success Rate",
    domain: "api",
  }),
];

test("displays the Chinese metric name and falls back when unavailable", () => {
  assert.equal(getKpiMetricDisplayName(metrics, "me_call_success_rate"), "呼叫成功率");
  assert.equal(getKpiMetricDisplayName(metrics, "me_api_success_rate"), "API Success Rate");
  assert.equal(getKpiMetricDisplayName(metrics, "missing_metric"), "missing_metric");
});

test("matches metric display text, resource id and metric key", () => {
  const target = metrics[0];
  assert.equal(matchesKpiMetric(target, "呼叫"), true);
  assert.equal(matchesKpiMetric(target, "success"), true);
  assert.equal(matchesKpiMetric(target, "ME_CALL_SUCCESS"), true);
  assert.equal(matchesKpiMetric(target, "me_call_success_rate"), true);
  assert.equal(matchesKpiMetric(target, "media"), false);
});

test("builds searchable options and can exclude configured derived metrics", () => {
  const options = buildKpiMetricOptions(metrics, {
    excludedKeys: new Set(["me_call_success_rate"]),
  });
  assert.equal(options.length, 2);
  assert.deepEqual(
    options.map((option) => option.value),
    ["me_call_attempts", "me_api_success_rate"],
  );

  const option = options.find((item) => item.value === "me_call_attempts")!;
  assert.equal(option.label, "呼叫请求次数");
  assert.equal(option.search, "呼叫请求次数 Call Attempts me_call_attempts ME_CALL_ATTEMPTS 呼叫请求次数");
});

test("maps resource domains to registered config domains", () => {
  assert.equal(toKpiRegisteredDomain("call"), "call");
  assert.equal(toKpiRegisteredDomain("api"), "api");
  assert.equal(toKpiRegisteredDomain("media"), "media");
  assert.equal(toKpiRegisteredDomain("unclassified"), undefined);
});

test("formats derived formulas with metric names", () => {
  assert.equal(
    formatKpiMetricFormula(
      { numerator: "me_call_success_rate", denominator: "me_call_attempts", scale: 1 },
      metrics,
    ),
    "呼叫成功率 / 呼叫请求次数",
  );
  assert.equal(
    formatKpiMetricFormula(
      { numerator: "me_call_success_rate", denominator: "me_call_attempts", scale: 100 },
      metrics,
    ),
    "呼叫成功率 / 呼叫请求次数 × 100",
  );
  assert.equal(
    formatKpiMetricFormula(
      { numerator: "missing", denominator: "me_call_attempts", scale: 1 },
      metrics,
    ),
    "missing / 呼叫请求次数",
  );
});

test("maps metric key lists to display names", () => {
  assert.deepEqual(
    formatKpiMetricNames(["me_call_success_rate", "missing", "me_api_success_rate"], metrics),
    ["呼叫成功率", "missing", "API Success Rate"],
  );
});
