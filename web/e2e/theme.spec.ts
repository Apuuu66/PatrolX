import { expect, test } from "@playwright/test";

test("全局主题使用统一主色和圆角", async ({ page }) => {
  await page.goto("/");
  const primaryButton = page.getByRole("button", { name: "上传数据包" });

  await expect(primaryButton).toBeVisible();
  await expect(primaryButton).toHaveCSS("background-color", "rgb(22, 119, 255)");
  await expect(primaryButton).toHaveCSS("border-radius", "8px");
});
