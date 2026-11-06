import { expect, test } from "@playwright/test";

async function loginAdmin(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

test("表格列宽支持拖拽调整并持久到当前页面交互", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/inspectors");
  await expect(page.getByRole("row").filter({ hasText: "kpi.measurement_units" })).toBeVisible();

  const codeHeader = page.getByRole("columnheader", { name: "规则编码" });
  const handle = codeHeader.locator(".column-resize-handle");
  await expect(handle).toHaveAttribute("data-column-width", "220");
  const initialBox = await codeHeader.boundingBox();
  expect(initialBox).not.toBeNull();

  const box = await handle.boundingBox();
  expect(box).not.toBeNull();

  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 80, box!.y + box!.height / 2, { steps: 4 });
  await page.mouse.up();

  await expect(handle).toHaveAttribute("data-column-width", "300");
  await expect
    .poll(async () => (await codeHeader.boundingBox())?.width ?? 0)
    .toBeGreaterThan(initialBox!.width + 70);
});
