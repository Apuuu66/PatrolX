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
test("任务列表加载态使用骨架屏且空态提供上传动作", async ({ page }) => {
  let releaseTasks: () => void = () => {};
  const taskGate = new Promise<void>((resolve) => {
    releaseTasks = resolve;
  });

  await page.route("**/api/v2/tasks?page=1&page_size=10**", async (route) => {
    await taskGate;
    return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 10 } });
  });
  await page.route("**/api/v2/overview", (route) =>
    route.fulfill({
      json: {
        task_count: 0,
        registered_rule_count: 0,
        rule_result_count: 0,
        finding_count: 0,
        status_counts: { pass: 0, warn: 0, fail: 0, error: 0, skip: 0 },
      },
    }),
  );
  await page.route("**/api/v2/dicts", (route) =>
    route.fulfill({ json: { province: [], operator: [], product: [], version: [] } }),
  );

  await page.goto("/");
  await expect(page.getByLabel("页面加载中").first()).toBeVisible();

  releaseTasks();
  await expect(page.getByText("暂无巡检任务，先上传一个数据包开始巡检。")).toBeVisible();
  await expect(
    page.locator(".page-empty-state").getByRole("button", { name: "上传数据包" }),
  ).toBeVisible();
});

/** 用 Tab 键推进焦点直到命中目标，验证键盘可达性（FR-019、contracts §7）。 */
async function tabTo(
  page: import("@playwright/test").Page,
  target: import("@playwright/test").Locator,
  limit = 120,
) {
  const handle = await target.elementHandle();
  if (!handle) return false;
  for (let index = 0; index < limit; index += 1) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate((node) => document.activeElement === node, handle);
    if (focused) return true;
  }
  return false;
}

test("密度切换、复制与展开可键盘触发且有可见焦点", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 密度：Tab 可达、焦点可见、Enter 可切换且不重置筛选。
  const comfortable = page
    .locator('[data-testid="density-control"]')
    .getByRole("button", { name: "舒适" });
  expect(await tabTo(page, comfortable)).toBe(true);
  const densityFocus = await comfortable.evaluate((node) => {
    const style = getComputedStyle(node);
    return { outlineStyle: style.outlineStyle, outlineWidth: Number.parseFloat(style.outlineWidth) };
  });
  expect(densityFocus.outlineStyle).not.toBe("none");
  expect(densityFocus.outlineWidth).toBeGreaterThanOrEqual(2);

  await page.keyboard.press("Enter");
  await expect(page.locator(".task-table")).toHaveClass(/density-comfortable/);

  // 复制与展开 / 收起：进入规则详情继续用键盘操作。
  await page.goto("/tasks/task-alarm-flapping-e2e/rules/alarm.flapping");
  await page
    .context()
    .grantPermissions(["clipboard-read", "clipboard-write"], { origin: "http://127.0.0.1:5183" });

  const sourcePatterns = page.getByTestId("rule-section-source-patterns");
  const patternText = (await sourcePatterns.locator("code").first().textContent())?.trim() ?? "";
  expect(patternText.length).toBeGreaterThan(0);

  const copyButton = sourcePatterns.getByRole("button", { name: "复制源文件匹配" });
  await sourcePatterns.hover();
  expect(await tabTo(page, copyButton)).toBe(true);
  const copyFocus = await copyButton.evaluate((node) => getComputedStyle(node).outlineStyle);
  expect(copyFocus).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page.locator(".rule-detail-source-patterns .copy-text-feedback")).toHaveText("已复制");
  const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboardText).toBe(patternText);

  const toggle = page.locator(".rule-finding-toggle").first();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(await tabTo(page, toggle)).toBe(true);
  const toggleFocus = await toggle.evaluate((node) => getComputedStyle(node).outlineStyle);
  expect(toggleFocus).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});
