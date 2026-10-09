import { expect, test } from "@playwright/test";

test("任务首页以行式列表呈现并让失败任务置顶", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 首屏可见概览条与种子任务（SC-001）
  await expect(page.locator('[data-testid="task-overview"]')).toBeVisible();
  const rows = page.locator(".task-table .ant-table-tbody > tr.ant-table-row");
  // 全量套件并行运行时会创建额外任务，这里只要求 5 条种子任务都出现在首屏（SC-001）。
  await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(5);
  for (const taskId of [
    "task-home-failed",
    "task-alarm-flapping-e2e",
    "task-kpi-history-current",
    "task-kpi-history-past",
  ]) {
    await expect(page.locator(".task-table code", { hasText: taskId })).toBeVisible();
  }

  // 单一表行式列表，不再是卡片网格（FR-006）
  await expect(page.locator(".task-table")).toHaveCount(1);

  // 失败任务必须位于第一行（SC-003、FR-007）
  const firstRow = rows.first();
  await expect(firstRow.locator("code", { hasText: "task-home-failed" })).toBeVisible();

  // 失败原因摘要在行内直接可见，无需展开（SC-003、FR-008）
  await expect(firstRow.locator('[data-testid="task-failure-reason"]')).toBeVisible();

  // 状态摘要只保留非零状态，不出现彩色 0 值（FR-003、FR-009）
  await expect(firstRow.locator('[data-status-count="error"]')).toHaveText(/异常 1/);
  await expect(firstRow.locator('[data-status-count="pass"]')).toHaveCount(0);
  await expect(firstRow.locator('[data-status-count="warn"]')).toHaveCount(0);
  await expect(firstRow.locator('[data-status-count="fail"]')).toHaveCount(0);
  await expect(firstRow.locator('[data-status-count="skip"]')).toHaveCount(0);

  // 失败任务行有失败日志与详情入口，进入失败日志不超过 2 次点击（SC-003）
  await firstRow.getByRole("button", { name: "失败日志" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed\/logs$/);
  await expect(page.getByText("任务执行失败：解析主清单失败")).toBeVisible();
});

test("任务首页行内元数据与耗时保持可读且操作分层", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "task-home-failed" });
  await expect(failedRow.locator('[data-metadata-key="device_id"]')).toContainText("home-device-001");
  await expect(failedRow.locator('[data-metadata-key="province"]')).toContainText("江苏");

  // 行内平铺业务操作不超过 3 个，且失败任务用失败日志替代报告（FR-012）
  await expect(failedRow.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "失败日志" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "报告" })).toHaveCount(0);
  await expect
    .poll(async () =>
      failedRow.getByRole("button", { name: /详情|报告|失败日志/ }).count(),
    )
    .toBeLessThanOrEqual(3);

  // 低频与危险操作收进更多菜单（FR-012）
  await expect(failedRow.getByRole("button", { name: "重跑" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: /删除/ })).toHaveCount(0);
  await failedRow.getByRole("button", { name: "更多操作" }).click();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /删除/ })).toBeVisible();
});

test("任务首页从失败任务行一次点击进入任务详情", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "task-home-failed" });

  await failedRow.getByRole("button", { name: "详情" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed$/);
});
