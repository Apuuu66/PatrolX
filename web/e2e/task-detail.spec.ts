import { expect, test } from "@playwright/test";

test("旧任务详情页从内嵌结果渲染规则列表", async ({ page }) => {
  const systemResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v2/tasks/task-legacy-e2e/system") &&
      response.request().method() === "GET",
  );

  await page.goto("/tasks/task-legacy-e2e");

  const systemResponse = await systemResponsePromise;
  expect(systemResponse.status()).toBe(200);

  await expect(page.getByText("旧版本任务").first()).toBeVisible();
  await page.getByRole("button", { name: "collapsed 日志" }).click();
  await expect(page.getByText("日志错误密度")).toBeVisible();
  await expect(page.getByText("无异常")).toBeVisible();
  await expect(page.getByText("巡检完成，未发现需要重点处理的规则")).toBeVisible();
  await expect(page.getByText("全部规则")).toBeVisible();
});
