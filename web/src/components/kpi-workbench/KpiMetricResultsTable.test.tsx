import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { KpiMetricResultPageV6, KpiMetricResultV6 } from "../../api/http";
import { KpiMetricResultsTable } from "./KpiMetricResultsTable";

function makeMetric(overrides: Partial<KpiMetricResultV6> = {}): KpiMetricResultV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    measurement_unit_id: "MU_MEDIA",
    measurement_unit_name: "媒体资源测量单元",
    metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
    metric_name: "媒体资源创建成功率",
    role: "base",
    importance: "P1",
    importance_rank: 1,
    availability: "available",
    is_team_focus: true,
    current_status: "fail",
    yesterday_trend: "worsened",
    needs_attention_group: "failure",
    special_state: null,
    today_value: 63.7,
    yesterday_value: 75,
    change_value: -11.3,
    change_unit: "pp",
    reason: "源包成功率低于失败阈值，且较昨日下降超过容差。",
    evidence_available: true,
    ...overrides,
  };
}

function makePage(items: KpiMetricResultV6[], emptyState: KpiMetricResultPageV6["empty_state"] = "none"): KpiMetricResultPageV6 {
  return {
    items,
    total: items.length,
    view_total: items.length,
    page: 1,
    page_size: 20,
    empty_state: emptyState,
    applied_filters: {
      search: null,
      measurement_unit_id: null,
      current_status: null,
      yesterday_trend: null,
      needs_attention_group: null,
    },
  };
}

describe("KpiMetricResultsTable", () => {
  it("源包成功率按 base 值展示，不出现重算公式或替代值", async () => {
    const onOpenEvidence = vi.fn();
    render(
      <KpiMetricResultsTable
        page={makePage([makeMetric()])}
        onOpenEvidence={onOpenEvidence}
      />,
    );

    const row = screen.getByTestId("kpi-metric-row");
    expect(within(row).getByText("媒体资源创建成功率")).toBeDefined();
    expect(row.textContent).toContain("媒体资源测量单元");
    expect(row.textContent).toContain("ME_MEDIA_CREATION_SUCCESS_RATE");
    expect(row.textContent).toContain("源包直出 · base");
    expect(row.textContent).toContain("63.7");
    expect(row.textContent).toContain("-11.3pp");
    expect(row.textContent).toContain("失败");
    expect(row.textContent).not.toContain("71.67");
    expect(row.textContent).not.toContain("129 / 180");

    await userEvent.click(screen.getByRole("button", { name: "查看媒体资源创建成功率证据" }));
    expect(onOpenEvidence).toHaveBeenCalledWith(expect.objectContaining({
      metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
      role: "base",
      today_value: 63.7,
    }));
  });

  it("空源值保持缺失，不用 0 或关联计数回填", () => {
    render(
      <KpiMetricResultsTable
        page={makePage([
          makeMetric({
            current_status: "unable_to_judge",
            yesterday_trend: "no_baseline",
            needs_attention_group: "unjudgeable",
            today_value: null,
            yesterday_value: null,
            change_value: null,
            change_unit: "unavailable",
            reason: "源包未提供成功率，无法判定。",
          }),
        ])}
      />,
    );

    const value = screen.getByTestId("kpi-metric-today-value-0");
    expect(value.textContent).toBe("源值缺失");
    expect(screen.getByTestId("kpi-metric-row").textContent).not.toContain("0%");
  });

  it("保持服务端返回顺序，不在前端重排", () => {
    render(
      <KpiMetricResultsTable
        page={makePage([
          makeMetric({ metric_resource_id: "METRIC_B", metric_name: "指标 B" }),
          makeMetric({ metric_resource_id: "METRIC_A", metric_name: "指标 A" }),
        ])}
      />,
    );

    expect(screen.getAllByTestId("kpi-metric-row").map((row) => row.getAttribute("data-metric-id"))).toEqual([
      "METRIC_B",
      "METRIC_A",
    ]);
  });

  it("关注为空和任务无指标使用不同空态文案", () => {
    const { rerender } = render(
      <KpiMetricResultsTable page={makePage([], "team_focus_empty")} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText("当前网元类型的团队关注为空")).toBeDefined();

    rerender(<KpiMetricResultsTable page={makePage([], "no_task_metrics")} onRefresh={vi.fn()} />);
    expect(screen.getByText("当前任务没有 KPI 指标")).toBeDefined();
    expect(screen.queryByText("当前网元类型的团队关注为空")).toBeNull();
  });
});
