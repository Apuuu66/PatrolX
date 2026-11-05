import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { Profiler } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  api,
  type MeasurementKpiOverview,
  type MeasurementMetadataMetric,
  type MeasurementMetadataUnit,
} from "../api/http";
import type { KpiDailyHealthSnapshot } from "./KpiDailyHealthPanel";
import { MeasurementInspectionPanel } from "./MeasurementInspectionPanel";

function makeMetric(id: string, name: string): MeasurementMetadataMetric {
  return {
    metric_resource_id: id,
    metric_resource_name_zh: name,
    raw_source_name: id,
    read_status: "ok",
    value_pattern: "normal",
    business_status: "normal",
  };
}

function makeUnit(id: string, name: string, metricName: string, healthScore: number): MeasurementMetadataUnit {
  return {
    measurement_unit_id: id,
    name_zh: name,
    name_en: id,
    status: "warn",
    file_count: 1,
    metrics: [makeMetric(`${id}_METRIC`, metricName)],
    risk_summary: {
      health_score: healthScore,
      business_fail_count: 0,
      business_warn_count: 1,
      data_error_count: 0,
      trend_worsened_count: 0,
      unconfigured_count: 0,
    },
  };
}

function makeMetricWithManyDetails(): MeasurementMetadataMetric {
  return {
    ...makeMetric("MU_DETAIL_METRIC", "明细指标"),
    trends: Array.from({ length: 12 }, (_, index) => ({
      label: "stable",
      signal: "none",
      object_key: `trend-object-${index + 1}`,
      period_minutes: 15,
      point_count: 2,
      reason: `trend-reason-${index + 1}`,
    })),
    observations: Array.from({ length: 12 }, (_, index) => ({
      object_key: `observation-object-${index + 1}`,
      row_count: 1,
      valid_count: 1,
      null_count: 0,
      parse_error_count: 0,
      zero_count: 0,
      min_value: 1,
      max_value: 1,
      avg_value: 1,
      value_pattern: "normal",
      business_status: "normal",
    })),
  };
}

function makeDailyHealthSnapshot(): KpiDailyHealthSnapshot {
  return {
    schema_version: 1,
    timezone: "Asia/Shanghai",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    latest_measured_at: "2026-11-05T10:15:00+08:00",
    legacy_fallback: null,
    current_counts: { normal: 1 },
    trend_counts: { stable: 1 },
    scope: {
      enabled_measurement_unit_count: 1,
      confirmed_binding_metric_count: 1,
      expected_metric_count: 1,
      out_of_scope_file_count: 0,
      unconfirmed_binding_count: 0,
      out_of_scope_reason_counts: {},
    },
    metrics: [{
      measurement_unit_id: "MU_A",
      measurement_unit_name_zh: "测量单元 A",
      measurement_unit_enabled: true,
      metric_resource_id: "ME_A",
      metric_resource_name_zh: "日健康指标",
      metric_resource_enabled: true,
      binding_confirmed: true,
      role: "derived",
      importance: "P1",
      direction: "higher_better",
      display_unit: "%",
      is_percentage: true,
      current_status: "normal",
      current_reason: "threshold_satisfied",
      current_reason_text: "达到阈值要求",
      today_value: 99.2,
      today_display: "99.2%",
      yesterday_value: 99,
      yesterday_display: "99.0%",
      delta: 0.2,
      delta_display: "+0.2pp",
      trend_status: "stable",
      trend_reason: "变化在容差内（pp）",
      trend_reason_code: "within_tolerance",
      current_threshold: {
        direction: "higher_better",
        warning_threshold: 99,
        critical_threshold: 98,
        source: "custom",
      },
      change_threshold: { value: 0.2, unit: "pp", source: "default" },
      daily_aggregation: "formula",
      aggregation_source: "default",
      zero_semantics: "unknown",
      consistency: { status: "within_tolerance", tolerance_pp: 0.2, difference_pp: 0.01 },
      objects: [],
    }],
  };
}

function makeKpiOverview(): MeasurementKpiOverview {
  return {
    unit_count: 1,
    metric_count: 1,
    health_score: 90,
    status_counts: { warn: 1 },
    business_fail_count: 0,
    business_warn_count: 1,
    data_error_count: 0,
    trend_worsened_count: 0,
    unconfigured_count: 0,
  };
}

async function chooseUnit(name: string) {
  const combobox = screen.getByRole("combobox", { name: "测量单元" });
  const option = within(combobox).getByRole("option", { name: new RegExp(name) });
  await userEvent.selectOptions(combobox, option);
}

describe("MeasurementInspectionPanel", () => {
  it("首屏先展示日健康结论，再展示原有 KPI 总览", () => {
    render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            daily_health: makeDailyHealthSnapshot(),
            kpi_overview: makeKpiOverview(),
            measurement_units: [makeUnit("MU_A", "测量单元 A", "指标 A", 90)],
          }}
        />
      </App>,
    );

    const dailyHealth = screen.getByRole("region", { name: "KPI 当前判定与昨日趋势" });
    const overview = screen.getByRole("region", { name: "KPI 总览" });
    expect(dailyHealth.compareDocumentPosition(overview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("日健康指标")).toBeDefined();
  });

  it("没有测量单元时仍展示旧任务日健康兼容提示", () => {
    render(
      <App>
        <MeasurementInspectionPanel metadata={{ measurement_units: [] }} />
      </App>,
    );

    expect(screen.getByRole("heading", { name: "KPI 日健康兼容提示" })).toBeDefined();
    expect(screen.getByText(/旧任务没有日健康结论/)).toBeDefined();
  });

  it("一次只挂载一个测量单元，并允许切换到其他单元", async () => {
    render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            measurement_units: [
              makeUnit("MU_A", "测量单元 A", "指标 A", 60),
              makeUnit("MU_B", "测量单元 B", "指标 B", 80),
            ],
          }}
        />
      </App>,
    );

    expect(screen.queryByText("指标 B")).toBeNull();
    expect(screen.getByText("指标 A")).toBeDefined();

    await chooseUnit("测量单元 B");

    await waitFor(() => {
      expect(screen.getByText("指标 B")).toBeDefined();
    });
    expect(screen.queryByText("指标 A")).toBeNull();
  });

  it("默认展示健康分最低的测量单元", () => {
    const { container } = render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            measurement_units: [
              makeUnit("MU_HEALTHY", "健康单元", "健康指标", 95),
              makeUnit("MU_RISKY", "风险单元", "风险指标", 40),
            ],
          }}
        />
      </App>,
    );

    const selector = within(container).getByTestId("measurement-unit-selector");
    expect(selector.textContent).toContain("风险单元");
    expect(screen.getByText("风险指标")).toBeDefined();
    expect(screen.queryByText("健康指标")).toBeNull();
  });

  it("首屏指标列表不挂载 rc-table 或 AntD 行控件，并保持每页十条", async () => {
    const metrics = Array.from({ length: 11 }, (_, index) => {
      const order = String(index).padStart(2, "0");
      return makeMetric(`METRIC_${order}`, `指标 ${order}`);
    });
    const { container } = render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            measurement_units: [
              {
                ...makeUnit("MU_LIGHT", "轻量单元", "轻量指标", 100),
                metrics,
              },
            ],
          }}
        />
      </App>,
    );

    expect(screen.getByRole("table", { name: "KPI 指标列表" })).toBeDefined();
    expect(container.querySelector(".ant-table")).toBeNull();
    expect(container.querySelector(".measurement-inspection-panel .ant-btn")).toBeNull();
    expect(container.querySelector(".measurement-metric-table .ant-typography")).toBeNull();
    await waitFor(() => expect(screen.getByText("指标 09")).toBeDefined());
    expect(screen.queryByText("指标 10")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() => expect(screen.getByText("指标 10")).toBeDefined());
  });

  it("初始指标不超过首屏条数时只提交一次，不触发无意义重渲染", () => {
    const onRender = vi.fn();
    render(
      <App>
        <Profiler id="measurement-panel" onRender={onRender}>
          <MeasurementInspectionPanel
            metadata={{
              measurement_units: [
                {
                  ...makeUnit("MU_SINGLE_RENDER", "单次渲染单元", "单次渲染指标", 100),
                  metrics: [makeMetric("METRIC_SINGLE", "单次渲染指标")],
                },
              ],
            }}
          />
        </Profiler>
      </App>,
    );

    expect(screen.getByText("单次渲染指标")).toBeDefined();
    expect(onRender).toHaveBeenCalledTimes(1);
  });

  it("指标排序复用本地化比较器，不逐次调用 localeCompare", () => {
    const localeCompare = vi.spyOn(String.prototype, "localeCompare").mockImplementation(() => {
      throw new Error("指标排序不应逐次构造 localeCompare");
    });

    try {
      render(
        <App>
          <MeasurementInspectionPanel
            metadata={{
              measurement_units: [
                {
                  ...makeUnit("MU_COLLATOR", "排序单元", "排序指标", 100),
                  metrics: [
                    makeMetric("METRIC_B", "指标 B"),
                    makeMetric("METRIC_A", "指标 A"),
                  ],
                },
              ],
            }}
          />
        </App>,
      );

      expect(screen.getByText("指标 A")).toBeDefined();
    } finally {
      localeCompare.mockRestore();
    }
  });

  it("当前页十条指标一次挂载，不启动逐帧刷新", () => {
    const metrics = Array.from({ length: 10 }, (_, index) => {
      const order = String(index).padStart(2, "0");
      return makeMetric(`METRIC_${order}`, `分帧指标 ${order}`);
    });
    render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            measurement_units: [
              {
                ...makeUnit("MU_PROGRESSIVE", "分帧单元", "分帧指标", 100),
                metrics,
              },
            ],
          }}
        />
      </App>,
    );

    expect(screen.getByText("分帧指标 00")).toBeDefined();
    expect(screen.getByText("分帧指标 09")).toBeDefined();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("指标明细的趋势和行对象分页展示，避免一次挂载全部记录", async () => {
    const { container } = render(
      <App>
        <MeasurementInspectionPanel
          metadata={{
            measurement_units: [
              {
                ...makeUnit("MU_DETAIL", "明细单元", "明细指标", 100),
                metrics: [makeMetricWithManyDetails()],
              },
            ],
          }}
        />
      </App>,
    );

    await userEvent.click(screen.getByRole("button", { name: "展开明细指标明细" }));

    expect(await screen.findByText("trend-reason-10")).toBeDefined();
    expect(screen.queryByText("trend-reason-11")).toBeNull();
    expect(screen.getByText("observation-object-10")).toBeDefined();
    expect(screen.queryByText("observation-object-11")).toBeNull();
    expect(container.querySelector(".ant-table")).toBeNull();
  });
  it("展开指标后再查看趋势时复用已加载明细，不重复请求详情", async () => {
    const metric = {
      ...makeMetric("MU_DETAIL_METRIC", "明细指标"),
      trend_points: [
        {
          time: "2026-09-20T10:00:00",
          object_key: "pod-a",
          period_minutes: 15,
          value: 2048,
        },
      ],
    };
    const detailMetric: MeasurementMetadataMetric = {
      ...metric,
      metric_group: "已加载详情",
    };
    const detailRequest = vi.spyOn(api, "getMeasurementMetricDetail").mockResolvedValue({
      task_id: "task-kpi",
      rule_code: "kpi.measurement_units",
      measurement_unit_id: "MU_DETAIL",
      metric: detailMetric,
    });
    try {
      const { container } = render(
        <App>
          <MeasurementInspectionPanel
            metadata={{
              measurement_units: [
                {
                  ...makeUnit("MU_DETAIL", "明细单元", "明细指标", 100),
                  metrics: [metric],
                },
              ],
            }}
            taskId="task-kpi"
            ruleCode="kpi.measurement_units"
          />
        </App>,
      );

      await userEvent.click(screen.getByRole("button", { name: "展开明细指标明细" }));

      expect(await screen.findByText("已加载详情")).toBeDefined();
      expect(detailRequest).toHaveBeenCalledTimes(1);

      await userEvent.click(screen.getByRole("button", { name: "查看明细指标完整趋势" }));

      expect(await screen.findByText("趋势点不足，无法判断趋势")).toBeDefined();
      expect(detailRequest).toHaveBeenCalledTimes(1);
    } finally {
      detailRequest.mockRestore();
    }
  });

});
