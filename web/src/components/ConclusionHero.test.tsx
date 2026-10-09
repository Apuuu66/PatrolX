import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

import type { RuleStatus, SystemInspection, TaskStats, TaskSummary } from "../api/http";
import { ConclusionHero } from "./ConclusionHero";

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1, ...overrides };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-001",
    name: "样例任务",
    mode: "local",
    status: "completed",
    trigger: "ui",
    created_at: "2026-10-10T00:00:00Z",
    completed_at: "2026-10-10T00:01:00Z",
    stats: makeStats(),
    ...overrides,
  };
}

function makeCounts(overrides: Partial<Record<RuleStatus, number>> = {}): Record<RuleStatus, number> {
  return { pass: 0, warn: 0, fail: 0, error: 0, skip: 0, ...overrides };
}

function renderHero(props: Partial<Parameters<typeof ConclusionHero>[0]> = {}) {
  return render(
    <App>
      <ConclusionHero
        task={makeTask()}
        system={null}
        statusCounts={makeCounts({ pass: 1 })}
        activeStatus={null}
        onStatusClick={() => {}}
        onOpenReport={() => {}}
        onOpenLogs={() => {}}
        {...props}
      />
    </App>,
  );
}

describe("ConclusionHero", () => {
  it("全通过任务展示结论标签、一句话、状态计数与关键元数据", () => {
    renderHero({
      system: {
        package_file: "package.zip",
        version: "V900R016C10SPC200",
        status: "completed",
        summary: makeStats(),
        rules: [],
        customer: { province: "js", operator: "cmcc", product: "umf" },
      } as unknown as SystemInspection,
    });

    expect(screen.getByText("全部通过")).toBeDefined();
    expect(screen.getByText("共执行 1 条规则，未发现失败、告警或异常。")).toBeDefined();
    expect(screen.getByLabelText("筛选通过").textContent).toContain("通过 1");
    expect(screen.getByRole("button", { name: /查看报告/ })).toBeDefined();
    expect(screen.queryByLabelText("筛选失败")).toBeNull();

    expect(screen.getByText("package.zip")).toBeDefined();
    expect(screen.getByText("V900R016C10SPC200")).toBeDefined();
    expect(screen.getByText("cmcc")).toBeDefined();

    // 超过 4 项的真实字段进入"更多元数据"，不产生占位噪音（FR-010）
    expect(screen.queryByText("umf")).toBeNull();
    expect(screen.getByRole("button", { name: /更多元数据/ })).toBeDefined();
  });

  it("关键元数据最多平铺 4 项，其余可展开查看", async () => {
    const { container } = renderHero({
      system: {
        package_file: "package.zip",
        version: "V900R016C10SPC200",
        status: "completed",
        summary: makeStats(),
        rules: [],
        customer: { province: "js", operator: "cmcc", product: "umf" },
      } as unknown as SystemInspection,
    });

    expect(container.querySelectorAll("[data-metadata-key]")).toHaveLength(4);

    await userEvent.click(screen.getByRole("button", { name: /更多元数据/ }));
    expect(await screen.findByText("umf")).toBeDefined();
    expect(screen.getByText("2026-10-10 08:00")).toBeDefined();
  });

  it("关键元数据不渲染空字段与横线占位", () => {
    const { container } = renderHero({ task: makeTask({ task_id: "task001" }), system: null });

    const values = Array.from(container.querySelectorAll(".metadata-list-value-text")).map(
      (node) => node.textContent ?? "",
    );
    expect(values.length).toBeGreaterThan(0);
    expect(values.every((value) => value.trim().length > 0 && value.trim() !== "-")).toBe(true);
    expect(container.querySelector('[data-metadata-key="package"]')).toBeNull();
    expect(container.querySelector('[data-metadata-key="province"]')).toBeNull();
  });

  it("结论句不出现零值状态", () => {
    renderHero({
      task: makeTask({ stats: makeStats({ total: 3, pass: 1, fail: 2 }) }),
      statusCounts: makeCounts({ pass: 1, fail: 2 }),
    });

    expect(screen.getByText("发现失败 2 条规则结果，需要处理。")).toBeDefined();
    expect(screen.queryByText(/异常 0 条/)).toBeNull();
  });

  it("任务失败时展示失败原因与阶段并给出失败日志主操作", () => {
    const onOpenLogs = vi.fn();
    const onOpenReport = vi.fn();
    renderHero({
      task: makeTask({ status: "failed", completed_at: null, stats: makeStats({ pass: 0, total: 0 }) }),
      statusCounts: makeCounts(),
      failureReason: "主包解压失败，任务失败：解压总量超限",
      onOpenLogs,
      onOpenReport,
    });

    expect(screen.getByText("任务失败")).toBeDefined();
    expect(screen.getByText("主包解压失败，任务失败：解压总量超限")).toBeDefined();
    expect(screen.getByText("失败阶段：任务执行")).toBeDefined();
    expect(screen.getByText("暂无规则结果")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /查看失败日志/ }));
    expect(onOpenLogs).toHaveBeenCalledTimes(1);
    expect(onOpenReport).not.toHaveBeenCalled();
  });

  it("排队中与执行中禁用报告主操作并说明原因", () => {
    const onOpenReport = vi.fn();
    for (const [status, reason] of [
      ["pending", "任务排队中，报告暂不可用。"],
      ["running", "任务执行中，报告暂不可用。"],
    ] as const) {
      const { unmount } = renderHero({
        task: makeTask({ status, completed_at: null }),
        statusCounts: makeCounts(),
        onOpenReport,
      });

      const button = screen.getByRole("button", { name: /查看报告/ });
      expect(button.hasAttribute("disabled")).toBe(true);
      fireEvent.click(button);
      expect(onOpenReport).not.toHaveBeenCalled();
      expect(screen.getByText(reason)).toBeDefined();
      unmount();
    }
  });

  it("fail 与 error 并存时结论计入异常条数", () => {
    renderHero({
      task: makeTask({ stats: makeStats({ total: 3, pass: 1, fail: 1, error: 1 }) }),
      statusCounts: makeCounts({ pass: 1, fail: 1, error: 1 }),
    });

    expect(screen.getByText("需要关注")).toBeDefined();
    expect(screen.getByText("发现失败 1 条、异常 1 条规则结果，需要处理。")).toBeDefined();
    expect(screen.getByText("失败 1")).toBeDefined();
    expect(screen.getByText("异常 1")).toBeDefined();
  });
});
