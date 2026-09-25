import { expect, test } from "@playwright/test";

const task = {
  task_id: "task-rule-rerun-e2e",
  name: "行级重跑测试任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 2, pass: 1, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
};

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
    code: "config.b",
    name: "配置失败",
    category: "config",
    priority: 2,
    execution_order: 1,
    status: "fail",
    severity: "high",
    summary: "配置不一致",
  },
];

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-rule-rerun-e2e")) {
      return route.fulfill({ json: task });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-rule-rerun-e2e/system")) {
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
    if (url.pathname.endsWith("/logs")) {
      return route.fulfill({ json: { task_id: task.task_id, entries: [] } });
    }
    if (url.pathname.endsWith("/rerun")) {
      return route.fulfill({ status: 202, json: task });
    }
    return route.fulfill({ json: {} });
  });
});

test("任务详情支持确认后单规则重跑", async ({ page }) => {
  await page.goto("/tasks/task-rule-rerun-e2e");

  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  const ruleRow = allRulesCard.locator("tr").filter({ hasText: "config.b" });
  await ruleRow.getByRole("button", { name: "重跑" }).click();

  const rerunPromise = page.waitForRequest((request) =>
    request.url().endsWith("/api/v2/tasks/task-rule-rerun-e2e/rerun"),
  );
  await page.getByRole("button", { name: "确 定" }).click();
  const rerun = await rerunPromise;
  expect(rerun.postDataJSON()).toEqual({ rule_codes: ["config.b"] });

  await expect(page.getByText("已受理重跑 config.b")).toBeVisible();
});
