import { fireEvent, render, screen } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it } from "vitest";

import type { MeasurementMetadataMetric } from "../api/http";
import { MetricTrendCell } from "./MeasurementTrendChart";

function makeMetric(overrides: Partial<MeasurementMetadataMetric> = {}): MeasurementMetadataMetric {
  return {
    metric_resource_id: "ME_MAX_USERS",
    metric_resource_name_zh: "最大注册用户数",
    raw_source_name: "最大注册用户数(户)",
    base_source_name: "最大注册用户数",
    display_unit: "户",
    read_status: "ok",
    value_pattern: "normal",
    trend_label: "cannot_determine",
    trend_signal: "none",
    trend_reason: "insufficient_points",
    trend_points: [
      {
        time: "2026-09-20T10:00:00",
        object_key: "pod-a",
        period_minutes: 15,
        value: 2048,
        source_rows: [
          { source_file: "ne333_Call_Statistics_15_0_202609201000.csv", line_number: 2, value: "2048" },
        ],
      },
    ],
    ...overrides,
  };
}

function renderCell(metric: MeasurementMetadataMetric) {
  return render(
    <App>
      <MetricTrendCell metric={metric} />
    </App>,
  );
}

describe("MetricTrendCell", () => {
  it("单点指标仍保留可点击趋势入口并展示时间点明细", async () => {
    renderCell(makeMetric());

    fireEvent.click(await screen.findByRole("button", { name: "查看最大注册用户数完整趋势" }));

    expect(await screen.findByText("趋势点不足，无法判断趋势")).toBeTruthy();
    expect(screen.getByText("本任务内只有 1 个时间点，至少需要 2 个时间点才能判断趋势")).toBeTruthy();
    expect(screen.getByText("时间点明细")).toBeTruthy();
    expect(screen.getByText("2026-09-20 10:00:00")).toBeTruthy();
    expect(screen.getByText("2048 户")).toBeTruthy();
    expect(screen.getByText("ne333_Call_Statistics_15_0_202609201000.csv:2")).toBeTruthy();
  });

  it("缺少时间点时仍可点击并解释无法判断趋势的原因", async () => {
    renderCell(makeMetric({ trend_points: [], trend_reason: "no_time_series" }));

    fireEvent.click(await screen.findByRole("button", { name: "查看最大注册用户数完整趋势" }));

    expect(await screen.findByText("趋势点不足，无法判断趋势")).toBeTruthy();
    expect(screen.getByText("未找到可用时间序列，测量时间缺失或格式非法")).toBeTruthy();
  });
});
