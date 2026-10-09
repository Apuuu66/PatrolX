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
