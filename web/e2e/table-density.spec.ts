import { expect, test } from "@playwright/test";

/** 读取表格首行行高，用于验证密度切换真实改变行距（FR-016）。 */
async function firstRowHeight(page: import("@playwright/test").Page, rootSelector: string) {
  const row = page.locator(`${rootSelector} .ant-table-tbody > tr.ant-table-row`).first();
  await expect(row).toBeVisible();
  const box = await row.boundingBox();
  return box?.height ?? 0;
}

test("密度偏好在任务列表、任务详情与规则管理之间沿用并刷新后保持", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const taskDensity = page.locator('.task-table ~ *, [data-testid="density-control"]').first();
  await expect(page.locator('[data-testid="density-control"]').first()).toBeVisible();
  await expect(page.locator('[data-testid="density-control"] button[aria-pressed="true"]')).toHaveText(
    "紧凑",
  );

  await page.locator('[data-testid="density-control"]').first().getByRole("button", { name: "舒适" }).click();
  await expect(page.locator(".task-table")).toHaveClass(/density-comfortable/);

  // 刷新后偏好仍在（localStorage 记忆）。
  await page.reload();
  await expect(page.locator(".task-table")).toHaveClass(/density-comfortable/);

  // 进入任务详情：重点关注表的密度控件应沿用同一偏好。
  const failedTaskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "task-home-failed" })
    .first();
  await failedTaskRow.getByRole("button", { name: "详情" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed$/);
  await expect(page.locator('[data-testid="attention-panel"]')).toBeVisible();
  await expect(page.locator(".task-detail-attention-table")).toHaveClass(/density-comfortable/);

  // 进入规则管理：同一偏好继续生效。
  await page.goto("/inspectors");
  await expect(page.locator(".inspectors-table")).toHaveClass(/density-comfortable/);
  await expect(page.locator('[data-testid="density-control"] button[aria-pressed="true"]')).toHaveText(
    "舒适",
  );

  void taskDensity;
});

test("紧凑密度同视口比舒适密度多显示至少 2 行", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 620 });
  await page.goto("/inspectors");
  await expect(page.locator(".inspectors-table .ant-table-tbody > tr").first()).toBeVisible();

  // 默认紧凑。
  await expect(page.locator(".inspectors-table")).toHaveClass(/density-compact/);
  const compactHeight = await firstRowHeight(page, ".inspectors-table");
  const visibleRows = async () => {
    const viewport = page.viewportSize() ?? { width: 1440, height: 620 };
    const rows = page.locator(".inspectors-table .ant-table-tbody > tr.ant-table-row");
    const count = await rows.count();
    let visible = 0;
    for (let index = 0; index < count; index += 1) {
      const box = await rows.nth(index).boundingBox();
      if (box && box.y < viewport.height) visible += 1;
    }
    return visible;
  };
  const compactVisible = await visibleRows();

  await page.locator('[data-testid="density-control"]').getByRole("button", { name: "舒适" }).click();
  await expect(page.locator(".inspectors-table")).toHaveClass(/density-comfortable/);
  const comfortableHeight = await firstRowHeight(page, ".inspectors-table");
  const comfortableVisible = await visibleRows();

  expect(comfortableHeight).toBeGreaterThan(compactHeight);
  expect(compactVisible - comfortableVisible).toBeGreaterThanOrEqual(2);
});

test("规则管理页更新时间以相对时间呈现并支持点击表头排序", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/inspectors");

  const rows = page.locator(".inspectors-table .ant-table-tbody > tr.ant-table-row");
  await expect(rows.first()).toBeVisible();
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThanOrEqual(2);

  // 规则编码等宽字体（等宽样式落在 Typography.Text code 的内层 <code> 上）。
  const code = rows.first().locator(".inspectors-code code").first();
  await expect(code).toBeVisible();
  const fontFamily = await code.evaluate((node) => getComputedStyle(node).fontFamily);
  expect(fontFamily.toLowerCase()).toContain("mono");

  // 更新时间列可排序：点击表头升序、再次点击降序（E2E 种子规则的 updated_at 相同，
  // 因此用 aria-sort 断言排序状态，排序后的真实数据顺序由 InspectorsPage.test.tsx 单测覆盖）。
  const updatedHeader = page.locator(".inspectors-table thead th", { hasText: "更新时间" });
  await updatedHeader.locator(".ant-table-column-title").click();
  await expect(updatedHeader).toHaveAttribute("aria-sort", "ascending");
  await updatedHeader.locator(".ant-table-column-title").click();
  await expect(updatedHeader).toHaveAttribute("aria-sort", "descending");
  await expect(rows.first()).toBeVisible();

  // 相对时间 + 完整时间 Tooltip（放在排序交互之后，避免悬浮提示遮挡表头点击）。
  const updatedAt = rows
    .filter({ hasText: "log.filter" })
    .first()
    .locator('[data-testid="inspector-updated-at"]');
  await expect(updatedAt).toHaveText(/前|刚刚/);
  await updatedAt.hover();
  await expect(page.locator(".ant-tooltip").filter({ hasText: /\d{4}-\d{2}-\d{2}/ })).toBeVisible();
});
