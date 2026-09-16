import { expect, test } from "@playwright/test";

test("KPI 详情按分组展示并可追溯派生指标和原始记录", async ({ page }) => {
  const recordsResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v2/tasks/task-kpi-e2e/rules/kpi.call/kpi/records") &&
      response.request().method() === "GET",
  );

  await page.goto("/tasks/task-kpi-e2e/rules/kpi.call");

  const focusPanel = page.getByRole("tabpanel", { name: "重点关注（1）" });
  const allPanel = page.getByRole("tabpanel", { name: "全部指标（2）" });

  await expect(focusPanel.getByText("呼叫成功率")).toBeVisible();
  await expect(page.getByText("异常指标")).toBeVisible();
  await expect(page.getByText("重点关注（1）")).toBeVisible();
  await expect(page.getByText("全部指标（2）")).toBeVisible();
  await expect(page.getByText("1 个未登记指标")).toBeVisible();

  await page.getByText("全部指标（2）").click();
  await expect(allPanel.getByText("呼叫请求次数")).toBeVisible();
  await allPanel.getByText("呼叫请求次数").click();
  await expect(page.getByText("查看原始记录")).toBeHidden();
  await page.keyboard.press("Escape");
  await page.getByText("重点关注（1）").click();
  await focusPanel.getByText("呼叫成功率").click();

  await expect(page.getByText("call_success_count / call_attempts * 100")).toBeVisible();
  await expect(page.getByText("call_success_count", { exact: true })).toBeVisible();
  await expect(page.getByText("kpi/kpi-call-5.csv").first()).toBeVisible();
  const recordsResponse = await recordsResponsePromise;
  expect(recordsResponse.status()).toBe(200);
  await expect(page.getByText("kpi/kpi-call-5.csv").first()).toBeVisible();
});

test("KPI 页搜索筛选和记录追溯无接口或运行时错误", async ({ page }) => {
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

  await page.goto("/tasks/task-kpi-e2e/rules/kpi.call");
  await expect(page.getByRole("tabpanel", { name: "重点关注（1）" }).getByText("呼叫成功率")).toBeVisible();

  await page.getByText("全部指标（2）").click();
  const allPanel = page.getByRole("tabpanel", { name: "全部指标（2）" });
  await page.getByPlaceholder("搜索中文名、英文名、key 或别名").fill("成功率");
  await expect(allPanel.getByText("呼叫成功率")).toBeVisible();
  await expect(allPanel.getByText("呼叫请求次数")).toBeHidden();
  await page.getByPlaceholder("搜索中文名、英文名、key 或别名").fill("");

  await page.locator(".ant-select").nth(0).click();
  await page.getByTitle("失败").click();
  await expect(allPanel.getByText("呼叫成功率")).toBeVisible();
  await expect(allPanel.getByText("呼叫请求次数")).toBeHidden();

  await allPanel.getByText("呼叫成功率").click();
  await expect(page.getByText("call_success_count / call_attempts * 100")).toBeVisible();
  await expect(page.getByText("共 2 条")).toBeVisible();
  await page.keyboard.press("Escape");

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
});
