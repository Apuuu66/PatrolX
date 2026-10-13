import { expect, test } from "@playwright/test";

test("侧边栏基础指标和数据字典使用不同图标", async ({ page }) => {
  await page.goto("/");

  const metricsItem = page.getByRole("menuitem", { name: "基础指标" });
  const dictsItem = page.getByRole("menuitem", { name: "数据字典" });

  await expect(metricsItem.locator('[aria-label="fund"]')).toBeVisible();
  await expect(dictsItem.locator('[aria-label="database"]')).toBeVisible();
});

test("侧边栏为深色导航，选中态用左侧指示条 + 白字加粗表达", async ({ page }) => {
  await page.goto("/inspectors");

  const sider = page.locator(".app-sider");
  await expect(sider).toBeVisible();
  // 深色导航：整块深底与浅色内容区分区，品牌与菜单文字保持白系。
  await expect(sider).toHaveClass(/ant-layout-sider-dark/);
  await expect(sider).toHaveCSS("background-color", "rgb(0, 21, 41)");
  await expect(sider.locator(".app-sider-brand")).toHaveCSS("color", "rgb(255, 255, 255)");

  const selected = sider.locator(".ant-menu-item-selected");
  await expect(selected).toHaveCount(1);
  await expect(selected).toContainText("规则管理");
  await expect(selected).toHaveCSS("background-color", "rgba(255, 255, 255, 0.12)");
  await expect(selected).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(selected).toHaveCSS("font-weight", "600");

  const indicator = await selected.evaluate((node) => {
    const style = getComputedStyle(node, "::before");
    return { width: style.width, background: style.backgroundColor };
  });
  expect(indicator.width).toBe("3px");
  expect(indicator.background).toBe("rgb(22, 119, 255)");

  // 未选中项保持白系中性文字色，并在深色底上满足 WCAG AA 4.5:1。
  const unselected = sider.locator(".ant-menu-item").filter({ hasText: "数据字典" });
  await expect(unselected).toHaveCSS("color", "rgba(255, 255, 255, 0.65)");
  const ratio = await unselected.evaluate((node) => {
    const numbers = (value: string) => (value.match(/[\d.]+/g) ?? []).map(Number);
    const channels = (value: string) => numbers(value).slice(0, 3);
    const alpha = (value: string) => numbers(value)[3] ?? 1;
    const linear = (value: number) => {
      const scaled = value / 255;
      return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (rgb: number[]) =>
      0.2126 * linear(rgb[0] ?? 0) + 0.7152 * linear(rgb[1] ?? 0) + 0.0722 * linear(rgb[2] ?? 0);

    // 文字与底色都可能半透明：向上取第一个不透明背景，再按 alpha 合成前景。
    let background = "rgb(255, 255, 255)";
    let current: HTMLElement | null = node as HTMLElement;
    while (current) {
      const value = getComputedStyle(current).backgroundColor;
      if (value !== "rgba(0, 0, 0, 0)" && alpha(value) > 0.9) {
        background = value;
        break;
      }
      current = current.parentElement;
    }
    const foreground = getComputedStyle(node).color;
    const backdrop = channels(background);
    const foregroundAlpha = alpha(foreground);
    const composited = channels(foreground).map(
      (channel, index) => channel * foregroundAlpha + (backdrop[index] ?? 0) * (1 - foregroundAlpha),
    );

    const foregroundLuminance = luminance(composited);
    const backgroundLuminance = luminance(backdrop);
    const lighter = Math.max(foregroundLuminance, backgroundLuminance);
    const darker = Math.min(foregroundLuminance, backgroundLuminance);
    return (lighter + 0.05) / (darker + 0.05);
  });
  expect(ratio).toBeGreaterThanOrEqual(4.5);
});
