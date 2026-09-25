import { expect, test } from "@playwright/test";

const task = {
  task_id: "task-states-e2e",
  name: "页面状态测试任务",
  mode: "local",
  status: "failed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:00:01Z",
  stats: { total: 1, pass: 0, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
};

const taskResponse = {
  items: [task],
  total: 1,
  page: 1,
  page_size: 10,
};

test("任务列表使用骨架屏并在失败后支持重试", async ({ page }) => {
  let shouldFailTasks = true;

  await page.route("**/api/v2/tasks?page=1&page_size=10", async (route) => {
    if (shouldFailTasks) return route.fulfill({ status: 500, json: { detail: "任务列表暂不可用" } });
    return route.fulfill({ json: taskResponse });
  });
  await page.route("**/api/v2/overview", (route) =>
    route.fulfill({
      json: {
        task_count: 1,
        registered_rule_count: 0,
        rule_result_count: 1,
        finding_count: 1,
        status_counts: { pass: 0, warn: 0, fail: 1, error: 0, skip: 0 },
      },
    }),
  );
  await page.route("**/api/v2/dicts", (route) =>
    route.fulfill({ json: { province: [], operator: [], product: [], version: [] } }),
  );

  await page.goto("/");
  await expect(page.getByText("加载失败")).toBeVisible();
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();

  shouldFailTasks = false;
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByText("页面状态测试任务")).toBeVisible();
});

test("任务状态快捷筛选会把状态传给任务列表接口", async ({ page }) => {
  let requestedStatus: string | null = null;

  await page.route("**/api/v2/tasks?page=1&page_size=10**", async (route) => {
    const url = new URL(route.request().url());
    requestedStatus = url.searchParams.get("status");
    return route.fulfill({ json: taskResponse });
  });
  await page.route("**/api/v2/overview", (route) =>
    route.fulfill({
      json: {
        task_count: 1,
        registered_rule_count: 0,
        rule_result_count: 1,
        finding_count: 1,
        status_counts: { pass: 0, warn: 0, fail: 1, error: 0, skip: 0 },
      },
    }),
  );
  await page.route("**/api/v2/dicts", (route) =>
    route.fulfill({ json: { province: [], operator: [], product: [], version: [] } }),
  );

  await page.goto("/");
  await expect(page.getByText("页面状态测试任务")).toBeVisible();

  await page.getByLabel("任务状态快捷筛选").getByText("失败").click();
  await expect.poll(() => requestedStatus).toBe("failed");
});
