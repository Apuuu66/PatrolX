import { expect, test } from "@playwright/test";

const inspectors = {
  items: [
    {
      code: "baseline.demo",
      name: "表格列宽测试",
      category: "config",
      priority: 1,
      enabled: true,
      updated_at: "2026-10-07T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

test("表格列宽支持拖拽调整并持久到当前页面交互", async ({ page }) => {
  await page.route("**/api/v2/inspector-states**", (route) => route.fulfill({ json: inspectors }));

  await page.goto("/inspectors");
  await expect(page.getByText("表格列宽测试")).toBeVisible();

  const firstCol = page.locator(".ant-table colgroup col").nth(0);
  await expect
    .poll(() => firstCol.evaluate((element) => element.style.width))
    .toBe("220px");

  const handle = page
    .locator(".ant-table-cell")
    .filter({ hasText: "规则编码" })
    .first()
    .locator('[data-testid="column-resize-handle-code"]');
  const box = await handle.boundingBox();
  expect(box).not.toBeNull();

  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 80, box!.y + box!.height / 2, { steps: 4 });
  await page.mouse.up();

  await expect
    .poll(() => firstCol.evaluate((element) => element.style.width))
    .toBe("300px");
});
