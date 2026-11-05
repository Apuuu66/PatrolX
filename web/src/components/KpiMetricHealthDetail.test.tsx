import { render, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type KpiDailyHealthMetricDetail } from "../api/http";
import { KpiMetricHealthDetail } from "./KpiMetricHealthDetail";

vi.mock("../lib/echarts", () => ({
  default: {
    init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
  },
}));

const detail: KpiDailyHealthMetricDetail = {
  task_id: "task-kpi",
  rule_code: "kpi.measurement_units",
  measurement_unit_id: "MU_CALL",
  metric_resource_id: "ME_RATE",
  metric: {
    name_zh: "呼叫成功率",
    role: "derived",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    daily_aggregation: "formula",
    formula: "numerator_sum / denominator_sum * 100",
    current_status: "fail",
    trend_status: "worsened",
    current_threshold: {
      direction: "higher_better",
      warning_threshold: 98,
      critical_threshold: 95,
      source: "custom",
    },
    change_threshold: { value: 0.2, unit: "pp", source: "default" },
    consistency: { status: "within_tolerance", tolerance_pp: 0.2, difference_pp: 0.03 },
  },
  groups: [
    {
      object_key: "pod-a",
      period_minutes: 15,
      today: {
        date: "2026-11-05",
        value: 45.5,
        numerator: 91,
        denominator: 200,
        valid_count: 2,
        first_measured_at: "2026-11-05T08:00:00+08:00",
        last_measured_at: "2026-11-05T08:15:00+08:00",
        status: "ok",
      },
      yesterday: {
        date: "2026-11-04",
        value: 99,
        numerator: 99,
        denominator: 100,
        valid_count: 1,
        first_measured_at: "2026-11-04T08:00:00+08:00",
        last_measured_at: "2026-11-04T08:00:00+08:00",
        status: "ok",
      },
      current_status: "fail",
      trend_status: "worsened",
      reason: "低于昨日 53.5pp",
      source_files: ["call.csv"],
    },
  ],
  seven_day_trend: [
    { date: "2026-10-30", value: null, valid_count: 0, status: "no_data" },
    { date: "2026-10-31", value: null, valid_count: 0, status: "no_data" },
    { date: "2026-11-01", value: 98.4, numerator: 984, denominator: 1000, valid_count: 4, status: "ok" },
    { date: "2026-11-02", value: 98.1, numerator: 981, denominator: 1000, valid_count: 4, status: "ok" },
    { date: "2026-11-03", value: 99, numerator: 99, denominator: 100, valid_count: 1, status: "ok" },
    { date: "2026-11-04", value: 99, numerator: 99, denominator: 100, valid_count: 1, status: "ok" },
    { date: "2026-11-05", value: 45.5, numerator: 91, denominator: 200, valid_count: 2, status: "ok" },
  ],
  legacy_fallback: null,
};

describe("KpiMetricHealthDetail", () => {
  afterEach(() => {
    vi.mocked(api.getKpiDailyHealthMetric).mockRestore();
  });

  it("展示成功率分子分母、公式、一致性检查和对象周期证据", async () => {
    vi.spyOn(api, "getKpiDailyHealthMetric").mockResolvedValue(detail);
    render(
      <App>
        <KpiMetricHealthDetail
          taskId="task-kpi"
          ruleCode="kpi.measurement_units"
          measurementUnitId="MU_CALL"
          metricResourceId="ME_RATE"
        />
      </App>,
    );

    await waitFor(() => expect(screen.getByText("呼叫成功率")).toBeDefined());
    expect(screen.getByText("numerator_sum / denominator_sum * 100")).toBeDefined();
    expect(screen.getByText("91 / 200 = 45.5%")).toBeDefined();
    expect(screen.getByText("99 / 100 = 99.0%")).toBeDefined();
    expect(screen.getByText(/一致性检查：容差内/)).toBeDefined();
    const group = screen.getByTestId("daily-health-group");
    expect(within(group).getByText("pod-a")).toBeDefined();
    expect(within(group).getByText("15 分钟")).toBeDefined();
    expect(within(group).getByText("首次测量 2026-11-05T08:00:00+08:00")).toBeDefined();
    expect(within(group).getByText("最后测量 2026-11-05T08:15:00+08:00")).toBeDefined();
    expect(within(group).getByText("call.csv")).toBeDefined();
    expect(screen.getByTestId("daily-health-seven-day-trend")).toBeDefined();
    expect(screen.getByText("数据日期").parentElement?.textContent).toContain("2026-11-05");
  });

  it("基础指标展示日聚合和全零待配置证据", async () => {
    vi.spyOn(api, "getKpiDailyHealthMetric").mockResolvedValue({
      ...detail,
      metric: {
        ...detail.metric,
        name_zh: "业务触发次数",
        role: "base",
        daily_aggregation: "sum",
        formula: null,
        current_status: "pending_config",
        trend_status: "no_baseline",
        consistency: { status: "not_checked", tolerance_pp: 0.2, difference_pp: null },
      },
      groups: [{
        object_key: "pod-b",
        period_minutes: 60,
        today: { date: "2026-11-05", value: 0, valid_count: 0, status: "zero_denominator" },
        yesterday: null,
        current_status: "pending_config",
        trend_status: "no_baseline",
        reason: "全零待确认",
        source_files: ["zero.csv"],
      }],
    });
    render(
      <App>
        <KpiMetricHealthDetail
          taskId="task-kpi"
          ruleCode="kpi.measurement_units"
          measurementUnitId="MU_CALL"
          metricResourceId="ME_ZERO"
        />
      </App>,
    );

    expect(await screen.findByText("业务触发次数")).toBeDefined();
    expect(screen.getByText("日聚合：sum")).toBeDefined();
    expect(screen.getByText("今日：全零待确认")).toBeDefined();
    expect(screen.getByText(/一致性检查：未检查/)).toBeDefined();
  });
});
