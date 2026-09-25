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

test("任务列表保留高频操作并收纳低频操作", async ({ page }) => {
  await page.goto("/");
  const taskCard = page.locator(".ant-card").filter({ hasText: "首页失败任务样例" }).last();

  await expect(taskCard.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(taskCard.getByRole("button", { name: "报告" })).toBeVisible();
  await expect(taskCard.getByRole("button", { name: "重跑" })).toHaveCount(0);
  await expect(taskCard.getByRole("button", { name: "删除" })).toHaveCount(0);

  await taskCard.getByLabel("更多操作").click();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "重建" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();
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
