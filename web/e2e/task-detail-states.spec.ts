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

test("重点关注超过 5 条时只渲染前 5 条并说明剩余位置", async ({ page }) => {
  await page.goto("/tasks/task-detail-states-e2e");

  const attentionCard = page.locator(".ant-card").filter({ hasText: "重点关注（7）" });
  await expect(page.getByText("重点关注 7 条规则")).toBeVisible();
  await expect(page.getByText(/其余 2 条在全部规则中查看。/)).toBeVisible();
  await expect(attentionCard.locator(".ant-table-tbody tr")).toHaveCount(5);
  await expect(attentionCard.getByText("失败规则 1")).toBeVisible();
  await expect(attentionCard.getByText("失败规则 6")).toBeHidden();

  const allRulesCard = page.locator(".ant-card").filter({ hasText: "全部规则" });
  await expect(allRulesCard.locator(".ant-table-tbody tr")).toHaveCount(7);
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
