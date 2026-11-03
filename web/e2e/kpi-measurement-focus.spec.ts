import { expect, test } from "@playwright/test";

test("管理员可取消并恢复指标关注", async ({ page }) => {
  const apiErrors: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      apiErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();

  await page.goto("/measurement-units");
  await page.getByRole("tab", { name: "关注指标" }).click();
  const search = page.getByPlaceholder("搜索指标 ID / 中文名 / 英文名");
  await search.fill("关注功能测试指标");
  await search.press("Enter");

  const row = page.getByRole("row").filter({ hasText: "关注功能测试指标" });
  await expect(row.getByText("关注", { exact: true })).toBeVisible();

  const disableResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v5/kpi/measurement-resources/ME_FOCUS_E2E")
      && response.request().method() === "PATCH",
  );
  await row.getByRole("button", { name: "取消关注" }).click();
  expect((await disableResponse).status()).toBe(200);
  await expect(row.getByText("未关注", { exact: true })).toBeVisible();

  const enableResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v5/kpi/measurement-resources/ME_FOCUS_E2E")
      && response.request().method() === "PATCH",
  );
  await row.getByRole("button", { name: "关注" }).click();
  expect((await enableResponse).status()).toBe(200);
  await expect(row.getByText("关注", { exact: true })).toBeVisible();

  expect(apiErrors).toEqual([]);
});
