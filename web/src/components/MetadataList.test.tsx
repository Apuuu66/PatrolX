import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MetadataList, type MetadataListItem } from "./MetadataList";

function stubClipboard() {
  const writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

function makeItems(count: number): MetadataListItem[] {
  return Array.from({ length: count }, (_, index) => ({
    key: `field-${index + 1}`,
    label: `字段${index + 1}`,
    value: `值${index + 1}`,
  }));
}

describe("MetadataList", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  });

  it("空值与空白值不渲染，全部为空时整块隐藏", () => {
    const { container } = render(
      <MetadataList
        items={[
          { key: "empty", label: "空", value: "" },
          { key: "blank", label: "空白", value: "   " },
        ]}
      />,
    );

    expect(container.childElementCount).toBe(0);
    expect(container.textContent).toBe("");
  });

  it("过滤空值后只渲染有值字段", () => {
    render(
      <MetadataList
        items={[
          { key: "province", label: "省份", value: "江苏" },
          { key: "operator", label: "运营商", value: "" },
        ]}
      />,
    );

    expect(screen.getByText("江苏")).toBeDefined();
    expect(screen.queryByText("运营商")).toBeNull();
  });

  it("最多平铺 4 项，其余收进更多元数据", async () => {
    const { container } = render(<MetadataList items={makeItems(6)} />);

    const flat = container.querySelectorAll("[data-metadata-key]");
    expect(flat).toHaveLength(4);
    expect(screen.getByText("值4")).toBeDefined();
    expect(screen.queryByText("值5")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /更多元数据/ }));

    await waitFor(() => {
      expect(screen.getByText("值5")).toBeDefined();
    });
    expect(screen.getByText("值6")).toBeDefined();
  });

  it("少于等于 4 项时没有更多元数据入口", () => {
    render(<MetadataList items={makeItems(4)} />);

    expect(screen.queryByRole("button", { name: /更多元数据/ })).toBeNull();
  });

  it("完整值可复制", async () => {
    const writeText = stubClipboard();
    const longValue = "output/task-001/prepared/very-deep-path/example-metrics.csv";
    render(<MetadataList items={[{ key: "path", label: "路径", value: longValue }]} />);

    await userEvent.click(screen.getByRole("button", { name: "复制路径值" }));

    expect(writeText).toHaveBeenCalledWith(longValue);
  });
});
