import { expect, test } from "@playwright/test";

test("侧边栏基础指标和数据字典使用不同图标", async ({ page }) => {
  await page.goto("/");

  const metricsItem = page.getByRole("menuitem", { name: "基础指标" });
  const dictsItem = page.getByRole("menuitem", { name: "数据字典" });

  await expect(metricsItem.locator('[aria-label="fund"]')).toBeVisible();
  await expect(dictsItem.locator('[aria-label="database"]')).toBeVisible();
});
