import { expect, test, type Page } from "@playwright/test";

const UMF_TASK_ID = "KPI-V6-UMF-TASK";
const FUTURE_TASK_ID = "task-kpi-v6-scope-future";
const UNIT_NAME = "媒体与数据通道呼叫统计";
const CANDIDATE_SOURCE_NAME = "待人工确认来源列";
const RECOVERY_NOTICE = "只影响后续巡检，现有配置、团队关注和历史结果保留";

async function loginAdmin(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

async function authorizationHeaders(page: Page): Promise<{ Authorization: string }> {
  const token = await page.evaluate(() => localStorage.getItem("patrolx_token"));
  expect(token).toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function taskSummary(page: Page, headers: { Authorization: string }, taskId: string) {
  const response = await page.request.get(`/api/v6/kpi/tasks/${taskId}/summary`, { headers });
  expect(response.status()).toBe(200);
  return (await response.json()) as {
    counts: {
      all_metric_count: number;
      team_focus_count: number;
    };
  };
}

async function waitForTaskCompletion(
  page: Page,
  headers: { Authorization: string },
  taskId: string,
) {
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/v2/tasks/${taskId}`, { headers });
      if (!response.ok()) return `http_${response.status()}`;
      return ((await response.json()) as { status: string }).status;
    }, { timeout: 90_000 })
    .toBe("completed");
}

test("测量单元是唯一巡检开关，恢复和异常修正不改写历史结果", async ({ page }) => {
  test.setTimeout(150_000);
  await loginAdmin(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const headers = await authorizationHeaders(page);
  const summaryBefore = await taskSummary(page, headers, UMF_TASK_ID);
  expect(summaryBefore.counts.all_metric_count).toBe(20);
  expect(summaryBefore.counts.team_focus_count).toBe(10);

  await page.goto("/measurement-units");
  await expect(page.getByRole("tab", { name: "测量单元" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "关注指标" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /批量确认/ })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "查看团队关注" })).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(1);
  await expect(page.getByText("20 基础")).toBeVisible();
  await expect(page.getByText("0 派生")).toBeVisible();

  const disableSwitch = page.getByRole("switch", { name: `停用 ${UNIT_NAME}` });
  const disableResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      new URL(response.url()).pathname.startsWith("/api/v6/kpi/measurement-units/UMF/"),
  );
  await disableSwitch.click();
  expect((await disableResponse).status()).toBe(200);
  await expect(page.getByRole("switch", { name: `启用 ${UNIT_NAME}` })).toBeVisible();
  await expect(page.getByText(RECOVERY_NOTICE)).toBeVisible();
  await expect(
    page.locator(".ant-message").getByText("测量单元已停用"),
  ).toBeVisible();

  const summaryAfterDisable = await taskSummary(page, headers, UMF_TASK_ID);
  expect(summaryAfterDisable).toEqual(summaryBefore);

  await page.goto(`/tasks/${UMF_TASK_ID}/kpi`);
  const viewTabs = page.getByRole("tablist", { name: "KPI 结果视图" });
  await viewTabs.getByRole("tab", { name: /全部指标/ }).click();
  await expect(page.getByTestId("kpi-result-visible-total")).toContainText(
    "当前可见 20 / 视图总计 20 项",
  );
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(20);

  const rebuildResponse = await page.request.post(`/api/v2/tasks/${FUTURE_TASK_ID}/rebuild`, {
    headers,
    data: { mode: "full", confirmed: true },
  });
  expect(rebuildResponse.status()).toBe(202);
  await waitForTaskCompletion(page, headers, FUTURE_TASK_ID);
  const futureSummary = await taskSummary(page, headers, FUTURE_TASK_ID);
  expect(futureSummary.counts.all_metric_count).toBe(0);
  expect(await taskSummary(page, headers, UMF_TASK_ID)).toEqual(summaryBefore);

  await page.goto("/measurement-units");
  await page.getByRole("tab", { name: "恢复与归属" }).click();
  const retry = page.getByRole("button", { name: `重试失败恢复项（1）` });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.getByText("历史恢复项已重试完成")).toBeVisible();
  await expect(page.getByText("成功 1")).toBeVisible();
  await expect(page.getByText("恢复成功")).toBeVisible();

  await page.getByRole("tab", { name: "绑定关系" }).click();
  const search = page.getByRole("searchbox", { name: "搜索绑定关系" });
  await search.fill(CANDIDATE_SOURCE_NAME);
  await search.press("Enter");
  const candidateRow = page.getByRole("row").filter({ hasText: CANDIDATE_SOURCE_NAME });
  await expect(candidateRow).toBeVisible();
  await expect(candidateRow).toContainText("候选");
  await candidateRow.getByRole("button", { name: "人工修正" }).click();

  const correction = page.getByRole("dialog", { name: "单条修正绑定异常" });
  await expect(correction).toContainText(CANDIDATE_SOURCE_NAME);
  await correction
    .getByPlaceholder("例如：人工核对源列后确认归属")
    .fill("E2E 人工核对源列后确认归属");
  await correction.getByRole("button", { name: "确认修正" }).click();
  await expect(
    page.locator(".ant-message").getByText("绑定异常已确认为有效"),
  ).toBeVisible();
  await expect(candidateRow).toContainText("已确认");

  await page.getByRole("tab", { name: "测量单元" }).click();
  const enableSwitch = page.getByRole("switch", { name: `启用 ${UNIT_NAME}` });
  await expect(enableSwitch).toBeVisible();
  const enableResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      new URL(response.url()).pathname.startsWith("/api/v6/kpi/measurement-units/UMF/"),
  );
  await enableSwitch.click();
  expect((await enableResponse).status()).toBe(200);
  await expect(page.getByRole("switch", { name: `停用 ${UNIT_NAME}` })).toBeVisible();
});
