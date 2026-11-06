import { expect, test } from "@playwright/test";

async function loginAdmin(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

/** 读取表格首行行高，用于验证密度切换真实改变行距（FR-016）。 */
async function firstRowHeight(page: import("@playwright/test").Page, rootSelector: string) {
  const row = page.locator(`${rootSelector} .ant-table-tbody > tr.ant-table-row`).first();
  await expect(row).toBeVisible();
  const box = await row.boundingBox();
  return box?.height ?? 0;
}

async function showAllTasks(page: import("@playwright/test").Page) {
  await page.locator(".ant-pagination-options .ant-select-selector").click();
  const option = page
    .locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option")
    .filter({ hasText: /^100\s*条\/页$/ });
  await expect(option).toBeVisible();
  await option.click();
  await expect(page.locator(".ant-pagination-options .ant-select-selection-item")).toHaveText(
    /100\s*条\/页/,
  );
}

test("密度偏好在任务列表、任务详情与规则管理之间沿用并刷新后保持", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

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
  // 任务详情入口已由 task-home.spec.ts 覆盖；这里直接进入固定失败任务，
  // 避免新工作台种子任务增加后，目标任务落到第二页而让密度断言依赖分页。
  await page.goto("/tasks/task-home-failed");
  await expect(page).toHaveURL(/\/tasks\/task-home-failed$/);
  await expect(page.locator('[data-testid="attention-panel"]')).toBeVisible();
  await expect(page.locator(".task-detail-attention-table")).toHaveClass(/density-comfortable/);

  // 进入规则管理：v6 规则归属接口要求登录，登录后同一密度偏好继续生效。
  await loginAdmin(page);
  await page.goto("/inspectors");
  await expect(page.locator(".inspectors-table")).toHaveClass(/density-comfortable/);
  await expect(page.locator('[data-testid="density-control"] button[aria-pressed="true"]')).toHaveText(
    "舒适",
  );

});

test("任务列表紧凑密度同视口比舒适密度多显示至少 2 行", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await showAllTasks(page);
  const rows = page.locator(".task-table .ant-table-tbody > tr.ant-table-row");
  await expect(rows.filter({ hasText: "task-density-e2e-12" })).toBeVisible();

  // 把多行任务表滚到视口顶部，使可见行数差异归因于密度而不是首页概览高度。
  await page.locator(".task-table").evaluate((node) => node.scrollIntoView({ block: "start" }));
  await expect(page.locator(".task-table thead")).toBeVisible();

  // 默认紧凑。
  await expect(page.locator(".task-table")).toHaveClass(/density-compact/);
  const compactHeight = await firstRowHeight(page, ".task-table");
  const visibleRows = async () => {
    const viewport = page.viewportSize() ?? { width: 1440, height: 900 };
    const count = await rows.count();
    let visible = 0;
    for (let index = 0; index < count; index += 1) {
      const box = await rows.nth(index).boundingBox();
      if (box && box.y >= 0 && box.y + box.height <= viewport.height) visible += 1;
    }
    return visible;
  };
  const compactVisible = await visibleRows();

  await page.locator('[data-testid="density-control"]').getByRole("button", { name: "舒适" }).click();
  await expect(page.locator(".task-table")).toHaveClass(/density-comfortable/);
  const comfortableHeight = await firstRowHeight(page, ".task-table");
  const comfortableVisible = await visibleRows();

  expect(comfortableHeight).toBeGreaterThan(compactHeight);
  expect(compactVisible - comfortableVisible).toBeGreaterThanOrEqual(2);
});

test("规则管理页更新时间以相对时间呈现并支持点击表头排序", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAdmin(page);
  await page.goto("/inspectors");

  const rows = page.locator(".inspectors-table .ant-table-tbody > tr.ant-table-row");
  const search = page.getByPlaceholder("搜索编码 / 名称");
  await search.fill("kpi.measurement_units");
  await search.press("Enter");
  await expect(rows.first()).toBeVisible();
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator(".inspectors-code code").first()).toHaveText(
    "kpi.measurement_units",
  );

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
  const updatedAt = rows.first().locator('[data-testid="rule-assignment-updated-at"]');
  await expect(updatedAt).toHaveText(/前|刚刚/);
  await updatedAt.hover();
  await expect(page.locator(".ant-tooltip").filter({ hasText: /\d{4}-\d{2}-\d{2}/ })).toBeVisible();
});
