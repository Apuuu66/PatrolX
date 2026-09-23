import assert from "node:assert/strict";
import test from "node:test";
import { buildTrendChartOption } from "./measurementTrend.ts";

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
