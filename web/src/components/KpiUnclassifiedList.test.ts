import assert from "node:assert/strict";
import test from "node:test";

import { buildKpiUnclassifiedRows } from "./kpiCatalogModel.ts";

const metadata = {
  version: 2,
  domain: "call",
  metric_catalog: [],
  kpi_results: [],
  kpi_files: [],
  unclassified_metrics: [
    {
      source_name: "自定义业务指标",
      source_files: ["kpi/kpi-call-15.csv"],
      record_count: 3,
      sample_values: [88, 90, "bad"],
      reason: "metric_not_registered",
    },
    {
      source_name: "legacy_peak",
      source_files: ["kpi/kpi-call-15.csv", "kpi/kpi-call-30.csv"],
      record_count: 0,
      sample_values: [],
      reason: "metric_not_registered",
    },
  ],
} as const;

test("builds unclassified rows with source and sample evidence", () => {
  const rows = buildKpiUnclassifiedRows(metadata);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], {
    sourceName: "自定义业务指标",
    sourceFiles: "kpi/kpi-call-15.csv",
    recordCount: 3,
    sampleValues: "88, 90, bad",
    reason: "未登记指标",
  });
  assert.equal(rows[1]?.recordCount, 0);
  assert.equal(rows[1]?.sourceFiles, "kpi/kpi-call-15.csv, kpi/kpi-call-30.csv");
  assert.equal(rows[1]?.sampleValues, "-");
});

test("searches unclassified source name and files", () => {
  assert.deepEqual(
    buildKpiUnclassifiedRows(metadata, { query: "自定义" }).map((row) => row.sourceName),
    ["自定义业务指标"],
  );
  assert.deepEqual(
    buildKpiUnclassifiedRows(metadata, { query: "kpi-call-30" }).map((row) => row.sourceName),
    ["legacy_peak"],
  );
});

test("returns an explicit empty state", () => {
  const empty = buildKpiUnclassifiedRows({ ...metadata, unclassified_metrics: [] });
  assert.deepEqual(empty, []);
  assert.equal(buildKpiUnclassifiedRows({ ...metadata, unclassified_metrics: [] }, { query: "x" }).length, 0);
  assert.equal(buildKpiUnclassifiedRows(null).length, 0);
});

test("hides the unclassified section when no metrics are unclassified", async () => {
  const { hasKpiUnclassifiedMetrics } = await import("./kpiCatalogModel.ts");
  assert.equal(hasKpiUnclassifiedMetrics({ ...metadata, unclassified_metrics: [] }), false);
  assert.equal(hasKpiUnclassifiedMetrics({ ...metadata, unclassified_metrics: undefined }), false);
  assert.equal(hasKpiUnclassifiedMetrics(null), false);
  assert.equal(hasKpiUnclassifiedMetrics(metadata), true);
});
