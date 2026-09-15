import { expect, test } from "@playwright/test";

test("KPI 详情按分组展示并可追溯派生指标和原始记录", async ({ page }) => {
  const recordsResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v2/tasks/task-kpi-e2e/rules/kpi.call/kpi/records") &&
      response.request().method() === "GET",
  );

  await page.goto("/tasks/task-kpi-e2e/rules/kpi.call");

  await expect(page.getByText("呼叫成功率")).toBeVisible();
  await expect(page.getByText("1 个重点 · 1 次越限")).toBeVisible();
  await expect(page.getByText("1 个未登记指标")).toBeVisible();
  await expect(page.getByText("呼叫请求次数")).toBeVisible();

  await page.getByText("呼叫请求次数").click();
  await expect(page.getByText("查看原始记录")).toBeHidden();
  await page.keyboard.press("Escape");
  await page.getByText("呼叫成功率").click();

  await expect(page.getByText("call_success_count / call_attempts * 100")).toBeVisible();
  await expect(page.getByText("call_success_count", { exact: true })).toBeVisible();
  await expect(page.getByText("kpi/kpi-call-5.csv").first()).toBeVisible();
  const recordsResponse = await recordsResponsePromise;
  expect(recordsResponse.status()).toBe(200);
  await expect(page.getByText("kpi/kpi-call-5.csv").first()).toBeVisible();
});
