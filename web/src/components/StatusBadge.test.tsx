import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { STATUS_TEXT_COLORS, contrastRatio } from "../utils/statusTextColors";

/** jsdom 会把内联十六进制颜色规范化为 rgb(...)，断言前统一转换。 */
function toRgbString(hex: string): string {
  const value = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((index) => Number.parseInt(value.slice(index, index + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
}
import { RuleStatusTag, SeverityTag, TaskStatusTag } from "./StatusBadge";

describe("SeverityTag", () => {
  it("默认渲染彩色 Tag", () => {
    const { container } = render(<SeverityTag severity="critical" />);
    const tag = container.querySelector(".ant-tag");
    expect(tag?.textContent).toBe("严重");
    expect(screen.getByText("严重")).toBeDefined();
  });

  it("plain 变体渲染色点 + 文字，并携带 title 与 aria-label", () => {
    const { container } = render(<SeverityTag severity="high" variant="plain" />);

    const plain = container.querySelector(".severity-plain");
    expect(plain?.textContent).toBe("高");
    expect(plain?.getAttribute("aria-label")).toBe("严重程度：高");
    expect(plain?.getAttribute("title")).toBe("严重程度：高");
    expect(plain?.getAttribute("data-severity")).toBe("high");
    expect(screen.queryByRole("img")).toBeNull();
    // 不再使用彩色 Tag，避免与状态标签争注意力（FR-013、R10）。
    expect(container.querySelector(".ant-tag")).toBeNull();

    const dot = container.querySelector(".severity-plain-dot");
    expect(dot?.getAttribute("aria-hidden")).toBe("true");
  });

  it("未知严重度回退原值", () => {
    render(<SeverityTag severity="unknown" variant="plain" />);
    expect(screen.getByLabelText("严重程度：unknown")).toBeDefined();
  });
});

describe("规则与任务状态标签", () => {
  it("skip 带原因时以 tooltip 承载原因", () => {
    const { container } = render(<RuleStatusTag status="skip" skipReason="source_patterns 未匹配" />);
    expect(container.querySelector(".ant-badge")?.textContent).toContain("跳过");
    expect(container.querySelector("[title='source_patterns 未匹配']")).toBeDefined();
  });

  it("任务状态使用中文标签", () => {
    const { container } = render(<TaskStatusTag status="completed" />);
    expect(container.textContent).toContain("已完成");
  });

  it("状态标签文字使用文本安全色（AARG 4.5:1）", () => {
    for (const status of ["pass", "warn", "fail", "skip", "error"]) {
      const { container, unmount } = render(<RuleStatusTag status={status} />);
      const tag = container.querySelector<HTMLElement>(".rule-status-tag");
      const color = tag?.style.color ?? "";
      const safeColor = STATUS_TEXT_COLORS[status as keyof typeof STATUS_TEXT_COLORS];
      expect(color.toLowerCase()).toBe(toRgbString(safeColor));
      expect(contrastRatio(safeColor, "#ffffff")).toBeGreaterThanOrEqual(4.5);
      unmount();
    }
  });

  it("异常标签挂载颜色以外的冗余样式钩子（斜纹见 theme.css / E2E 断言）", () => {
    const { container } = render(<RuleStatusTag status="error" />);
    expect(container.querySelector(".rule-status-tag-error")).not.toBeNull();
    // 异常文字使用中性灰安全色，与"仅靠灰色表达"的斜纹冗余配套（FR-019、R13）。
    expect(container.querySelector<HTMLElement>(".rule-status-tag-error")?.style.color).toBe(
      toRgbString("#595959"),
    );
  });
});
