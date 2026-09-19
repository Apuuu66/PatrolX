import { expect, test } from "@playwright/test";

test("基础指标配置可分类基础指标并保留审计", async ({ page, request }) => {
  const listResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v3/kpi/resource-metrics") &&
      response.request().method() === "GET",
  );

  await page.goto("/kpi-resources");

  await expect(page.getByRole("menuitem", { name: "基础指标" })).toBeVisible();
  await expect(page.getByText("基础指标配置")).toBeVisible();
  await expect(page.getByText("指标总数")).toBeVisible();
  const listResponse = await listResponsePromise;
  expect(listResponse.status()).toBe(200);
  await expect(page.getByText("共 7 条").first()).toBeVisible();
  await expect(page.getByLabel("上传")).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.getByText(/(未分类|呼叫|API|媒体): /).first()).toBeVisible();

  const row = page.getByRole("row", { name: /ME_CALL_ATTEMPTS/ });
  await row.getByRole("checkbox").check();
  await page.locator(".ant-select").nth(1).click();
  await page.getByTitle("呼叫", { exact: true }).click();
  await page.getByPlaceholder("操作人").fill("kpi-resource-e2e");
  await expect(page.getByRole("tab", { name: "指标公式" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "阈值" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "容量与展示" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "公共配置" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "配置审计" })).toBeVisible();
  await page.getByRole("button", { name: /批量分类/ }).click();

  await expect(row.getByText("呼叫", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("分类审计")).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("row", { name: /ME_CALL_ATTEMPTS/ }).getByText("呼叫", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".ant-card")
      .filter({ hasText: "分类审计" })
      .getByRole("row", { name: /me_call_attempts classify kpi-resource-e2e/ }),
  ).toBeVisible();
  await expect(page.getByText("kpi-resource-e2e").first()).toBeVisible();

  const response = await request.get("/api/v3/kpi/resource-metrics/classification-audits?page=1&page_size=10");
  expect(response.status()).toBe(200);
  const audits = await response.json();
  expect(audits.total).toBeGreaterThan(0);
  expect(audits.items[0]).toMatchObject({
    metric_key: "me_call_attempts",
    operation: "classify",
    operator: "kpi-resource-e2e",
    to_domain: "call",
  });
  expect(audits.items[0].operated_at).toBeTruthy();
});
