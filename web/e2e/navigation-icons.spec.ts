import { expect, test } from "@playwright/test";

test("侧边栏基础指标和数据字典使用不同图标", async ({ page }) => {
  await page.goto("/");

  const metricsItem = page.getByRole("menuitem", { name: "基础指标" });
  const dictsItem = page.getByRole("menuitem", { name: "数据字典" });

  await expect(metricsItem.locator('[aria-label="fund"]')).toBeVisible();
  await expect(dictsItem.locator('[aria-label="database"]')).toBeVisible();
});

test("侧边栏选中态为淡色底 + 左侧指示条 + 品牌深色文字", async ({ page }) => {
  await page.goto("/inspectors");

  const sider = page.locator(".app-sider");
  await expect(sider).toBeVisible();
  // 浅色主题：不再使用深色底整块反色。
  await expect(sider).not.toHaveClass(/ant-layout-sider-dark/);

  const selected = sider.locator(".ant-menu-item-selected");
  await expect(selected).toHaveCount(1);
  await expect(selected).toContainText("规则管理");
  await expect(selected).toHaveCSS("background-color", "rgb(240, 247, 255)");
  await expect(selected).toHaveCSS("color", "rgb(9, 88, 217)");

  const indicator = await selected.evaluate((node) => {
    const style = getComputedStyle(node, "::before");
    return { width: style.width, background: style.backgroundColor };
  });
  expect(indicator.width).toBe("3px");
  expect(indicator.background).toBe("rgb(22, 119, 255)");

  // 未选中项保持中性文字色，避免整块实心主色。
  await expect(sider.locator(".ant-menu-item").filter({ hasText: "数据字典" })).toHaveCSS(
    "color",
    "rgba(0, 0, 0, 0.65)",
  );
});
