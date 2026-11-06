import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  KpiMetricResultPageV6,
  KpiTaskSummaryV6,
} from "../../api/http";
import {
  EMPTY_KPI_RESULT_FILTERS,
  KpiResultViews,
  type KpiResultFilters,
} from "./KpiResultViews";

function makeSummary(): KpiTaskSummaryV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    result_contract_version: "v6",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    latest_measured_at: "2026-11-05T08:00:00Z",
    counts: {
      enabled_measurement_unit_count: 2,
      all_metric_count: 20,
      team_focus_count: 10,
      needs_attention_count: 6,
      no_action_count: 4,
      unavailable_focus_count: 0,
    },
    needs_attention_groups: [
      { group: "failure", order: 1, count: 3 },
      { group: "warning", order: 2, count: 1 },
      { group: "trend_degraded", order: 3, count: 1 },
      { group: "unjudgeable", order: 4, count: 1 },
      { group: "needs_config", order: 5, count: 0 },
    ],
    rule_scope: {
      business_rule_count: 1,
      has_executable_rules: true,
      notice: null,
    },
    notices: [],
  };
}

function makePage(
  emptyState: KpiMetricResultPageV6["empty_state"] = "none",
): KpiMetricResultPageV6 {
  return {
    items: [],
    total: emptyState === "none" ? 3 : 0,
    view_total: 10,
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

function renderViews({
  filters = EMPTY_KPI_RESULT_FILTERS,
  page = makePage(),
  onViewChange = vi.fn(),
  onFiltersChange = vi.fn(),
  onClearFilters = vi.fn(),
}: {
  filters?: KpiResultFilters;
  page?: KpiMetricResultPageV6;
  onViewChange?: (view: "needs_attention" | "team_focus" | "all") => void;
  onFiltersChange?: (filters: KpiResultFilters) => void;
  onClearFilters?: () => void;
} = {}) {
  return render(
    <KpiResultViews
      summary={makeSummary()}
      view="needs_attention"
      filters={filters}
      page={page}
      measurementUnitOptions={[
        { value: "MU_MEDIA", label: "媒体资源测量单元" },
        { value: "MU_CALL", label: "呼叫测量单元" },
      ]}
      onViewChange={onViewChange}
      onFiltersChange={onFiltersChange}
      onClearFilters={onClearFilters}
    />,
  );
}

describe("KpiResultViews", () => {
  it("展示三视图计数并支持点击和方向键切换", async () => {
    const onViewChange = vi.fn();
    renderViews({ onViewChange });

    expect(screen.getByRole("tab", { name: "需处理 6" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "团队关注 10" })).toBeDefined();
    expect(screen.getByRole("tab", { name: "全部指标 20" })).toBeDefined();

    await userEvent.click(screen.getByRole("tab", { name: "团队关注 10" }));
    expect(onViewChange).toHaveBeenLastCalledWith("team_focus");

    screen.getByRole("tab", { name: "需处理 6" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onViewChange).toHaveBeenLastCalledWith("team_focus");
  });

  it("组合搜索、测量单元、判定和趋势筛选并显示可见数与视图总数", async () => {
    const onFiltersChange = vi.fn();
    renderViews({ onFiltersChange });

    await userEvent.type(screen.getByRole("searchbox", { name: "搜索指标" }), "媒体");
    expect(onFiltersChange).toHaveBeenLastCalledWith({
      ...EMPTY_KPI_RESULT_FILTERS,
      search: "媒体",
    });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "测量单元筛选" }),
      "MU_MEDIA",
    );
    expect(onFiltersChange).toHaveBeenLastCalledWith({
      ...EMPTY_KPI_RESULT_FILTERS,
      measurementUnitId: "MU_MEDIA",
    });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "当前判定筛选" }),
      "fail",
    );
    expect(onFiltersChange).toHaveBeenLastCalledWith({
      ...EMPTY_KPI_RESULT_FILTERS,
      currentStatus: "fail",
    });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "昨日趋势筛选" }),
      "worsened",
    );
    expect(onFiltersChange).toHaveBeenLastCalledWith({
      ...EMPTY_KPI_RESULT_FILTERS,
      yesterdayTrend: "worsened",
    });

    expect(screen.getByTestId("kpi-result-visible-total").textContent).toContain(
      "当前可见 3 / 视图总计 10 项",
    );
  });

  it("存在筛选时启用清除全部筛选，无筛选时禁用", async () => {
    const onClearFilters = vi.fn();
    const { rerender } = renderViews({ onClearFilters });
    const clearButton = screen.getByRole("button", { name: "清除全部筛选" });
    expect(clearButton).toHaveProperty("disabled", true);

    rerender(
      <KpiResultViews
        summary={makeSummary()}
        view="needs_attention"
        filters={{ ...EMPTY_KPI_RESULT_FILTERS, search: "媒体" }}
        page={makePage()}
        measurementUnitOptions={[]}
        onViewChange={vi.fn()}
        onFiltersChange={vi.fn()}
        onClearFilters={onClearFilters}
      />,
    );
    expect(clearButton).toHaveProperty("disabled", false);

    await userEvent.click(clearButton);
    expect(onClearFilters).toHaveBeenCalledOnce();
  });

  it.each([
    ["team_focus_empty", "当前网元类型的团队关注为空", null],
    ["no_task_metrics", "当前任务没有 KPI 指标", "刷新当前结果"],
    ["no_matching_metrics", "没有符合当前条件的指标", "清除筛选"],
  ] as const)("为 %s 展示对应空态", (emptyState, title, action) => {
    renderViews({ page: makePage(emptyState) });

    expect(screen.getByRole("status").textContent).toContain(title);
    if (action) expect(screen.getByRole("button", { name: action })).toBeDefined();
  });
});
