import { expect, test } from "@playwright/test";

const task = {
  task_id: "report-task-e2e",
  name: "报告任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 2, pass: 1, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
};

const system = {
  package_file: "report-package.zip",
  version: "V5.2.1",
  status: "completed",
  summary: task.stats,
  customer: {
    province: "江苏",
    operator: "移动",
    product: "核心网",
    device_id: "report-device-001",
  },
  rules: [],
};

let systemAvailable = true;

test.beforeEach(async ({ page }) => {
  systemAvailable = true;
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/report-task-e2e")) {
      return route.fulfill({ json: task });
    }
    if (url.pathname.endsWith("/api/v2/tasks/report-task-e2e/system")) {
      if (!systemAvailable) {
        return route.fulfill({
          status: 500,
          json: { code: "system_error", message: "系统结果暂不可用" },
        });
      }
      return route.fulfill({ json: system });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) {
      return route.fulfill({ json: { task_id: task.task_id, entries: [] } });
    }
    if (url.pathname.endsWith("/report")) {
      return route.fulfill({
        headers: { "content-type": "text/html" },
        body: "<!doctype html><html><body><h1>巡检报告内容</h1></body></html>",
      });
    }
    return route.fulfill({ json: {} });
  });
});

test("报告详情先展示任务信息再展示报告", async ({ page }) => {
  await page.goto("/tasks/report-task-e2e/report");

  const cards = page.locator(".ant-card");
  await expect(cards).toHaveCount(2);

  const taskCard = cards.nth(0);
  const reportCard = cards.nth(1);
  await expect(taskCard.getByText("任务信息")).toBeVisible();
  await expect(taskCard.getByText("报告任务")).toBeVisible();
  await expect(taskCard.getByText("report-package.zip")).toBeVisible();
  await expect(taskCard.getByText("report-device-001")).toBeVisible();
  await expect(reportCard.getByText("巡检报告")).toBeVisible();
});

test("系统结果失败时保留报告入口", async ({ page }) => {
  systemAvailable = false;
  await page.goto("/tasks/report-task-e2e/report");

  await expect(page.getByText("系统结果加载失败")).toBeVisible();
  await expect(page.getByText("系统结果暂不可用")).toBeVisible();
  await expect(page.locator('iframe[title="巡检报告"]')).toBeVisible();
});
