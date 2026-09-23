import { expect, test } from "@playwright/test";

const TASK_ID = "task-kpi-history-current";

test("测量单元支持完整趋势和历史对比维度选择", async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const apiErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      apiErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto(`/tasks/${TASK_ID}/rules/kpi.measurement_units`);
  await expect(page.getByText("呼叫统计")).toBeVisible();

  const detailResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v2/tasks/${TASK_ID}/rules/kpi.measurement_units/measurement-units/MU_CALL/metrics/ME_CALL`,
      ) && response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "查看呼叫请求次数完整趋势" }).click();
  const detailResponse = await detailResponsePromise;
  expect(detailResponse.status()).toBe(200);

  const historyResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v2/tasks/${TASK_ID}/rules/kpi.measurement_units/measurement-units/MU_CALL/metrics/ME_CALL/history-trend`,
      ) && response.request().method() === "GET",
  );
  await page.getByRole("tab", { name: "历史对比" }).click();
  const historyResponse = await historyResponsePromise;
  expect(historyResponse.status()).toBe(200);

  const historyUrl = new URL(historyResponse.url());
  expect(historyUrl.searchParams.get("object_key")).toBe("pod-a");
  expect(historyUrl.searchParams.get("period_minutes")).toBe("15");

  await expect(page.getByText("设备 demo-device-001")).toBeVisible();
  await expect(page.getByText("历史 3 天")).toBeVisible();
  await expect(page.locator("canvas").first()).toHaveCount(1);
  const canvasWidth = Number(await page.locator("canvas").first().getAttribute("width"));
  expect(canvasWidth).toBeGreaterThan(300);

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
