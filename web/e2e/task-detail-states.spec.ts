import { expect, test } from "@playwright/test";

const rules = Array.from({ length: 7 }, (_, index) => ({
  code: `fail.${index + 1}`,
  name: `失败规则 ${index + 1}`,
  category: index % 2 === 0 ? "log" : "config",
  priority: 1,
  execution_order: index,
  status: index < 5 ? "fail" : "warn",
  severity: "high",
  summary: "命中异常",
}));

const task = {
  task_id: "task-detail-states-e2e",
  name: "详情状态测试任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-25T00:00:00Z",
  completed_at: "2026-09-25T00:00:01Z",
  stats: { total: 7, pass: 0, warn: 2, fail: 5, error: 0, skip: 0, systems: 1 },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-detail-states-e2e")) {
      return route.fulfill({ json: task });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-detail-states-e2e/system")) {
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
    if (url.pathname.endsWith("/logs")) return route.fulfill({ status: 500, json: { code: "logs_error", message: "日志服务暂不可用" } });
    return route.fulfill({ json: {} });
  });
});

test("重点关注超过 5 条时只渲染前 5 条并可展开其余", async ({ page }) => {
  await page.goto("/tasks/task-detail-states-e2e");

  const hero = page.getByTestId("conclusion-hero");
  await expect(hero.getByText("需要关注")).toBeVisible();
  await expect(hero.getByText("发现失败 5 条、异常 0 条规则结果，需要处理。")).toBeVisible();
  await expect(hero.getByLabel("筛选失败")).toContainText("失败 5");
  await expect(hero.getByLabel("筛选告警")).toContainText("告警 2");
  await expect(hero.getByRole("button", { name: "查看报告" })).toBeVisible();

  const attentionCard = page.getByTestId("attention-panel");
  await expect(attentionCard.getByText("重点关注（7）")).toBeVisible();
  await expect(attentionCard.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(5);
  await expect(attentionCard.getByText("失败规则 1")).toBeVisible();
  await expect(attentionCard.getByText("失败规则 6")).toHaveCount(0);
  await expect(page.getByText("重点关注 7 条规则")).toHaveCount(0);
  await expect(page.getByText(/其余 2 条在全部规则中查看。/)).toHaveCount(0);

  await attentionCard.getByRole("button", { name: "展开其余 2 条" }).click();
  await expect(attentionCard.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(7);
  await expect(attentionCard.getByText("失败规则 6")).toBeVisible();
  await attentionCard.getByRole("button", { name: "收起" }).click();
  await expect(attentionCard.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(5);

  const allRulesCard = page.getByTestId("rule-browser");
  await expect(allRulesCard.getByText("失败规则 6")).toBeVisible();
  await expect(allRulesCard.getByText("失败规则 7")).toBeVisible();
});

test("状态计数点选后联动状态筛选", async ({ page }) => {
  await page.goto("/tasks/task-detail-states-e2e");

  const failCount = page.getByTestId("conclusion-hero").getByLabel("筛选失败");
  await failCount.click();
  await expect(page).toHaveURL(/status=fail/);
  await expect(failCount).toHaveAttribute("aria-pressed", "true");

  const allRulesCard = page.getByTestId("rule-browser");
  await expect(allRulesCard.getByText("失败规则 1")).toBeVisible();
  await expect(allRulesCard.getByText("失败规则 6")).toHaveCount(0);

  await failCount.click();
  await expect(page).not.toHaveURL(/status=fail/);
  await expect(allRulesCard.getByText("失败规则 6")).toBeVisible();
});

test("执行日志加载失败时展示错误态而不是空态", async ({ page }) => {
  await page.goto("/tasks/task-detail-states-e2e");
  await page.getByRole("tab", { name: "执行日志" }).click();

  const logsCard = page.locator(".ant-card").filter({ hasText: "执行日志" });
  await expect(logsCard.getByText("加载失败")).toBeVisible();
  await expect(logsCard.getByText(/日志服务暂不可用|请求失败/)).toBeVisible();
  await expect(logsCard.getByText("暂无日志")).toBeHidden();
});
