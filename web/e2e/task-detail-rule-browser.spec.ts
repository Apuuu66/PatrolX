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
    code: "log.a",
    name: "日志访问",
    category: "log",
    priority: 1,
    execution_order: 1,
    status: "pass",
    severity: "low",
    summary: "通过",
  },
  {
    code: "log.b",
    name: "日志错误",
    category: "log",
    priority: 1,
    execution_order: 2,
    status: "fail",
    severity: "high",
    summary: "命中错误",
  },
];

const task = {
  task_id: "task-rule-browser-e2e",
  name: "规则浏览测试任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 3, pass: 2, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-rule-browser-e2e")) {
      return route.fulfill({ json: task });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-rule-browser-e2e/system")) {
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

test("任务详情提供健康度条、规则搜索、分类聚焦和严重度排序", async ({ page }) => {
  await page.goto("/tasks/task-rule-browser-e2e");

  await expect(page.getByLabel("规则健康度分布")).toBeVisible();
  await expect(page.locator(".health-bar-segment")).toHaveCount(2);

  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  const failSegment = page.getByLabel("筛选失败");
  await failSegment.click();
  await expect(allRulesCard.locator(".ant-tag-checkable").filter({ hasText: /^配置\s*0$/ })).toBeVisible();
  await expect(allRulesCard.locator(".ant-tag-checkable").filter({ hasText: /^日志\s*1$/ })).toBeVisible();
  await failSegment.click();

  await page.getByLabel("规则搜索").fill("KPI");
  await expect(allRulesCard.getByText("暂无匹配的规则结果")).toBeVisible();
  await page.getByLabel("规则搜索").fill("");

  await page.locator(".ant-tag-checkable").filter({ hasText: /^日志\s*2$/ }).click();
  await expect(allRulesCard.getByText("配置 1", { exact: true })).toBeVisible();
  await expect(allRulesCard.getByText("配置通过")).toBeVisible();
  const firstRow = allRulesCard.locator(".ant-table-tbody").first().locator("tr").first();
  await expect(firstRow).toContainText("日志访问");
  await expect(firstRow).toHaveClass(/rule-row-focus/);
  await expect(firstRow.locator("td").first()).toHaveCSS("background-color", "rgb(240, 247, 255)");

  await page.getByText("默认排序", { exact: true }).click();
  await page.locator(".ant-select-item-option[title=严重度优先]").click();
  await expect(firstRow).toContainText("日志错误");
});
