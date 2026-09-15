import assert from "node:assert/strict";
import test from "node:test";

import { buildKpiMetricGroups, filterKpiMetricGroups } from "./kpiCatalogModel.ts";

const metadata = {
  version: 2,
  domain: "call",
  config_source: "deploy/config/kpi",
  input_timezone: "Asia/Shanghai",
  metric_catalog: [
    {
      key: "call_success_rate",
      name_zh: "呼叫成功率",
      name_en: "Call Success Rate",
      aliases: [{ language: "zh", value: "接通率" }],
      metric_type: "rate",
      semantic_group: "quality",
      display_role: "highlight",
      unit: "%",
      source_type: "derived",
      aggregation: { kind: "ratio_from_inputs" },
    },
    {
      key: "call_attempts",
      name_zh: "呼叫请求次数",
      name_en: "Call Attempts",
      aliases: [],
      metric_type: "count",
      semantic_group: "traffic",
      display_role: "context",
      unit: "次",
      source_type: "raw",
      aggregation: { kind: "sum" },
    },
    {
      key: "stat_peak",
      name_zh: "统计峰值",
      name_en: "Stat Peak",
      aliases: [],
      metric_type: "capacity",
      semantic_group: "capacity",
      display_role: "catalog",
      unit: "个",
      source_type: "raw",
      aggregation: { kind: "max" },
    },
  ],
  kpi_results: [
    {
      key: "call_success_rate",
      main_value: 98.8,
      value_available: true,
      display_status: "fail",
      unit: "%",
      aggregation: "ratio_from_inputs",
      threshold: { direction: "min", default: 99 },
      breach_count: 3,
      series: [],
      source_files: [],
      provenance: {},
    },
    {
      key: "call_attempts",
      main_value: 120,
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
    {
      key: "stat_peak",
      main_value: null,
      value_available: false,
      display_status: "unavailable",
      unit: "个",
      aggregation: "max",
      threshold: null,
      breach_count: 0,
      series: [],
      source_files: [],
      provenance: {},
    },
  ],
  unclassified_metrics: [],
  kpi_files: [],
} as const;

test("groups catalog metrics by semantic group", () => {
  const groups = buildKpiMetricGroups(metadata);
  assert.deepEqual(
    groups.map((group) => [group.key, group.items.length]),
    [
      ["quality", 1],
      ["traffic", 1],
      ["capacity", 1],
    ],
  );
  assert.equal(groups[0]?.items[0]?.definition.name_zh, "呼叫成功率");
});

test("filters by display status and threshold availability", () => {
  const failOnly = filterKpiMetricGroups(metadata, { status: "fail" });
  assert.deepEqual(failOnly.flatMap((group) => group.items.map((item) => item.definition.key)), [
    "call_success_rate",
  ]);

  const withThreshold = filterKpiMetricGroups(metadata, { threshold: "with" });
  assert.deepEqual(withThreshold.flatMap((group) => group.items.map((item) => item.definition.key)), [
    "call_success_rate",
  ]);

  const withoutThreshold = filterKpiMetricGroups(metadata, { threshold: "without" });
  assert.deepEqual(withoutThreshold.flatMap((group) => group.items.map((item) => item.definition.key)), [
    "call_attempts",
    "stat_peak",
  ]);
});

test("searches Chinese, English, stable key and aliases", () => {
  for (const query of ["成功率", "success", "call_success_rate", "接通率"]) {
    const result = filterKpiMetricGroups(metadata, { query });
    assert.deepEqual(
      result.flatMap((group) => group.items.map((item) => item.definition.key)),
      ["call_success_rate"],
      `query=${query}`,
    );
  }
});
