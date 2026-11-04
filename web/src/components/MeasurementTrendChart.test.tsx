import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type MeasurementMetadataMetric, type MeasurementMetricDetail } from "../api/http";
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

function renderCell(
  metric: MeasurementMetadataMetric,
  detail?: { taskId: string; ruleCode: string; unitId: string },
) {
  return render(
    <App>
      <MetricTrendCell
        metric={metric}
        ruleCode={detail?.ruleCode}
        taskId={detail?.taskId}
        unitId={detail?.unitId}
      />
    </App>,
  );
}

describe("MetricTrendCell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

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

  it("摘要只返回趋势点数量时仍提供明确的趋势入口", async () => {
    renderCell(makeMetric({ trend_points: undefined, trend_point_count: 8 }));

    const trigger = await screen.findByRole("button", { name: "查看最大注册用户数完整趋势" });

    expect(trigger.textContent).toBe("查看趋势");
  });

  it("完整趋势加载期间不把已计数但尚未返回的趋势点误判为不足", async () => {
    let resolveDetail: ((detail: MeasurementMetricDetail) => void) | undefined;
    const detailRequest = vi.spyOn(api, "getMeasurementMetricDetail").mockReturnValue(
      new Promise((resolve) => {
        resolveDetail = resolve;
      }),
    );
    const trendPoints = Array.from({ length: 8 }, (_, index) => ({
      time: `2026-09-20T${String(index + 1).padStart(2, "0")}:00:00`,
      object_key: "pod-a",
      period_minutes: 60,
      value: 2000 + index * 10,
    }));

    renderCell(makeMetric({ trend_points: undefined, trend_point_count: 8 }), {
      taskId: "task-kpi",
      ruleCode: "kpi.measurement_units",
      unitId: "MU_MAX_USERS",
    });
    fireEvent.click(await screen.findByRole("button", { name: "查看最大注册用户数完整趋势" }));

    expect(await screen.findByText("正在加载完整明细…")).toBeTruthy();
    expect(screen.queryByText("趋势点不足，无法判断趋势")).toBeNull();
    await waitFor(() => expect(detailRequest).toHaveBeenCalledTimes(1));

    expect(resolveDetail).toBeDefined();
    await act(async () => {
      resolveDetail?.({
        task_id: "task-kpi",
        rule_code: "kpi.measurement_units",
        measurement_unit_id: "MU_MAX_USERS",
        metric: makeMetric({ trend_points: trendPoints, trend_point_count: 8 }),
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId("measurement-single-trend-chart")).toBeTruthy();
    });
    expect(screen.queryByText("趋势点不足，无法判断趋势")).toBeNull();
  });

  it("单任务趋势首屏使用轻量图表，不加载 AntD Table", async () => {
    const trendPoints = Array.from({ length: 8 }, (_, index) => ({
      time: `2026-09-20T${String(index + 1).padStart(2, "0")}:00:00`,
      object_key: "pod-a",
      period_minutes: 60,
      value: 2000 + index * 10,
    }));
    const { container } = renderCell(makeMetric({ trend_points: trendPoints }));

    fireEvent.click(await screen.findByRole("button", { name: "查看最大注册用户数完整趋势" }));

    expect(await screen.findByTestId("measurement-single-trend-chart")).toBeTruthy();
    expect(container.querySelector(".ant-table")).toBeNull();
  });
});
