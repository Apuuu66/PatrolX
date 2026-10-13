import { expect, test } from "@playwright/test";
import path from "node:path";

import type { Page } from "@playwright/test";

const ledgerZip = path.join(process.cwd(), "e2e", ".tmp", "device-check-e2e.zip");
const LEDGER_DEVICE_NAME = "E2E-DEV-901";

async function loginAdmin(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

/** 上传单一设备的巡检包，落到设备台账；返回任务 ID。 */
async function uploadLedgerPackage(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: /上传/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
  await page.setInputFiles('input[type="file"]', ledgerZip);
  const selectByLabel = (label: string) =>
    page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");
  for (const [label, option] of [
    ["省份", "江苏"],
    ["运营商", "移动"],
    ["网元类型", "UMF"],
  ] as const) {
    await selectByLabel(label).click();
    await page
      .locator(
        `.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`,
      )
      .click();
  }
  await page.getByRole("button", { name: "提交巡检" }).click();
  await page.waitForURL(/\/tasks\/task-/);
  return new URL(page.url()).pathname.split("/").filter(Boolean).pop() as string;
}

async function taskStatus(page: Page, taskId: string): Promise<string> {
  const response = await page.request.get(`/api/v2/tasks/${taskId}`);
  return ((await response.json()) as { status: string }).status;
}

function devicePatch(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" && response.url().includes("/device-id"),
  );
}

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

test("任务列表操作全部平铺，高频入口一次点击可达", async ({ page }) => {
  await page.goto("/");
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();

  // 操作列不再收缩：详情、失败日志、重建、删除全部平铺常驻（2026-10-13 修订）
  await expect(taskRow.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(taskRow.locator('[data-testid="task-failure-reason"]')).toBeVisible();
  await expect(taskRow.getByRole("button", { name: "失败日志" })).toBeVisible();
  await expect(taskRow.getByRole("button", { name: "重建" })).toBeVisible();
  await expect(taskRow.getByRole("button", { name: "删除" })).toBeVisible();
  await expect(taskRow.getByRole("button", { name: "更多操作" })).toHaveCount(0);
  // 列表只保留"重建"：重跑与更名前的"全量重建"都不再出现
  await expect(taskRow.getByRole("button", { name: "重跑" })).toHaveCount(0);
  await expect(taskRow.getByRole("button", { name: "全量重建" })).toHaveCount(0);

  // 行内失败日志一次点击进入日志页（FR-026）
  await taskRow.getByRole("button", { name: "失败日志" }).click();
  await expect(page).toHaveURL(/\/tasks\/task-home-failed\/logs$/);
});

test("已完成任务的报告入口常驻可见并一次点击进入报告", async ({ page }) => {
  await page.goto("/");
  const completedRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "task-kpi-history-current" })
    .first();

  // 报告不再 hover 才显现，行内常驻可见且可用（2026-10-13 修订）
  const reportButton = completedRow.getByRole("button", { name: "报告" });
  await expect(reportButton).toBeVisible();
  await expect(reportButton).toBeEnabled();
  await reportButton.click();
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

test("手动设备 ID 必须是台账内设备：不存在被拒绝、存在可保存", async ({ page }) => {
  // 用例包含真实上传与巡检执行，默认 30s 不够。
  test.setTimeout(120_000);
  await loginAdmin(page);
  const uploadedTaskId = await uploadLedgerPackage(page);
  await expect
    .poll(() => taskStatus(page, uploadedTaskId), { timeout: 30_000 })
    .toBe("completed");
  await page.reload();

  // 未手工填写时展示台账解析出的网元名称（FR-010 前置状态）
  await page.getByTestId("technical-collapse").getByText("执行与技术信息").click();
  const deviceCell = page.locator(".ant-descriptions-item").filter({ hasText: "设备 ID" });
  await expect(deviceCell).toContainText(LEDGER_DEVICE_NAME);
  await expect(deviceCell).toContainText("台账解析");

  const devicesBody = (await (
    await page.request.get("/api/v2/inventory/devices?page=1&page_size=100")
  ).json()) as { items: { device_id: string; device_name: string }[] };
  const ledgerDevice = devicesBody.items.find((item) => item.device_name === LEDGER_DEVICE_NAME);
  expect(ledgerDevice, `台账缺少设备 ${LEDGER_DEVICE_NAME}`).toBeTruthy();
  const ledgerDeviceId = ledgerDevice!.device_id;

  const modal = page.locator(".ant-modal").filter({ hasText: "修改设备 ID" });
  const input = modal.getByPlaceholder("输入设备 ID");
  // antd 按钮在快速 loading 切换后可能残留动画节点污染可访问名（如 "loading 保 存"），
  // 这里按弹窗底部按钮位置定位，避免 a11y 名称竞态导致的误判。
  const saveButton = modal.locator(".ant-modal-footer button").last();
  const cancelButton = modal.locator(".ant-modal-footer button").first();

  // 不存在于台账的 ID：400 拒绝 + 弹窗内明确提示，任务记录保持原值
  await deviceCell.getByRole("button", { name: "编辑" }).click();
  await input.fill("NOT-EXIST-E2E");
  const rejectedPromise = devicePatch(page);
  await saveButton.click();
  const rejected = await rejectedPromise;
  expect(rejected.status()).toBe(400);
  expect(((await rejected.json()) as { code: string }).code).toBe("device_not_found");
  await expect(page.getByTestId("device-id-error")).toContainText("设备 ID 不存在于设备台账");
  await expect(modal).toBeVisible();

  const afterReject = (await (
    await page.request.get(`/api/v2/tasks/${uploadedTaskId}`)
  ).json()) as { system: { customer: Record<string, string> } };
  expect(afterReject.system.customer.device_id ?? "").toBe("");
  await cancelButton.click();

  // 台账内的 ID：保存成功，任务详情同步展示新值
  await deviceCell.getByRole("button", { name: "编辑" }).click();
  await input.fill(ledgerDeviceId);
  const acceptedPromise = devicePatch(page);
  await saveButton.click();
  const accepted = await acceptedPromise;
  expect(accepted.status()).toBe(200);
  await expect(page.getByText("设备 ID 已更新")).toBeVisible();
  await expect(deviceCell).toContainText(ledgerDeviceId);
});
