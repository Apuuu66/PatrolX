import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import type { Locator, Page } from "@playwright/test";

const LEGACY_TASK_ID = "task-kpi-v6-legacy-rebuild";
const LEGACY_PACKAGE_FILE = "KPI-V6-LEGACY-REBUILD.zip";
const E2E_ROOT = process.env.PATROLX_E2E_TEST_ROOT ?? path.join(process.cwd(), "e2e", ".tmp");
const LEGACY_PACKAGE = path.join(E2E_ROOT, "uploads", LEGACY_TASK_ID, LEGACY_PACKAGE_FILE);

async function loginAdmin(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

async function showAllTasks(page: Page): Promise<void> {
  await page.locator(".ant-pagination-options .ant-select-selector").click();
  const option = page
    .locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option")
    .filter({ hasText: /^100\s*条\/页$/ });
  await expect(option).toBeVisible();
  await option.click();
  await expect(page.locator(".ant-pagination-options .ant-select-selection-item")).toHaveText(
    /100\s*条\/页/,
  );
}

function taskRow(page: Page, taskId: string): Locator {
  return page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ has: page.locator(`code:text-is("${taskId}")`) })
    .first();
}

async function taskStatus(page: Page, taskId: string): Promise<string> {
  const response = await page.request.get(`/api/v2/tasks/${taskId}`);
  return ((await response.json()) as { status: string }).status;
}

async function sha256(filePath: string): Promise<string> {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

test("旧任务必须按当前配置全量重建且保持原包不变", async ({ page }) => {
  test.setTimeout(120_000);
  const packageSha256Before = await sha256(LEGACY_PACKAGE);

  await loginAdmin(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  const summaryResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === `/api/v6/kpi/tasks/${LEGACY_TASK_ID}/summary`,
  );
  await page.goto(`/tasks/${LEGACY_TASK_ID}`);
  const summaryResponse = await summaryResponsePromise;
  expect(summaryResponse.status()).toBe(409);
  expect((await summaryResponse.json()) as { code: string }).toMatchObject({
    code: "task_result_requires_rebuild",
  });

  const rebuildRequired = page.getByTestId("task-kpi-rebuild-required");
  await expect(rebuildRequired).toContainText("task_result_requires_rebuild");
  await expect(rebuildRequired).toContainText("旧任务不迁移结果");
  await expect(page.getByTestId("task-kpi-entry")).toHaveCount(0);

  await page.goto("/tasks");
  await showAllTasks(page);
  const legacyRow = taskRow(page, LEGACY_TASK_ID);
  await expect(legacyRow).toBeVisible();
  await legacyRow.getByRole("button", { name: "重建" }).click();

  const confirm = page.locator(".ant-modal-confirm").filter({ hasText: "重建该任务？" });
  await expect(confirm).toContainText("删除并重建任务输出");
  await expect(confirm).toContainText("该操作不可撤销");
  await expect(confirm).toContainText("原始上传包只读");

  const acceptedResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/v2/tasks/${LEGACY_TASK_ID}/rebuild`,
  );
  await confirm.getByRole("button", { name: /^重\s*建$/ }).click();
  const acceptedResponse = await acceptedResponsePromise;
  expect(acceptedResponse.status()).toBe(202);
  expect(acceptedResponse.headers().location).toBe(`/api/v2/tasks/${LEGACY_TASK_ID}`);
  expect((await acceptedResponse.json()) as { task_id: string }).toEqual({ task_id: LEGACY_TASK_ID });
  await expect(page.locator(".ant-message").getByText("已受理重建")).toBeVisible();

  await expect.poll(() => taskStatus(page, LEGACY_TASK_ID), { timeout: 90_000 }).toBe("completed");
  expect(await sha256(LEGACY_PACKAGE)).toBe(packageSha256Before);

  await page.goto(`/tasks/${LEGACY_TASK_ID}`);
  const kpiEntry = page.getByTestId("task-kpi-entry");
  await expect(kpiEntry).toBeVisible();
  await expect(kpiEntry).toContainText("UMF");
  await kpiEntry.getByRole("button", { name: "查看 KPI 巡检结果" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${LEGACY_TASK_ID}/kpi$`));
  await expect(page.getByTestId("kpi-result-visible-total")).toContainText("当前可见");
});
