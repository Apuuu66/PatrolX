import { expect, test } from "@playwright/test";

const TASK_ID = "task-kpi-history-current";
const SINGLE_POINT_METRIC = "最大注册用户数";

test("趋势点不足的指标仍可点击查看时间点明细", async ({ page }) => {
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
        `/api/v2/tasks/${TASK_ID}/rules/kpi.measurement_units/measurement-units/MU_CALL/metrics/ME_MAX_USERS`,
      ) && response.request().method() === "GET",
  );

  const trigger = page.getByRole("button", { name: `查看${SINGLE_POINT_METRIC}完整趋势` });
  await expect(trigger).toBeVisible();
  await expect(trigger).toBeEnabled();
  await trigger.click();
  expect((await detailResponsePromise).status()).toBe(200);

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("趋势点不足，无法判断趋势")).toBeVisible();
  await expect(dialog.getByText("本任务内只有 1 个时间点，至少需要 2 个时间点才能判断趋势")).toBeVisible();
  await expect(dialog.getByText("时间点明细", { exact: true })).toBeVisible();
  await expect(dialog.getByText("2026-09-20 10:00:00")).toBeVisible();
  await expect(dialog.getByText("2048 户")).toBeVisible();
  await expect(dialog.getByText("ne333_Call_Statistics_15_0_202609201000.csv:2")).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
