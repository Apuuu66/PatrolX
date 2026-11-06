import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { KpiTaskSummaryV6 } from "../../api/http";
import { KpiSummaryHeader } from "./KpiSummaryHeader";

function makeSummary(): KpiTaskSummaryV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    result_contract_version: "v6",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    latest_measured_at: "2026-11-05T08:00:00Z",
    counts: {
      enabled_measurement_unit_count: 1,
      all_metric_count: 20,
      team_focus_count: 10,
      needs_attention_count: 10,
      no_action_count: 0,
      unavailable_focus_count: 0,
    },
    needs_attention_groups: [
      { group: "failure", order: 1, count: 3 },
      { group: "warning", order: 2, count: 2 },
      { group: "trend_degraded", order: 3, count: 3 },
      { group: "unjudgeable", order: 4, count: 1 },
      { group: "needs_config", order: 5, count: 1 },
    ],
    rule_scope: {
      business_rule_count: 1,
      has_executable_rules: true,
      notice: null,
    },
    notices: [],
  };
}

describe("KpiSummaryHeader", () => {
  it("展示全局日期、测量时间和互斥分组汇总", () => {
    render(<KpiSummaryHeader summary={makeSummary()} />);

    expect(screen.getByText("UMF 团队关注 · 按网元类型共享")).toBeDefined();
    expect(screen.getByText("2026-11-05")).toBeDefined();
    expect(screen.getByText("2026-11-04")).toBeDefined();
    expect(screen.getByText(/11-05 16:00/)).toBeDefined();
    expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10");
    expect(screen.getByTestId("kpi-summary-all").textContent).toContain("20");
    expect(screen.getByTestId("kpi-summary-focus").textContent).toContain("10");
    expect(screen.getByTestId("kpi-summary-no-action").textContent).toContain("0");
    expect(screen.getByTestId("kpi-summary-enabled-units").textContent).toContain("1");

    const groups = screen.getByTestId("kpi-summary-groups");
    expect(within(groups).getAllByTestId(/kpi-group-/).map((item) => item.textContent)).toEqual([
      expect.stringContaining("失败3"),
      expect.stringContaining("预警2"),
      expect.stringContaining("昨日恶化3"),
      expect.stringContaining("无法判定1"),
      expect.stringContaining("待配置1"),
    ]);
  });

  it("分组状态同时包含文字和颜色，并可通过键盘选择", async () => {
    const onGroupSelect = vi.fn();
    render(
      <KpiSummaryHeader
        summary={makeSummary()}
        selectedGroup="failure"
        onGroupSelect={onGroupSelect}
      />,
    );

    const failure = screen.getByTestId("kpi-group-failure");
    expect(failure.textContent).toContain("失败");
    expect(failure.className).toContain("is-failure");
    expect(failure.getAttribute("aria-pressed")).toBe("true");

    failure.focus();
    expect(document.activeElement).toBe(failure);
    await userEvent.keyboard("{Enter}");
    expect(onGroupSelect).toHaveBeenCalledWith("failure");
  });

  it("筛选选择变化不会改写全局汇总计数", () => {
    const summary = makeSummary();
    const { rerender } = render(<KpiSummaryHeader summary={summary} />);

    rerender(<KpiSummaryHeader summary={summary} selectedGroup="needs_config" />);

    expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10");
    expect(screen.getByTestId("kpi-summary-focus").textContent).toContain("10");
    expect(screen.getByTestId("kpi-group-failure").textContent).toContain("3");
  });
});
