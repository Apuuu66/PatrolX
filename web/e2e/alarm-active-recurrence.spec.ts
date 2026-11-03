import { expect, test } from "@playwright/test";

const TASK_ID = "task-alarm-active-recurrence-e2e";

function collectPageErrors(page: import("@playwright/test").Page) {
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
  return { consoleErrors, pageErrors, apiErrors };
}

test("从任务详情区分未清除活动风险与反复上报风险", async ({ page }) => {
  const { consoleErrors, pageErrors, apiErrors } = collectPageErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto(`/tasks/${TASK_ID}`);
  const attention = page.getByTestId("attention-panel");
  await expect(attention).toContainText("未清除告警巡检");
  await expect(attention).toContainText("告警反复上报巡检");

  await attention.getByText("未清除告警巡检", { exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${TASK_ID}/rules/alarm\\.active_state$`));
  await expect(page.getByText("规则编码：alarm.active_state")).toBeVisible();

  const activeSummary = page.getByTestId("alarm-active-summary");
  await expect(activeSummary).toContainText("最高严重级 紧急");
  await expect(activeSummary).toContainText("活动记录 2");
  await expect(activeSummary).toContainText("活动分组 2");
  await expect(activeSummary).toContainText("原始 Repeat Times 30 次");
  await expect(activeSummary).toContainText("估算上报 32 次");
  await expect(activeSummary).toContainText("单条最大重复 24");
  await expect(activeSummary).toContainText("估算口径：Σ(1 + Repeat Times)，不是精确事件总数");
  await expect(activeSummary).toContainText("coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻");
  await expect(page.getByTestId("alarm-active-groups")).toContainText("NTP 同步失败");
  await expect(page.getByTestId("alarm-active-groups")).toContainText("pod-umf-9");
  await expect(page.getByTestId("alarm-active-status-counts")).toContainText("未清除 2");

  await page.goto(`/tasks/${TASK_ID}`);
  await page.getByTestId("attention-panel").getByText("告警反复上报巡检", { exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${TASK_ID}/rules/alarm\\.recurrence$`));
  await expect(page.getByText("规则编码：alarm.recurrence")).toBeVisible();

  const recurrenceSummary = page.getByTestId("alarm-recurrence-summary");
  await expect(recurrenceSummary).toContainText("有效生命周期 6");
  await expect(recurrenceSummary).toContainText("告警类型 2");
  await expect(recurrenceSummary).toContainText("原始 Repeat Times 38 次");
  await expect(recurrenceSummary).toContainText("估算上报 44 次");
  await expect(recurrenceSummary).toContainText("Reset Cleared 1");
  await expect(recurrenceSummary).toContainText("双计数口径：原始 Repeat Times 为 Σ Repeat Times");
  await expect(recurrenceSummary).toContainText("估算上报为 Σ(1 + Repeat Times)，不是精确事件总数");

  const recurrenceTypes = page.getByTestId("alarm-recurrence-types");
  await expect(recurrenceTypes).toContainText("iBMC 连接失败");
  await expect(recurrenceTypes).toContainText("快速复发");
  await expect(recurrenceTypes).toContainText("Reset Cleared");
  await expect(page.getByText("Reset Cleared 不代表稳定恢复", { exact: true })).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
