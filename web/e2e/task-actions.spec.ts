import { expect, test } from "@playwright/test";

const taskId = "task-actions-e2e";

const task = {
  task_id: taskId,
  name: "操作收纳测试任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 2, pass: 2, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
};

test("任务列表收敛后高频入口与低频操作仍可及", async ({ page }) => {
  await page.goto("/");
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();

  // 常驻行内只有详情；失败原因摘要即唯一日志入口（FR-008、R5）
  await expect(taskRow.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(taskRow.locator('[data-testid="task-failure-reason"]')).toBeVisible();
  await expect(taskRow.getByRole("button", { name: "失败日志" })).toHaveCount(0);
  await expect(taskRow.getByRole("button", { name: "重跑" })).toHaveCount(0);
  await expect(taskRow.getByRole("button", { name: "删除" })).toHaveCount(0);

  // 低频操作仍在 ⋯ 菜单内可达（FR-008、FR-026）
  await taskRow.getByLabel("更多操作").click();
  await expect(page.getByRole("menuitem", { name: "失败日志" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "全量重建" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();

  // 菜单里的失败日志仍能一次点击进入日志页（FR-026）
  await page.getByRole("menuitem", { name: "失败日志" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed\/logs$/);
});

test("已完成任务的报告入口在 hover 时显现且菜单同样可达", async ({ page }) => {
  await page.goto("/");
  const completedRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "task-kpi-history-current" })
    .first();

  const revealButton = completedRow.locator(".task-table-action-reveal");
  await expect(revealButton).toHaveText("报告");

  // 默认不抢注意力，行 hover 后显现（FR-008）
  await expect(revealButton).toHaveCSS("opacity", "0");
  await completedRow.hover();
  await expect(revealButton).toHaveCSS("opacity", "1");
  await revealButton.click();
  await expect(page).toHaveURL(/\/tasks\/task-kpi-history-current\/report$/);
});

test("任务详情只保留报告主操作并收纳次要操作", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith(`/api/v2/tasks/${taskId}`)) return route.fulfill({ json: task });
    if (url.pathname.endsWith(`/api/v2/tasks/${taskId}/system`)) {
      return route.fulfill({
        json: {
          package_file: "package.zip",
          status: "completed",
          summary: { total: 2, pass: 2, warn: 0, fail: 0, error: 0, skip: 0 },
          rules: [],
          customer: { province: "js", operator: "cmcc", product: "router", device_id: "dev-001" },
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) return route.fulfill({ json: { task_id: taskId, entries: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto(`/tasks/${taskId}`);
  await expect(page.getByRole("button", { name: "查看报告" })).toBeVisible();
  await expect(page.getByRole("button", { name: "执行日志" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "增量重建" })).toHaveCount(0);

  await page.getByLabel("更多操作").click();
  await page.getByRole("menuitem", { name: "执行日志" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${taskId}/logs$`));
});
