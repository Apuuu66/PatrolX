import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyTextButton } from "./CopyTextButton";

function stubClipboard(impl?: () => Promise<void>) {
  const writeText = vi.fn(impl ?? (() => Promise.resolve()));
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

describe("CopyTextButton", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  });

  it("点击后复制文本并给出可见成功反馈", async () => {
    const writeText = stubClipboard();
    render(<CopyTextButton text="output/task-001/a.log" label="来源路径" />);

    await userEvent.click(screen.getByRole("button", { name: "复制来源路径" }));

    expect(writeText).toHaveBeenCalledWith("output/task-001/a.log");
    await waitFor(() => {
      expect(screen.getByText("已复制")).toBeDefined();
    });
    expect(screen.getByRole("button", { name: "复制来源路径" }).getAttribute("data-copy-state")).toBe(
      "copied",
    );
  });

  it("剪贴板不可用时给出失败反馈并降级为可选中文本", async () => {
    stubClipboard(() => Promise.reject(new Error("denied")));
    render(<CopyTextButton text="abcdef" label="规则编码" />);

    await userEvent.click(screen.getByRole("button", { name: "复制规则编码" }));

    await waitFor(() => {
      expect(screen.getByText(/手动选择/)).toBeDefined();
    });
    expect(screen.getByText("abcdef")).toBeDefined();
  });

  it("键盘可触发复制", async () => {
    const writeText = stubClipboard();
    render(<CopyTextButton text="tar.gz" />);

    await userEvent.tab();
    await userEvent.keyboard("{Enter}");

    expect(writeText).toHaveBeenCalledWith("tar.gz");
  });

  it("点击不触发行跳转", async () => {
    stubClipboard();
    const onRowClick = vi.fn();
    render(
      <div onClick={onRowClick}>
        <CopyTextButton text="x" />
      </div>,
    );

    await userEvent.click(screen.getByRole("button", { name: "复制" }));

    expect(onRowClick).not.toHaveBeenCalled();
  });
});
