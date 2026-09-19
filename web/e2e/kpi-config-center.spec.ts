import { expect, test } from "@playwright/test";

test("KPI 配置中心可维护公式、阈值并查看配置审计", async ({ page }) => {
  await page.goto("/kpi-resources");
  await page.getByPlaceholder("操作人").fill("kpi-config-e2e");
  await expect(page.getByRole("tab", { name: "指标公式" })).toBeVisible();

  const resourceRow = page.getByRole("row", { name: /ME_MAX_CONCURRENCY/ });
  await resourceRow.getByRole("checkbox").check();
  await page.locator(".ant-select").nth(1).click();
  await page.getByTitle("呼叫", { exact: true }).click();
  await page.getByRole("button", { name: /批量分类/ }).click();
  await expect(resourceRow.getByText("呼叫", { exact: true })).toBeVisible({ timeout: 10_000 });

  const dialog = page.locator(".ant-modal:visible");
  await page.getByRole("button", { name: "新增指标口径" }).click();
  const formulaMetricInput = dialog.getByRole("combobox", { name: "* 指标", exact: true });
  await formulaMetricInput.click();
  await formulaMetricInput.fill("最大并发");
  const formulaMetricOption = page.locator(".ant-select-item-option").filter({ hasText: "最大并发" });
  await expect(formulaMetricOption).toBeVisible();
  await expect(formulaMetricOption.getByText("me_max_concurrency")).toBeVisible();
  await formulaMetricInput.press("Enter");
  const aggregationSelect = dialog
    .locator(".ant-form-item")
    .filter({ hasText: "聚合公式" })
    .locator(".ant-select");
  await aggregationSelect.click();
  await page.locator(".ant-select-item-option").filter({ hasText: "最小值 (min)" }).click();
  await dialog.getByLabel("单位").fill("个");
  await dialog.getByRole("button", { name: /保\s?存/ }).click();
  const formulaCard = page.locator(".ant-card").filter({ hasText: "指标聚合与公式" });
  await expect(formulaCard.getByRole("row", { name: /me_max_concurrency/ })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("tab", { name: "阈值" }).click();
  await page.getByRole("button", { name: "新增阈值" }).click();
  const thresholdMetricInput = dialog.getByTestId("threshold-metric-select").getByRole("combobox");
  await thresholdMetricInput.click();
  await thresholdMetricInput.fill("最大并发");
  const thresholdMetricOption = page.getByTitle("最大并发").last();
  await expect(thresholdMetricOption).toBeVisible();
  await expect(thresholdMetricOption.getByText("me_max_concurrency")).toBeVisible();
  await thresholdMetricInput.press("Enter");
  await dialog.getByLabel("阈值名称").fill("最大并发下限");
  await dialog.getByLabel("单位").fill("个");
  await dialog.getByLabel("默认阈值").fill("1000");
  await dialog.getByLabel("5 分钟", { exact: true }).fill("900");
  await dialog.getByRole("button", { name: /保\s?存/ }).click();
  const thresholdCard = page.locator(".ant-card").filter({ hasText: "阈值规则" });
  await expect(thresholdCard.getByRole("row", { name: /最大并发.*最大并发下限/ })).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole("tab", { name: "配置审计" }).click();
  const auditCard = page.locator(".ant-card").filter({ hasText: "动态配置审计" });
  await expect(
    auditCard.getByRole("row", { name: /me_max_concurrency.*(upsert|create).*kpi-config-e2e/ }).first(),
  ).toBeVisible();
});
