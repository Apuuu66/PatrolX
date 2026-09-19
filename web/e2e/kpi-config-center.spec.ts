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
  await dialog.getByLabel("指标 Key").fill("me_max_concurrency");
  await dialog.getByText("求和 (sum)").click();
  await page.getByTitle("最小值 (min)").click();
  await dialog.getByLabel("单位").fill("个");
  await dialog.getByRole("button", { name: /保\s?存/ }).click();
  const formulaCard = page.locator(".ant-card").filter({ hasText: "指标聚合与公式" });
  await expect(formulaCard.getByRole("row", { name: /me_max_concurrency/ })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("tab", { name: "阈值" }).click();
  await page.getByRole("button", { name: "新增阈值" }).click();
  await dialog.getByLabel("指标 Key").fill("me_max_concurrency");
  await dialog.getByLabel("阈值名称").fill("最大并发下限");
  await dialog.getByLabel("单位").fill("个");
  await dialog.getByLabel("默认阈值").fill("1000");
  await dialog.getByLabel("5 分钟", { exact: true }).fill("900");
  await dialog.getByRole("button", { name: /保\s?存/ }).click();
  const thresholdCard = page.locator(".ant-card").filter({ hasText: "阈值规则" });
  await expect(thresholdCard.getByRole("row", { name: /me_max_concurrency 最大并发下限/ })).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole("tab", { name: "配置审计" }).click();
  const auditCard = page.locator(".ant-card").filter({ hasText: "动态配置审计" });
  await expect(
    auditCard.getByRole("row", { name: /me_max_concurrency.*(upsert|create).*kpi-config-e2e/ }).first(),
  ).toBeVisible();
});
