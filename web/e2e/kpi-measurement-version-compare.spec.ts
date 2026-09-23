import { expect, test } from "@playwright/test";

const TASK_ID = "task-kpi-history-current";

test("测量单元支持同设备版本对比", async ({ page }) => {
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

  await page.getByRole("button", { name: "查看呼叫请求次数完整趋势" }).click();
  const candidatesResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v2/tasks/${TASK_ID}/rules/kpi.measurement_units/measurement-units/MU_CALL/metrics/ME_CALL/version-candidates`,
      ) && response.request().method() === "GET",
  );
  await page.getByRole("tab", { name: "版本对比" }).click();
  await expect(page.getByText("选择基线版本")).toBeVisible();
  const candidatesResponse = await candidatesResponsePromise;
  expect(candidatesResponse.status()).toBe(200);

  const compareResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v2/tasks/${TASK_ID}/rules/kpi.measurement_units/measurement-units/MU_CALL/metrics/ME_CALL/version-compare`,
      ) && response.request().method() === "GET",
  );
  await page.getByRole("combobox", { name: "基线版本" }).click();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  const compareResponse = await compareResponsePromise;
  expect(compareResponse.status()).toBe(200);

  await expect(page.getByRole("cell", { name: "当前版本 : V2" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "基线版本 : V1" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "基线任务 : task-kpi-history-past" })).toBeVisible();
  await expect(page.getByText(/上涨/)).toBeVisible();
  await expect(page.locator("canvas").first()).toHaveCount(1);

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
