import { expect, test } from "@playwright/test";

test("任务首页展示完成耗时、设备元数据和失败日志入口", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("耗时 1 小时 30 分钟")).toBeVisible();
  const taskCard = page
    .locator(".ant-card:not(:has(.ant-card))")
    .filter({ hasText: "task-home-failed" });
  await expect(taskCard).toHaveCount(1);
  await expect(taskCard.getByText("设备 ID")).toBeVisible();
  await expect(taskCard.getByText("home-device-001")).toBeVisible();
  await expect(taskCard.locator("code", { hasText: "task-home-failed" })).toHaveCSS(
    "color",
    "rgba(0, 0, 0, 0.65)",
  );
  await expect(taskCard.getByText("省份", { exact: true })).toHaveCSS("color", "rgba(0, 0, 0, 0.65)");
  await expect(taskCard.getByText("江苏", { exact: true })).toHaveCSS("color", "rgba(0, 0, 0, 0.88)");

  await taskCard.getByRole("button", { name: "失败日志" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed\/logs$/);
  await expect(page.getByText("任务执行失败：解析主清单失败")).toBeVisible();
});
