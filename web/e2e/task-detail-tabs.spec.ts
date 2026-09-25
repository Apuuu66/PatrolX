import { expect, test } from "@playwright/test";

const rules = [
  {
    code: "config.a",
    name: "配置通过",
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "pass",
    severity: "low",
    summary: "通过",
  },
  {
    code: "log.b",
    name: "日志错误",
    category: "log",
    priority: 1,
    execution_order: 1,
    status: "fail",
    severity: "high",
    summary: "命中错误",
  },
];

const task = {
  task_id: "task-detail-tabs-e2e",
  name: "详情交互测试任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 2, pass: 1, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-detail-tabs-e2e")) {
      return route.fulfill({ json: task });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-detail-tabs-e2e/system")) {
      return route.fulfill({
        json: {
          package_file: "package.zip",
          status: "completed",
          summary: task.stats,
          rules,
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) return route.fulfill({ json: { task_id: task.task_id, entries: [] } });
    return route.fulfill({ json: {} });
  });
});

test("健康度条、任务视图和筛选状态同步到 URL", async ({ page }) => {
  await page.goto("/tasks/task-detail-tabs-e2e");

  await expect(page.getByRole("tab", { name: "规则结果" })).toBeVisible();
  await page.getByRole("tab", { name: "执行日志" }).click();
  await expect(page).toHaveURL(/view=logs/);
  await expect(page.getByText("暂无日志")).toBeVisible();

  await page.getByRole("tab", { name: "报告预览" }).click();
  await expect(page).toHaveURL(/view=report/);
  await expect(page.getByTitle("巡检报告")).toBeVisible();

  await page.getByRole("tab", { name: "规则结果" }).click();
  await page.locator(".health-bar-segment").filter({ hasText: "" }).nth(1).click();
  await expect(page).toHaveURL(/status=fail/);
  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  await expect(allRulesCard.getByText("配置通过")).toBeHidden();
  await expect(allRulesCard.getByText("日志错误")).toBeVisible();
});

test("URL 中的筛选状态在刷新后保留", async ({ page }) => {
  await page.goto("/tasks/task-detail-tabs-e2e?view=rules&status=fail&category=log&search=日志&sort=severity");
  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  await expect(allRulesCard.getByText("日志错误")).toBeVisible();
  await expect(allRulesCard.getByText("配置通过")).toBeHidden();
  await expect(page.getByLabel("规则搜索")).toHaveValue("日志");
});
