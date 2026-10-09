import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DensitySegmented } from "./DensitySegmented";

describe("DensitySegmented", () => {
  it("呈现紧凑与舒适两态并标记当前选择", () => {
    render(<DensitySegmented value="compact" onChange={() => undefined} />);

    const compact = screen.getByRole("button", { name: "紧凑" });
    const comfortable = screen.getByRole("button", { name: "舒适" });

    expect(compact.getAttribute("aria-pressed")).toBe("true");
    expect(comfortable.getAttribute("aria-pressed")).toBe("false");
  });

  it("点击另一态触发切换回调", async () => {
    const onChange = vi.fn();
    render(<DensitySegmented value="compact" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "舒适" }));

    expect(onChange).toHaveBeenCalledWith("comfortable");
  });

  it("可键盘操作且分组有可读名称", async () => {
    const onChange = vi.fn();
    render(<DensitySegmented value="compact" onChange={onChange} />);

    expect(screen.getByRole("group", { name: "表格密度" })).toBeDefined();

    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("comfortable");
  });

  it("不改变筛选与分页：只回调密度值", async () => {
    const onChange = vi.fn();
    render(<DensitySegmented value="comfortable" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "紧凑" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("compact");
  });
});
