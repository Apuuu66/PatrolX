import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/http";
import {
  KpiDailyHealthPanel,
  type KpiDailyHealthMetric,
  type KpiDailyHealthSnapshot,
} from "./KpiDailyHealthPanel";

function makeMetric(overrides: Partial<KpiDailyHealthMetric> = {}): KpiDailyHealthMetric {
  return {
    measurement_unit_id: "MU_A",
    measurement_unit_name_zh: "测量单元 A",
    measurement_unit_enabled: true,
    metric_resource_id: "ME_A",
    metric_resource_name_zh: "成功率 A",
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
      source: "legacy_resource",
    },
    change_threshold: { value: 0.2, unit: "pp", source: "default" },
    daily_aggregation: "formula",
    aggregation_source: "default",
    zero_semantics: "unknown",
    consistency: { status: "within_tolerance", tolerance_pp: 0.2, difference_pp: 0.01 },
    objects: [{ object_key: "pod-a", period_minutes: 15, current_status: "normal", trend_status: "stable" }],
    ...overrides,
  };
}

function makeSnapshot(metrics: KpiDailyHealthMetric[]): KpiDailyHealthSnapshot {
  return {
    schema_version: 1,
    timezone: "Asia/Shanghai",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    latest_measured_at: "2026-11-05T10:15:00+08:00",
    legacy_fallback: null,
    current_counts: {},
    trend_counts: {},
    scope: {
      enabled_measurement_unit_count: 4,
      confirmed_binding_metric_count: 20,
      expected_metric_count: 20,
      out_of_scope_file_count: 3,
      unconfirmed_binding_count: 2,
      out_of_scope_reason_counts: { disabled_unit: 1, unconfirmed_binding: 2 },
    },
    metrics,
  };
}

function renderPanel(snapshot?: KpiDailyHealthSnapshot) {
  return render(
    <App>
      <KpiDailyHealthPanel
        metadata={snapshot ? { daily_health: snapshot } : {}}
        taskId="task-kpi"
        ruleCode="kpi.measurement_units"
      />
    </App>,
  );
}

describe("KpiDailyHealthPanel", () => {
  it("首屏展示当前判定、昨日趋势、日期和统计范围", () => {
    renderPanel(makeSnapshot([
      makeMetric({ current_status: "fail", trend_status: "worsened" }),
      makeMetric({ metric_resource_id: "ME_WARN", current_status: "warn", trend_status: "stable" }),
      makeMetric({ metric_resource_id: "ME_PENDING", current_status: "pending_config", trend_status: "no_baseline" }),
      makeMetric({ metric_resource_id: "ME_NA", current_status: "not_applicable", trend_status: "no_baseline" }),
    ]));

    expect(screen.getByRole("heading", { name: "KPI 当前判定与昨日趋势" })).toBeDefined();
    expect(screen.getByText(/数据日期 2026-11-05/)).toBeDefined();
    expect(screen.getByText(/对比日 2026-11-04/)).toBeDefined();
    expect(screen.getByText(/Asia\/Shanghai/)).toBeDefined();
    expect(screen.getByTestId("current-fail").textContent).toContain("1");
    expect(screen.getByTestId("current-warn").textContent).toContain("1");
    expect(screen.getByTestId("current-pending_config").textContent).toContain("1");
    expect(screen.getByTestId("current-not_applicable").textContent).toContain("1");
    expect(screen.getByTestId("trend-worsened").textContent).toContain("1");
    expect(screen.getByTestId("trend-stable").textContent).toContain("1");
    expect(screen.getByTestId("daily-health-scope").textContent).toContain("启用测量单元 4");
    expect(screen.getByTestId("daily-health-scope").textContent).toContain("已确认绑定指标 20");
    expect(screen.getByTestId("daily-health-scope").textContent).toContain("范围外文件 3");
    expect(screen.getByTestId("daily-health-scope").textContent).toContain("未确认绑定 2");
  });

  it("顶部只展示数量大于零的当前判定和趋势状态", () => {
    renderPanel(makeSnapshot([
      makeMetric({ metric_resource_id: "ME_NORMAL", current_status: "normal", trend_status: "stable" }),
      makeMetric({ metric_resource_id: "ME_WARN", current_status: "warn", trend_status: "improved" }),
    ]));

    expect(screen.getByTestId("current-normal")).toBeDefined();
    expect(screen.getByTestId("current-warn")).toBeDefined();
    expect(screen.queryByTestId("current-fail")).toBeNull();
    expect(screen.queryByTestId("current-pending_config")).toBeNull();
    expect(screen.getByTestId("trend-stable")).toBeDefined();
    expect(screen.getByTestId("trend-improved")).toBeDefined();
    expect(screen.queryByTestId("trend-worsened")).toBeNull();
  });

  it("统计合计与全部指标表逐项一致", () => {
    const metrics = [
      makeMetric({ metric_resource_id: "ME_1", current_status: "normal", trend_status: "stable" }),
      makeMetric({ metric_resource_id: "ME_2", current_status: "warn", trend_status: "improved" }),
      makeMetric({ metric_resource_id: "ME_3", current_status: "unable_to_judge", trend_status: "no_baseline" }),
    ];
    renderPanel(makeSnapshot(metrics));

    expect(screen.getByTestId("current-total").textContent).toContain("3");
    expect(screen.getByTestId("trend-total").textContent).toContain("3");
    const rows = screen.getAllByTestId("daily-health-metric-row");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain("当前：正常");
    expect(rows[1].textContent).toContain("当前：预警");
    expect(rows[2].textContent).toContain("当前：无法判定");
  });

  it("四个名称相近的成功率按 metric_resource_id 独立展示", () => {
    renderPanel(makeSnapshot([
      makeMetric({ metric_resource_id: "ME_RATE_1", metric_resource_name_zh: "媒体资源创建成功率" }),
      makeMetric({ metric_resource_id: "ME_RATE_2", metric_resource_name_zh: "媒体资源创建请求成功率" }),
      makeMetric({ metric_resource_id: "ME_RATE_3", metric_resource_name_zh: "DC 资源更新成功率" }),
      makeMetric({ metric_resource_id: "ME_RATE_4", metric_resource_name_zh: "数据通道资源更新请求成功率" }),
    ]));

    expect(screen.getAllByText(/成功率$/)).toHaveLength(4);
    for (const id of ["ME_RATE_1", "ME_RATE_2", "ME_RATE_3", "ME_RATE_4"]) {
      expect(screen.getByText(id)).toBeDefined();
    }
  });

  it("指标表展示角色，并支持按当前判定和昨日趋势筛选", async () => {
    renderPanel(makeSnapshot([
      makeMetric({ metric_resource_id: "ME_BASE", measurement_unit_id: "MU_A", role: "base", current_status: "normal", trend_status: "stable" }),
      makeMetric({ metric_resource_id: "ME_FAIL", measurement_unit_id: "MU_B", current_status: "fail", trend_status: "stable" }),
      makeMetric({ metric_resource_id: "ME_WARN", measurement_unit_id: "MU_C", current_status: "warn", trend_status: "improved" }),
      makeMetric({ metric_resource_id: "ME_PENDING", measurement_unit_id: "MU_D", current_status: "pending_config", trend_status: "no_baseline" }),
      makeMetric({ metric_resource_id: "ME_UNKNOWN", measurement_unit_id: "MU_E", current_status: "unable_to_judge", trend_status: "worsened" }),
    ]));

    const table = screen.getByRole("table", { name: "KPI 日健康指标结论" });
    expect(within(table).getByText("基础指标")).toBeDefined();
    expect(within(table).getAllByText("聚合指标").length).toBeGreaterThan(0);

    const currentFilter = screen.getByLabelText("按当前判定筛选");
    const trendFilter = screen.getByLabelText("按昨日趋势筛选");
    for (const [status, metricId] of [
      ["fail", "ME_FAIL"],
      ["warn", "ME_WARN"],
      ["pending_config", "ME_PENDING"],
      ["unable_to_judge", "ME_UNKNOWN"],
    ] as const) {
      await userEvent.selectOptions(currentFilter, status);
      const rows = screen.getAllByTestId("daily-health-metric-row");
      expect(rows).toHaveLength(1);
      expect(rows[0].textContent).toContain(metricId);
    }

    await userEvent.selectOptions(currentFilter, "all");
    await userEvent.selectOptions(trendFilter, "worsened");
    const worsenedRows = screen.getAllByTestId("daily-health-metric-row");
    expect(worsenedRows).toHaveLength(1);
    expect(worsenedRows[0].textContent).toContain("ME_UNKNOWN");
  });

  it("重点指标按当前风险、趋势和重要级别稳定排序", () => {
    renderPanel(makeSnapshot([
      makeMetric({ metric_resource_id: "ME_NORMAL_WORSE", metric_resource_name_zh: "普通但恶化", current_status: "normal", trend_status: "worsened", importance: "P0" }),
      makeMetric({ metric_resource_id: "ME_PENDING", metric_resource_name_zh: "待配置指标", current_status: "pending_config", trend_status: "no_baseline", importance: "P0" }),
      makeMetric({ metric_resource_id: "ME_WARN", metric_resource_name_zh: "预警指标", current_status: "warn", trend_status: "stable", importance: "normal" }),
      makeMetric({ metric_resource_id: "ME_FAIL", metric_resource_name_zh: "失败指标", current_status: "fail", trend_status: "worsened", importance: "P2" }),
    ]));

    const focus = screen.getByTestId("daily-health-focus");
    const rows = within(focus).getAllByTestId("focus-metric");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("失败指标"),
      expect.stringContaining("预警指标"),
      expect.stringContaining("待配置指标"),
      expect.stringContaining("普通但恶化"),
    ]);
  });

  it("需关注指标超过六项时全部展示", () => {
    renderPanel(makeSnapshot(
      Array.from({ length: 7 }, (_, index) => makeMetric({
        metric_resource_id: `ME_FOCUS_${index + 1}`,
        metric_resource_name_zh: `需关注指标 ${index + 1}`,
        current_status: index === 0 ? "normal" : "warn",
        trend_status: index === 0 ? "worsened" : "stable",
      })),
    ));

    const focus = screen.getByTestId("daily-health-focus");
    expect(within(focus).getAllByTestId("focus-metric")).toHaveLength(7);
  });

  it("普通正常稳定指标不进入重点关注", () => {
    renderPanel(makeSnapshot([
      makeMetric({ metric_resource_id: "ME_STABLE", metric_resource_name_zh: "正常稳定指标" }),
      makeMetric({
        metric_resource_id: "ME_FAIL",
        metric_resource_name_zh: "失败指标",
        current_status: "fail",
        trend_status: "stable",
      }),
    ]));

    const focus = screen.getByTestId("daily-health-focus");
    const rows = within(focus).getAllByTestId("focus-metric");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("失败指标");
    expect(focus.textContent).not.toContain("正常稳定指标");
  });

  it("零分母显示不适用而不是 0%", () => {
    renderPanel(makeSnapshot([
      makeMetric({
        metric_resource_id: "ME_ZERO",
        metric_resource_name_zh: "零分母成功率",
        today_value: null,
        today_display: null,
        yesterday_value: null,
        yesterday_display: null,
        delta: null,
        delta_display: null,
        current_status: "not_applicable",
        current_reason: "zero_denominator",
        current_reason_text: "当日分母为零",
        trend_status: "no_baseline",
      }),
    ]));

    const row = screen.getByTestId("daily-health-metric-row");
    expect(within(row).getByText("不适用")).toBeDefined();
    expect(within(row).queryByText("0.0%")).toBeNull();
  });

  it("旧任务传入 legacy_fallback 时显示兼容提示", () => {
    const snapshot = makeSnapshot([]);
    snapshot.legacy_fallback = { code: "legacy_result", message: "旧结果缺少日健康判定，请重跑任务" };
    renderPanel(snapshot);

    expect(screen.getByText("KPI 日健康兼容提示")).toBeDefined();
    expect(screen.getByText("旧结果缺少日健康判定，请重跑任务")).toBeDefined();
  });

  it("旧任务完全缺少 daily_health 时降级且不崩溃", () => {
    renderPanel();

    expect(screen.getByText("KPI 日健康兼容提示")).toBeDefined();
    expect(screen.getByText(/旧任务没有日健康结论/)).toBeDefined();
    expect(screen.queryByTestId("daily-health-metric-row")).toBeNull();
  });

  it("点击指标证据入口后按需加载单指标详情", async () => {
    const getDetail = vi.spyOn(api, "getKpiDailyHealthMetric").mockReturnValue(new Promise(() => {}));
    renderPanel(makeSnapshot([makeMetric()]));

    await userEvent.click(screen.getByRole("button", { name: /查看.*证据/ }));
    await waitFor(() => expect(getDetail).toHaveBeenCalledWith(
      "task-kpi",
      "kpi.measurement_units",
      "MU_A",
      "ME_A",
    ));
  });
});
