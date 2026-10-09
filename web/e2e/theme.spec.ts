import { expect, test } from "@playwright/test";

test("全局主题使用统一主色和圆角", async ({ page }) => {
  await page.goto("/");
  const primaryButton = page.locator(".page-header").getByRole("button", { name: "上传数据包" });

  await expect(primaryButton).toBeVisible();
  await expect(primaryButton).toHaveCSS("background-color", "rgb(22, 119, 255)");
  await expect(primaryButton).toHaveCSS("border-radius", "8px");
});

test("布局在 1280px 与 1920px 下符合宽度约束", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect(page.locator(".page-header")).toBeVisible();
  const narrow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(narrow.scrollWidth).toBeLessThanOrEqual(narrow.clientWidth);

  await page.setViewportSize({ width: 1920, height: 900 });
  const wide = await page.evaluate(() => {
    const inner = document.querySelector(".ant-layout-content .app-shell-inner");
    const header = document.querySelector(".app-shell-header");
    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      contentWidth: Math.round(inner?.getBoundingClientRect().width ?? 0),
      contentLeft: Math.round(inner?.getBoundingClientRect().left ?? 0),
      headerLeft: Math.round(header?.getBoundingClientRect().left ?? 0),
    };
  });
  expect(wide.scrollWidth).toBeLessThanOrEqual(wide.clientWidth);
  // 1920px 下内容不被无限拉伸，且页头与内容区左边缘对齐。
  expect(wide.contentWidth).toBeLessThanOrEqual(1600);
  expect(wide.headerLeft).toBe(wide.contentLeft);
});
test("关注状态文字满足 WCAG AA 对比度", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/tasks/task-alarm-flapping-e2e");

  const warnCount = page.locator('[data-status-count="warn"]').first();
  await expect(warnCount).toBeVisible();

  const ratio = await warnCount.evaluate((node) => {
    const channels = (value: string) =>
      (value.match(/[\d.]+/g) ?? []).slice(0, 3).map((part) => Number.parseFloat(part));
    const linear = (value: number) => {
      const scaled = value / 255;
      return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (rgb: number[]) =>
      0.2126 * linear(rgb[0] ?? 0) + 0.7152 * linear(rgb[1] ?? 0) + 0.0722 * linear(rgb[2] ?? 0);

    // 计数文字位于卡片 / 页面浅色底之上，向上找到第一个不透明背景作为比较基准。
    let background = "rgb(255, 255, 255)";
    let current: HTMLElement | null = node as HTMLElement;
    while (current) {
      const value = getComputedStyle(current).backgroundColor;
      const alpha = (value.match(/[\d.]+/g) ?? [])[3];
      if (value !== "rgba(0, 0, 0, 0)" && (alpha === undefined || Number.parseFloat(alpha) > 0.9)) {
        background = value;
        break;
      }
      current = current.parentElement;
    }

    const foregroundLuminance = luminance(channels(getComputedStyle(node).color));
    const backgroundLuminance = luminance(channels(background));
    const lighter = Math.max(foregroundLuminance, backgroundLuminance);
    const darker = Math.min(foregroundLuminance, backgroundLuminance);
    return (lighter + 0.05) / (darker + 0.05);
  });

  expect(ratio).toBeGreaterThanOrEqual(4.5);
});

test("异常在分布条与状态标签上带颜色以外的冗余标识", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 任务列表：异常=1 的任务行分段条使用斜纹（FR-019、SC-006、R13）。
  const errorSegment = page.locator('[data-status-segment="error"]').first();
  await expect(errorSegment).toBeVisible();
  const segmentBackground = await errorSegment.evaluate(
    (node) => getComputedStyle(node).backgroundImage,
  );
  expect(segmentBackground).toContain("repeating-linear-gradient");

  // 规则详情：异常状态标签同时使用虚框 + 斜纹。
  await page.goto("/tasks/task-home-failed/rules/log.error_density");
  const errorTag = page.locator(".rule-status-tag-error");
  await expect(errorTag).toBeVisible();
  expect(await errorTag.evaluate((node) => getComputedStyle(node).backgroundImage)).toContain(
    "repeating-linear-gradient",
  );
  expect(await errorTag.evaluate((node) => getComputedStyle(node).borderStyle)).toBe("dashed");
});
