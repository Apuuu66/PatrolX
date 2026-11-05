import { expect, type Page, test } from "@playwright/test";

const TASK_ID = "task-kpi-daily-health";
const LEGACY_TASK_ID = "task-kpi-daily-health-legacy";
const RULE_CODE = "kpi.measurement_units";
const RATE_ID = "ME_HEALTH_RATE_1";

const CURRENT_LABELS = ["正常", "预警", "失败", "待配置", "无法判定", "不适用"] as const;
const TREND_LABELS = ["改善", "稳定", "恶化", "关注", "无昨日基线"] as const;

async function login(page: Page, username: string, password: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText(username, { exact: true })).toBeVisible();
}

async function expectDistributionMatchesTable(
  page: Page,
  kind: "current" | "trend",
  labels: readonly string[],
) {
  const rows = page.getByTestId("daily-health-metric-row");
  const statusIds = kind === "current"
    ? ["normal", "warn", "fail", "pending_config", "unable_to_judge", "not_applicable"]
    : ["improved", "stable", "worsened", "observe", "no_baseline"];
  for (const [index, label] of labels.entries()) {
    const shown = Number(await page.getByTestId(`${kind}-${statusIds[index]}`).locator("strong").innerText());
    const expectedText = kind === "current" ? `当前：${label}` : `趋势：${label}`;
    await expect(rows.filter({ hasText: expectedText })).toHaveCount(shown);
  }
}

test("首屏同时回答当前判定与昨日趋势，证据按需加载且四个成功率独立", async ({ page }) => {
  const startedAt = Date.now();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const apiErrors: string[] = [];
  const detailRequests: string[] = [];
  const kpiPointRequests: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes(`/daily-health/${encodeURIComponent("MU_HEALTH_CALL")}/${encodeURIComponent(RATE_ID)}`)) {
      detailRequests.push(url);
    }
    if (url.includes("kpi-points") || url.includes("/kpi/points")) kpiPointRequests.push(url);
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      apiErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto(`/tasks/${TASK_ID}/rules/${RULE_CODE}`);
  await expect(page.getByRole("heading", { name: "KPI 当前判定与昨日趋势" })).toBeVisible();
  await expect(page.getByText("数据日期 2026-11-05", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前判定", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "较昨日趋势", exact: true })).toBeVisible();
  await expect(page.getByTestId("daily-health-scope")).toContainText("启用测量单元 4");
  await expect(page.getByTestId("current-total")).toHaveText("合计 20");
  await expect(page.getByTestId("trend-total")).toHaveText("合计 20");

  const rows = page.getByTestId("daily-health-metric-row");
  await expect(rows).toHaveCount(20);
  const unitIds = await rows.locator("td:first-child .kpi-health-secondary").allTextContents();
  expect(new Set(unitIds).size).toBe(4);

  await expectDistributionMatchesTable(page, "current", CURRENT_LABELS);
  await expectDistributionMatchesTable(page, "trend", TREND_LABELS);

  const table = page.getByRole("table", { name: "KPI 日健康指标结论" });
  const toolbar = page.locator(".kpi-health-table-toolbar");
  await expect(toolbar).toBeVisible();
  expect(await toolbar.evaluate((element) => getComputedStyle(element).display)).toBe("flex");
  expect(await page.getByTestId("current-fail").evaluate((element) => getComputedStyle(element).cursor)).toBe("pointer");

  await page.getByTestId("current-fail").click();
  await expect(page.getByTestId("daily-health-filter-total")).toHaveText("显示 1 / 20");
  await expect(rows).toHaveCount(1);
  await expect(table.locator(".kpi-health-role").first()).toHaveText("聚合指标");

  const reset = page.getByRole("button", { name: "重置筛选" });
  await expect(reset).toBeVisible();
  expect(await reset.evaluate((element) => getComputedStyle(element).cursor)).toBe("pointer");
  await reset.click();
  await expect(rows).toHaveCount(20);

  await page.getByLabel("按当前判定筛选").selectOption("fail");
  await page.getByLabel("按昨日趋势筛选").selectOption("improved");
  await expect(page.getByTestId("daily-health-filter-total")).toHaveText("显示 0 / 20");
  const emptyCell = table.locator(".kpi-health-table-empty");
  await expect(emptyCell).toHaveText("当前筛选条件下没有指标。");
  expect(await emptyCell.evaluate((element) => getComputedStyle(element).textAlign)).toBe("center");
  await page.getByRole("button", { name: "重置筛选" }).click();
  await expect(rows).toHaveCount(20);

  const rateNames = [
    "媒体资源创建成功率",
    "媒体资源创建请求成功率",
    "DC 资源更新成功率",
    "数据通道资源更新请求成功率",
  ];
  await expect(rows.filter({ hasText: "成功率" })).toHaveCount(4);
  for (const [index, name] of rateNames.entries()) {
    const rateRow = rows.filter({ hasText: name });
    await expect(rateRow).toHaveCount(1);
    await expect(rateRow).toContainText(`ME_HEALTH_RATE_${index + 1}`);
  }
  const focus = page.getByTestId("daily-health-focus");
  await expect(focus).toBeVisible();
  const attentionNames: string[] = [];
  for (let index = 0; index < await rows.count(); index += 1) {
    const row = rows.nth(index);
    const rowText = await row.innerText();
    if (/当前：(失败|预警|待配置|无法判定)/.test(rowText) || rowText.includes("趋势：恶化")) {
      attentionNames.push(await row.locator(".kpi-health-metric-name").innerText());
    }
  }
  expect(attentionNames.length).toBeGreaterThan(0);
  const focusRows = focus.getByTestId("focus-metric");
  await expect(focusRows).toHaveCount(attentionNames.length);
  for (const metricName of attentionNames) {
    await expect(focusRows.filter({ hasText: metricName })).toHaveCount(1);
  }
  expect(Date.now() - startedAt).toBeLessThan(30_000);
  expect(detailRequests).toEqual([]);

  const detailResponse = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v2/tasks/${TASK_ID}/rules/${RULE_CODE}/daily-health/MU_HEALTH_CALL/${RATE_ID}`,
      ) && response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "查看 媒体资源创建成功率 证据" }).click();
  expect((await detailResponse).status()).toBe(200);

  const dialog = page.getByRole("dialog", { name: "媒体资源创建成功率" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("129 / 200 = 64.5%");
  await expect(dialog.getByTestId("daily-health-seven-day-trend")).toBeVisible();
  await expect(dialog.getByTestId("daily-health-group")).toContainText("pod-health-a");
  await expect(dialog.getByTestId("daily-health-group")).toContainText("15 分钟");
  await dialog.getByRole("button", { name: "关闭指标证据" }).click();
  await expect(dialog).toBeHidden();
  expect(kpiPointRequests).toEqual([]);

  const noHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(noHorizontalOverflow).toBe(true);
  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("管理员可维护配置并查看审计，viewer 只能查看", async ({ page }) => {
  await login(page, "e2e-admin", "e2e-admin-123");
  await page.goto("/measurement-units");
  await page.getByRole("tab", { name: "维护配置" }).click();
  await expect(page.getByRole("heading", { name: "指标维护配置" })).toBeVisible();

  const maintenanceTable = page.getByRole("table", { name: "指标维护配置" });
  const row = maintenanceTable
    .getByRole("row")
    .filter({ has: page.getByText(RATE_ID, { exact: true }) });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "编辑维护配置" }).click();

  const editor = page.getByRole("dialog", { name: /编辑维护配置/ });
  await expect(editor).toBeVisible();
  await editor.getByLabel("预警阈值").fill("98.5");
  const updateResponse = page.waitForResponse(
    (response) =>
      response.url().includes(
        `/api/v5/kpi/metric-maintenance-configs/MU_HEALTH_CALL/${RATE_ID}`,
      ) && response.request().method() === "PATCH",
  );
  await editor.getByRole("button", { name: /^保\s*存$/ }).click();
  expect((await updateResponse).status()).toBe(200);
  await expect(editor).toBeHidden();

  await row.getByRole("button", { name: "审计记录" }).click();
  const auditDialog = page.getByRole("dialog", { name: /维护审计/ });
  await expect(auditDialog).toBeVisible();
  await expect(auditDialog).toContainText("e2e-admin");
  await expect(auditDialog).toContainText("warning_threshold");
  await auditDialog.getByRole("button", { name: /^关\s*闭$/ }).click();

  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await login(page, "e2e-viewer", "e2e-viewer-123");
  await page.goto("/measurement-units");
  await page.getByRole("tab", { name: "维护配置" }).click();
  await expect(page.getByRole("heading", { name: "指标维护配置" })).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑维护配置" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "编辑聚合配置" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "审计记录" }).first()).toBeVisible();
});

test("旧 KPI 任务缺少日健康字段时显示兼容提示且页面不崩溃", async ({ page }) => {
  await page.goto(`/tasks/${LEGACY_TASK_ID}/rules/${RULE_CODE}`);
  await expect(page.getByRole("heading", { name: "KPI 日健康兼容提示" })).toBeVisible();
  await expect(page.getByText(/旧任务没有日健康结论/)).toBeVisible();
  await expect(page.getByTestId("daily-health-metric-row")).toHaveCount(0);
});
