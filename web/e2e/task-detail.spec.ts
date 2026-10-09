import { expect, test } from "@playwright/test";

test("旧任务详情页首屏给出结论、状态计数与关键元数据", async ({ page }) => {
  const systemResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v2/tasks/task-legacy-e2e/system") &&
      response.request().method() === "GET",
  );

  await page.goto("/tasks/task-legacy-e2e");

  const systemResponse = await systemResponsePromise;
  expect(systemResponse.status()).toBe(200);

  const hero = page.getByTestId("conclusion-hero");
  await expect(hero.getByRole("heading", { name: "旧版本任务" })).toBeVisible();
  await expect(hero.getByText("全部通过", { exact: true })).toBeVisible();
  await expect(hero.getByText("共执行 1 条规则，未发现失败、告警或异常。")).toBeVisible();
  await expect(hero.getByLabel("筛选通过")).toContainText("通过 1");
  await expect(hero.getByRole("button", { name: "查看报告" })).toBeVisible();
  await expect(hero.getByText("数据包")).toBeVisible();
  await expect(hero.getByText("legacy.zip")).toBeVisible();
  await expect(hero.getByText("创建时间")).toBeVisible();

  await expect(page.getByTestId("rule-browser").getByText("日志错误密度")).toBeVisible();
  await expect(page.getByText("无异常")).toBeVisible();
  await expect(page.getByText("全部规则")).toBeVisible();

  // 旧版“巡检完成，未发现需要重点处理的规则”提示条已并入结论 Hero，不再重复表达。
  await expect(page.getByText("巡检完成，未发现需要重点处理的规则")).toHaveCount(0);
});

test("全通过且无关注项时只保留结论 Hero 与全部规则", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-all-pass-e2e")) {
      return route.fulfill({
        json: {
          task_id: "task-all-pass-e2e",
          name: "全部通过任务",
          mode: "local",
          status: "completed",
          trigger: "ui",
          created_at: "2026-09-21T00:00:00Z",
          completed_at: "2026-09-21T00:00:01Z",
          stats: { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-all-pass-e2e/system")) {
      return route.fulfill({
        json: {
          package_file: "package.zip",
          status: "completed",
          summary: { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0 },
          rules: [
            {
              code: "config.a",
              name: "配置通过",
              category: "config",
              priority: 1,
              execution_order: 0,
              status: "pass",
              severity: "low",
              summary: "配置一致",
            },
          ],
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) {
      return route.fulfill({ json: { task_id: "task-all-pass-e2e", entries: [] } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/tasks/task-all-pass-e2e");

  const hero = page.getByTestId("conclusion-hero");
  await expect(hero.getByText("全部通过", { exact: true })).toBeVisible();
  await expect(hero.getByLabel("筛选通过")).toContainText("通过 1");
  await expect(hero.getByLabel("筛选失败")).toHaveCount(0);
  await expect(hero.getByText("暂无规则结果")).toHaveCount(0);

  await expect(page.getByTestId("attention-panel")).toHaveCount(0);
  await expect(page.getByTestId("rule-browser").getByText("配置通过")).toBeVisible();
});

test("解压失败任务首屏给出失败阶段与日志入口且不渲染空规则表", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-extract-failed-e2e")) {
      return route.fulfill({
        json: {
          task_id: "task-extract-failed-e2e",
          name: "解压失败任务",
          mode: "local",
          status: "failed",
          trigger: "ui",
          created_at: "2026-09-21T00:00:00Z",
          completed_at: null,
          stats: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 0 },
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-extract-failed-e2e/system")) {
      return route.fulfill({ status: 404, json: { code: "not_found", message: "系统结果不存在", detail: {} } });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) {
      return route.fulfill({
        json: {
          task_id: "task-extract-failed-e2e",
          entries: [
            { ts: "2026-09-21T00:00:00Z", level: "info", message: "任务开始执行", detail: {} },
            {
              ts: "2026-09-21T00:00:01Z",
              level: "error",
              message: "主包解压失败，任务失败",
              detail: { error: "解压总量超限：允许解压总量 2.8 GB" },
            },
          ],
        },
      });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/tasks/task-extract-failed-e2e");

  const hero = page.getByTestId("conclusion-hero");
  await expect(hero.getByText("任务失败", { exact: true })).toBeVisible();
  await expect(hero.getByText(/主包解压失败，任务失败：解压总量超限/)).toBeVisible();
  await expect(hero.getByText("失败阶段：任务执行")).toBeVisible();
  await expect(hero.getByRole("button", { name: "查看失败日志" })).toBeVisible();
  await expect(hero.getByText("暂无规则结果")).toBeVisible();

  // 规则区不渲染空规则表格，也不重复表达失败原因与阶段（FR-019、SC-005）。
  await expect(page.getByTestId("rule-browser")).toHaveCount(0);
  await expect(page.getByTestId("attention-panel")).toHaveCount(0);
  await expect(page.locator(".ant-table")).toHaveCount(0);
  await expect(hero.getByText("失败阶段：任务执行")).toHaveCount(1);
  await expect(hero.getByText(/主包解压失败，任务失败：解压总量超限/)).toHaveCount(1);

  await hero.getByRole("button", { name: "查看失败日志" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-extract-failed-e2e\/logs$/);
});

test("元数据超过 4 项时收纳进更多元数据且空字段不渲染占位", async ({ page }) => {
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/v2/tasks/task-metadata-e2e")) {
      return route.fulfill({
        json: {
          task_id: "task-metadata-e2e",
          name: "元数据测试任务",
          mode: "local",
          status: "completed",
          trigger: "ui",
          created_at: "2026-09-21T00:00:00Z",
          completed_at: "2026-09-21T00:01:00Z",
          customer_version: "V9.0.0",
          stats: { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/tasks/task-metadata-e2e/system")) {
      return route.fulfill({
        json: {
          package_file: "package.zip",
          version: "V9.0.0",
          status: "completed",
          summary: { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0 },
          customer: { province: "江苏省", operator: "中国移动", product: "" },
          rules: [
            {
              code: "config.a",
              name: "配置通过",
              category: "config",
              priority: 1,
              execution_order: 0,
              status: "pass",
              severity: "low",
              summary: "配置一致",
            },
          ],
        },
      });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/logs")) {
      return route.fulfill({ json: { task_id: "task-metadata-e2e", entries: [] } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/tasks/task-metadata-e2e");

  const hero = page.getByTestId("conclusion-hero");
  const metadata = hero.locator(".metadata-list");
  await expect(hero.getByText("共执行 1 条规则，未发现失败、告警或异常。")).toBeVisible();
  await expect(hero.getByText(/异常 0 条|告警 0 条|失败 0 条/)).toHaveCount(0);

  // 平铺 4 项，其余进入"更多元数据"（FR-010）
  await expect(metadata.locator(".metadata-list-item")).toHaveCount(4);
  await expect(metadata.locator('[data-metadata-key="package"]')).toContainText("package.zip");
  await expect(metadata.locator('[data-metadata-key="province"]')).toContainText("江苏省");

  // 空字段不渲染，也不出现 "-" 占位（FR-010、SC-003）
  await expect(hero.getByText("网元类型")).toHaveCount(0);
  await expect(metadata.getByText("-", { exact: true })).toHaveCount(0);

  const moreTrigger = metadata.getByTestId("metadata-more");
  await expect(moreTrigger).toHaveText("更多元数据（2）");
  await moreTrigger.click();

  const panel = page.getByTestId("metadata-more-panel");
  await expect(panel.locator('[data-metadata-key="created_at"]')).toContainText("创建时间");
  await expect(panel.locator('[data-metadata-key="duration"]')).toContainText("耗时");

  // 复制入口 hover 显现，点击后有反馈（contracts §7）
  const packageItem = metadata.locator('[data-metadata-key="package"]');
  const copyButton = metadata.getByRole("button", { name: "复制数据包值" });
  await expect(packageItem.locator(".metadata-list-copy")).toHaveCSS("opacity", "0");
  await packageItem.hover();
  await expect(packageItem.locator(".metadata-list-copy")).toHaveCSS("opacity", "1");
  await copyButton.click();
  await expect(copyButton).not.toHaveAttribute("data-copy-state", "idle");
  await expect(page).toHaveURL(/\/tasks\/task-metadata-e2e$/);
});
