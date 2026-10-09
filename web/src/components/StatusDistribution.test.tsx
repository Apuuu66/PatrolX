import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TaskStats } from "../api/http";
import { StatusDistribution } from "./StatusDistribution";

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 0, ...overrides };
}

describe("StatusDistribution", () => {
  it("只渲染非零状态并保留文字标签", () => {
    render(<StatusDistribution stats={makeStats({ total: 3, pass: 2, warn: 1 })} />);

    expect(screen.getByText("通过 2")).toBeDefined();
    expect(screen.getByText("告警 1")).toBeDefined();
    expect(screen.queryByText("失败 0")).toBeNull();
    expect(screen.queryByText("异常 0")).toBeNull();
    expect(screen.queryByText("跳过 0")).toBeNull();
  });

  it("按非零数值计算分段占比", () => {
    const { container } = render(
      <StatusDistribution stats={makeStats({ total: 4, pass: 3, warn: 1 })} />,
    );

    const passSegment = container.querySelector<HTMLElement>('[data-status-segment="pass"]');
    const warnSegment = container.querySelector<HTMLElement>('[data-status-segment="warn"]');
    expect(passSegment?.style.width).toBe("75%");
    expect(warnSegment?.style.width).toBe("25%");
  });

  it("五态全 0 时渲染空态而不是空条", () => {
    const { container } = render(<StatusDistribution stats={makeStats()} />);

    expect(container.querySelector(".status-distribution-bar")).toBeNull();
    expect(screen.getByText("暂无规则结果")).toBeDefined();
  });

  it("紧凑与完整两形态共享同一结论", () => {
    const stats = makeStats({ total: 2, warn: 2 });
    const { container: compact } = render(<StatusDistribution stats={stats} variant="compact" />);
    expect(compact.querySelector('[data-status-segment="warn"]')).not.toBeNull();

    const { container: full } = render(<StatusDistribution stats={stats} variant="full" />);
    expect(full.querySelector('[data-status-segment="warn"]')).not.toBeNull();
  });

  it("提供 onStatusClick 时非零计数可点选并标记激活态", () => {
    const onStatusClick = vi.fn();
    render(
      <StatusDistribution
        stats={makeStats({ total: 3, pass: 2, fail: 1 })}
        activeStatus="fail"
        onStatusClick={onStatusClick}
      />,
    );

    const failCount = screen.getByLabelText("筛选失败");
    expect(failCount.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(failCount);
    expect(onStatusClick).toHaveBeenCalledWith("fail");
  });

  it("未提供 onStatusClick 时不产生可点选元素", () => {
    render(<StatusDistribution stats={makeStats({ total: 2, pass: 2 })} />);

    expect(screen.queryByLabelText("筛选通过")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("按 fail → warn → error → skip → pass 排序分段与计数", () => {
    const { container } = render(
      <StatusDistribution
        stats={makeStats({ total: 8, pass: 3, warn: 1, fail: 2, error: 1, skip: 1 })}
      />,
    );

    const segments = Array.from(
      container.querySelectorAll<HTMLElement>("[data-status-segment]"),
    ).map((node) => node.dataset.statusSegment);
    const counts = Array.from(container.querySelectorAll<HTMLElement>("[data-status-count]")).map(
      (node) => node.dataset.statusCount,
    );

    expect(segments).toEqual(["fail", "warn", "error", "skip", "pass"]);
    expect(counts).toEqual(["fail", "warn", "error", "skip", "pass"]);
  });

  it("分段与计数 Tooltip 文案为状态 计数（整数百分比）", async () => {
    const { container } = render(
      <StatusDistribution stats={makeStats({ total: 3, pass: 1, fail: 2 })} />,
    );

    fireEvent.mouseEnter(container.querySelector('[data-status-segment="fail"]')!);
    await waitFor(() => {
      expect(document.body.textContent).toContain("失败 2（67%）");
    });

    fireEvent.mouseEnter(screen.getByText("通过 1"));
    await waitFor(() => {
      expect(document.body.textContent).toContain("通过 1（33%）");
    });
  });

  it("关注状态计数使用文本安全色，通过 / 跳过保持中性次要色", () => {
    const { container } = render(
      <StatusDistribution stats={makeStats({ total: 4, pass: 2, warn: 1, fail: 1 })} />,
    );

    const color = (key: string) =>
      container.querySelector<HTMLElement>(`[data-status-count="${key}"]`)?.style.color;

    // 文本安全色（FR-019、SC-006、R13）：告警 gold-8、失败 red-8。
    expect(color("warn")).toBe("rgb(135, 77, 0)");
    expect(color("fail")).toBe("rgb(207, 19, 34)");
    expect(color("pass")).toBe("");
  });

  it("异常分段与圆点携带颜色以外的冗余标识钩子", () => {
    const { container } = render(
      <StatusDistribution stats={makeStats({ total: 2, fail: 1, error: 1 })} />,
    );

    expect(container.querySelector('[data-status-segment="error"]')).not.toBeNull();
    expect(container.querySelector('[data-status-dot="error"]')).not.toBeNull();
  });

  it("概览场景弱化通过与跳过填充色，关注状态保持标准色", () => {
    const { container } = render(
      <StatusDistribution
        stats={makeStats({ total: 4, pass: 2, warn: 1, skip: 1 })}
        emphasis="overview"
      />,
    );

    const background = (key: string) =>
      container.querySelector<HTMLElement>(`[data-status-segment="${key}"]`)?.style.background;

    expect(background("pass")).toBe("rgb(183, 235, 143)");
    expect(background("skip")).toBe("rgb(145, 202, 255)");
    expect(background("warn")).toBe("rgb(250, 173, 20)");
  });
});
