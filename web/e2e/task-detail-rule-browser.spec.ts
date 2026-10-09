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

test("任务详情提供状态分布、规则搜索、分类聚焦和严重度排序", async ({ page }) => {
  await page.goto("/tasks/task-rule-browser-e2e");

  await expect(page.getByLabel("规则状态分布")).toBeVisible();
  await expect(page.getByTestId("conclusion-hero").getByLabel("筛选失败")).toBeVisible();
  await expect(page.getByTestId("conclusion-hero").getByLabel("筛选通过")).toBeVisible();

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
  // 默认只展开含异常的分组；通过分组展开后其它类别的规则仍然保留（FR-017）。
  await expect(allRulesCard.getByText("配置通过")).toBeHidden();
  await allRulesCard.getByRole("button", { name: /配置（1）/ }).click();
  await expect(allRulesCard.getByText("配置通过")).toBeVisible();
  const firstRow = allRulesCard.locator(".ant-table-tbody").first().locator("tr").first();
  await expect(firstRow).toContainText("日志访问");
  await expect(firstRow).toHaveClass(/rule-row-focus/);
  await expect(firstRow.locator("td").first()).toHaveCSS("background-color", "rgb(240, 247, 255)");

  await page.getByText("默认排序", { exact: true }).click();
  await page.locator(".ant-select-item-option[title=严重度优先]").click();
  await expect(firstRow).toContainText("日志错误");
});

test("重点关注规则默认不在全部规则中重复展示且可恢复", async ({ page }) => {
  await page.goto("/tasks/task-rule-browser-e2e");

  const allRulesCard = page.getByTestId("rule-browser");
  // log.b 已在「重点关注」，默认不在「全部规则」等权重复（FR-011、SC-004）。
  await expect(page.getByTestId("attention-panel").getByText("日志错误")).toBeVisible();
  await expect(allRulesCard.getByTestId("rule-browser-dedupe")).toContainText(
    "另有 1 条已在上方重点关注",
  );
  await expect(allRulesCard.getByText("日志错误")).toHaveCount(0);
  // 分类计数沿用既有筛选语义，不因去重减少（R7）。
  await expect(
    allRulesCard.locator(".ant-tag-checkable").filter({ hasText: /^日志\s*2$/ }),
  ).toBeVisible();

  await allRulesCard.getByTestId("rule-browser-show-all").click();
  await expect(allRulesCard.getByTestId("rule-browser-show-all-active")).toContainText(
    "已包含重点关注中的规则",
  );
  await expect(allRulesCard.getByText("日志错误")).toBeVisible();

  await allRulesCard.getByTestId("rule-browser-hide-all").click();
  await expect(allRulesCard.getByText("日志错误")).toHaveCount(0);

  // 搜索命中被排除的规则时自动纳入，不丢失入口（FR-011）。
  await page.getByLabel("规则搜索").fill("log.b");
  await expect(allRulesCard.getByText("日志错误")).toBeVisible();
  await expect(allRulesCard.getByTestId("rule-browser-dedupe")).toHaveCount(0);
});
