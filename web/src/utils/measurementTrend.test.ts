import assert from "node:assert/strict";
import test from "node:test";
import { analyzeTrendComparison, buildDailyTrendChartOption, buildTrendChartOption } from "./measurementTrend.ts";

test("buildTrendChartOption 生成完整趋势曲线配置", () => {
  const option = buildTrendChartOption(
    [
      { time: "2026-01-01 00:00:00", value: 1 },
      { time: "2026-01-01 00:15:00", value: 3 },
      { time: "2026-01-01 00:30:00", value: 2 },
    ],
    "CPU使用率",
    "%",
  );

  assert.deepEqual(option.xAxis, {
    type: "category",
    boundaryGap: false,
    data: ["2026-01-01 00:00:00", "2026-01-01 00:15:00", "2026-01-01 00:30:00"],
  });
  assert.equal(option.yAxis.name, "%");
  assert.equal(option.yAxis.scale, true);
  assert.equal(option.series[0]?.name, "CPU使用率");
  assert.deepEqual(option.series[0]?.data, [1, 3, 2]);
  assert.equal(option.tooltip.trigger, "axis");
});

test("buildTrendChartOption 对不足两个趋势点返回空配置", () => {
  assert.equal(buildTrendChartOption([{ time: "2026-01-01 00:00:00", value: 1 }], "CPU使用率"), null);
});

test("analyzeTrendComparison 在多天数据下使用同时刻历史基线", () => {
  const comparison = analyzeTrendComparison([
    { time: "2026-01-01 10:00:00", value: 10 },
    { time: "2026-01-01 11:00:00", value: 20 },
    { time: "2026-01-02 10:00:00", value: 30 },
    { time: "2026-01-02 11:00:00", value: 60 },
  ]);

  assert.equal(comparison.mode, "multi_day");
  assert.equal(comparison.latestTime, "2026-01-02 11:00:00");
  assert.equal(comparison.latestValue, 60);
  assert.equal(comparison.baselineValue, 20);
  assert.equal(comparison.deviation, 40);
  assert.equal(comparison.deviationRatio, 2);
  assert.match(comparison.message, /同时刻/);
});

test("analyzeTrendComparison 在单日数据下使用短期基线", () => {
  const comparison = analyzeTrendComparison([
    { time: "2026-01-01 10:00:00", value: 10 },
    { time: "2026-01-01 10:15:00", value: 12 },
    { time: "2026-01-01 10:30:00", value: 11 },
    { time: "2026-01-01 10:45:00", value: 30 },
  ]);

  assert.equal(comparison.mode, "short_window");
  assert.equal(comparison.latestValue, 30);
  assert.equal(comparison.baselineValue, 11);
  assert.equal(comparison.deviation, 19);
  assert.equal(comparison.deviationRatio, 19 / 11);
  assert.match(comparison.message, /短期突变/);
});

test("analyzeTrendComparison 对点数不足返回 insufficient", () => {
  const comparison = analyzeTrendComparison([{ time: "2026-01-01 10:00:00", value: 1 }]);
  assert.equal(comparison.mode, "insufficient");
  assert.equal(comparison.baselineValue, null);
});

test("buildDailyTrendChartOption 按时刻对齐每日曲线", () => {
  const option = buildDailyTrendChartOption(
    [
      { time: "2026-01-01 10:00:00", value: 10 },
      { time: "2026-01-01 11:00:00", value: 20 },
      { time: "2026-01-02 10:00:00", value: 30 },
      { time: "2026-01-02 11:00:00", value: 60 },
    ],
    "CPU使用率",
  );

  assert.deepEqual(option?.xAxis.data, ["10:00", "11:00"]);
  assert.deepEqual(option?.series.find((item) => item.name === "2026-01-01")?.data, [10, 20]);
  assert.deepEqual(option?.series.find((item) => item.name === "2026-01-02")?.data, [30, 60]);
  assert.deepEqual(option?.series.find((item) => item.name === "历史基线")?.data, [10, 20]);
});
