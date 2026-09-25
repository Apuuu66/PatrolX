import { expect, test } from "@playwright/test";

const rules = [
  {
    code: "config.a",
    name: "通过规则",
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "pass",
    severity: "low",
    summary: "通过",
  },
  {
    code: "config.b",
    name: "失败规则",
    category: "config",
    priority: 1,
    execution_order: 1,
    status: "fail",
    severity: "high",
    summary: "失败",
  },
];

test("任务详情状态数字点击后过滤规则", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-filter-e2e")) {
      return route.fulfill({
        json: {
          task_id: "task-filter-e2e",
          name: "过滤测试任务",
          mode: "local",
          status: "completed",
          trigger: "ui",
          created_at: "2026-09-21T00:00:00Z",
          completed_at: "2026-09-21T00:00:01Z",
          stats: { total: 2, pass: 1, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-filter-e2e/system")) {
      return route.fulfill({
        json: {
          package_file: "package.zip",
          status: "completed",
          summary: { total: 2, pass: 1, warn: 0, fail: 1, error: 0, skip: 0 },
          rules,
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) return route.fulfill({ json: { task_id: "task-filter-e2e", entries: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/tasks/task-filter-e2e");
  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  const failCard = page.locator(".ant-card-small").filter({ has: page.locator(".ant-statistic-title", { hasText: /^失败$/ }) });
  await failCard.click();

  await expect(allRulesCard.getByText("失败规则")).toBeVisible();
  await expect(allRulesCard.getByText("通过规则")).toBeHidden();
  await expect
    .poll(() => failCard.evaluate((element) => getComputedStyle(element).backgroundColor))
    .not.toBe("rgb(255, 255, 255)");
});
