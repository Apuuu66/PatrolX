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
        {
          key: "call_success_count",
          value: 900,
          aggregation: "sum",
          source_names: ["呼叫请求成功次数(次)"],
        },
        {
          key: "call_attempts",
          value: 1000,
          aggregation: "sum",
          source_names: ["呼叫请求次数(次)"],
        },
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
  assert.deepEqual(view.inputRows.map((row) => row.sourceNamesText), [
    "呼叫请求成功次数(次)",
    "呼叫请求次数(次)",
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

import { buildKpiRecordQuery, getKpiRecordPageInfo, getKpiRecordRows } from "./kpiRecordTableModel.ts";

const records = [
  {
    metric_key: "call_success_rate",
    metric_name_zh: "呼叫成功率",
    source_file: "kpi/kpi-call-5.csv",
    line_number: 4,
    period_minutes: 5,
    start_at: "2026-09-14T02:00:00Z",
    end_at: "2026-09-14T02:05:00Z",
    value: 90,
    status: "fail",
    errors: [],
  },
  {
    metric_key: "call_success_rate",
    metric_name_zh: "呼叫成功率",
    source_file: "kpi/kpi-call-5.csv",
    line_number: 5,
    period_minutes: 5,
    start_at: "2026-09-14T02:05:00Z",
    end_at: "2026-09-14T02:10:00Z",
    value: null,
    status: "unavailable",
    errors: [{ code: "invalid_value", message: "值非法" }],
  },
] as never[];

test("builds paginated KPI record queries with exact filters", () => {
  assert.deepEqual(buildKpiRecordQuery("call_success_rate", {}, 1, 50), {
    metric_key: "call_success_rate",
    page: 1,
    page_size: 50,
  });
  assert.deepEqual(
    buildKpiRecordQuery("call_success_rate", {
      sourceFile: "kpi/kpi-call-5.csv",
      periodMinutes: 5,
      status: "fail",
    }, 2, 200),
    {
      metric_key: "call_success_rate",
      source_file: "kpi/kpi-call-5.csv",
      period_minutes: 5,
      status: "fail",
      page: 2,
      page_size: 200,
    },
  );
  assert.equal(buildKpiRecordQuery("call_success_rate", {}, -1, 999).page_size, 200);
});

test("projects UTC record rows and errors", () => {
  const rows = getKpiRecordRows(records);
  assert.equal(rows[0]?.timeText, "2026-09-14 02:00:00 UTC — 2026-09-14 02:05:00 UTC");
  assert.deepEqual(rows.map((row) => [row.statusLabel, row.statusColor]), [
    ["失败", "#ff4d4f"],
    ["不可用", "#8c8c8c"],
  ]);
  assert.equal(rows[1]?.errorsText, "值非法");
});

test("describes record pages and empty state", () => {
  assert.equal(getKpiRecordPageInfo(null), "");
  assert.equal(getKpiRecordPageInfo({ total: 0, page: 1, page_size: 50, items: [] }), "共 0 条");
  assert.equal(getKpiRecordPageInfo({ total: 8, page: 3, page_size: 3, items: [] as never[] }), "7-7 / 共 8 条");
  assert.equal(getKpiRecordRows([]).length, 0);
});

test("creates unique keys for duplicated cross-reference values", () => {
  const duplicatedRow = {
    source_name: "呼叫请求成功次数",
    source_file: "kpi/call.csv",
    value: 100,
  };
  const view = getKpiMetricDetailView({
    ...item,
    result: {
      ...item.result,
      provenance: {
        ...item.result.provenance,
        direct_cross_reference: [duplicatedRow, duplicatedRow],
      },
    },
  });
  assert.equal(view.crossReferenceRows.length, 2);
  assert.notEqual(view.crossReferenceRows[0]?.key, view.crossReferenceRows[1]?.key);
});

test("sorts trend points by measurement time", () => {
  const trend = getKpiMetricTrendView({
    ...item.result,
    series: [
      { start_at: "2026-09-01T02:05:00Z", period_minutes: 15, value: 99.2, status: "pass" },
      { start_at: "2026-09-01T02:00:00Z", period_minutes: 15, value: 90, status: "fail" },
    ],
  });
  assert.deepEqual(trend.points.map((point) => point.value), [90, 99.2]);
});
