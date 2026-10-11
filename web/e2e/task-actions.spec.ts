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
  await expect(taskRow.getByRole("button", { name: /重跑|重建/ })).toHaveCount(0);
  await expect(taskRow.getByRole("button", { name: "删除" })).toHaveCount(0);

  // 低频操作仍在 ⋯ 菜单内可达（FR-008、FR-026）
  await taskRow.getByLabel("更多操作").click();
  await expect(page.getByRole("menuitem", { name: "失败日志" })).toBeVisible();
  // 列表只保留"重建"：重跑与更名前的"全量重建"都不再出现
  await expect(page.getByRole("menuitem", { name: "重建" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toHaveCount(0);
  await expect(page.getByRole("menuitem", { name: "全量重建" })).toHaveCount(0);

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

  // 默认不抢注意力，行 hover 后显现（FR-008）。
  await expect(revealButton).toHaveCSS("opacity", "0");
  // 列表在任务执行期间每 2 秒轮询重载，行序变化会把指针从该行移开；
  // hover 与断言一起重试，直到指针稳定落在目标行上（FR-008）。
  await expect(async () => {
    await completedRow.hover();
    await expect(revealButton).toHaveCSS("opacity", "1", { timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
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

const preparationTask = {
  task_id: "task-preparation-e2e",
  name: "数据准备样例任务",
  mode: "local",
  status: "completed",
  trigger: "ui",
  created_at: "2026-09-21T00:00:00Z",
  completed_at: "2026-09-21T00:01:00Z",
  stats: { total: 2, pass: 2, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
  preparation: {
    status: "warn",
    total: 2,
    success_count: 1,
    warning_count: 1,
    failure_count: 0,
    skip_count: 0,
    items: [
      {
        code: "prepare.alarm",
        name: "告警提取",
        category: "alarm",
        status: "warn",
        summary: "提取 3/5",
        duration_ms: 120,
        extracted_count: 3,
        total_count: 5,
        issues: [
          {
            type: "skipped",
            source: "raw/alarm/2026-09-21.csv",
            target: "prepared/alarm/2026-09-21.csv",
            reason: "来源文件缺失",
            path_length: 118,
            path_limit: 100,
          },
        ],
      },
      {
        code: "prepare.logs",
        name: "日志提取",
        category: "logs",
        status: "pass",
        summary: "全部提取",
        duration_ms: 80,
        extracted_count: 2,
        total_count: 2,
        issues: [],
      },
    ],
  },
};

test("数据准备摘要就地可见，明细在列内弹层而不是行展开", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v2/tasks") {
      return route.fulfill({
        json: { items: [preparationTask], total: 1, page: 1, page_size: 10 },
      });
    }
    if (url.pathname === "/api/v2/overview") {
      return route.fulfill({
        json: {
          task_count: 1,
          registered_rule_count: 2,
          rule_result_count: 2,
          finding_count: 0,
          status_counts: { total: 2, pass: 2, warn: 0, fail: 0, error: 0, skip: 0 },
        },
      });
    }
    if (url.pathname === "/api/v2/dicts") {
      return route.fulfill({ json: { province: [], operator: [], product: [], version: [] } });
    }
    return route.continue();
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 去掉收缩：行首不再有展开 / 收起箭头
  await expect(page.locator(".ant-table-row-expand-icon")).toHaveCount(0);

  const row = page.locator(".task-table .ant-table-tbody > tr.ant-table-row").first();
  const summary = row.locator('[data-testid="task-preparation-summary"]');
  await expect(summary).toBeVisible();
  await expect(summary).toContainText("1 类异常");

  // FR-011：问题摘要与问题文件明细仍可查看，只是改为列内弹层
  await summary.click();
  const popover = page.locator(".ant-popover").filter({ hasText: "告警 3/5" }).first();
  await expect(popover).toBeVisible();
  await expect(popover).toContainText("来源文件缺失");
  await expect(popover).toContainText("正常：日志");
});
