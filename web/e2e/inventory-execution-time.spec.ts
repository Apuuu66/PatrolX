import { expect, test } from "@playwright/test";
import path from "node:path";

import type { Page } from "@playwright/test";

const lateZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e-time-late.zip");
const earlierZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e-time-earlier.zip");
const missingZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e-time-missing.zip");

/** 较晚执行包（执行时间 2026-03-10）与较早执行包（2026-03-05）使用同一台设备。 */
const DEVICE_NAME = "E2E-TIME-901";
const LATE_DATE = "2026-03-10";
const EARLIER_DATE = "2026-03-05";
const LATE_VERSION = "V900R016C10SPC200";
const EARLIER_VERSION = "V900R016C10SPC090";

/** 头部没有执行时间的包使用独立设备，避免与乱序补传用例互相影响。 */
const FALLBACK_DEVICE_NAME = "E2E-TIME-NONE-901";

async function uploadPackage(page: Page, file: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /上传/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();

  await page.setInputFiles('input[type="file"]', file);
  const selectByLabel = (label: string) =>
    page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");
  const pickOption = async (label: string, option: string) => {
    await selectByLabel(label).click();
    await page
      .locator(`.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`)
      .click();
  };
  await pickOption("省份", "江苏");
  await pickOption("运营商", "移动");
  await pickOption("网元类型", "UMF");

  await page.getByRole("button", { name: /提交巡检|覆盖并重建/ }).click();

  // 同名包会先弹覆盖确认，确认后清空旧现场并全量重建（FR-024）。
  const confirm = page.locator(".ant-modal-confirm");
  const overwritten = await Promise.race([
    page.waitForURL(/\/tasks\//).then(() => false, () => false),
    confirm.waitFor({ state: "visible", timeout: 10_000 }).then(() => true, () => false),
  ]);
  if (overwritten) {
    await confirm.getByRole("button", { name: "覆盖并重建" }).click();
  }
  await page.waitForURL(/\/tasks\//);
  // 台账归档在任务收尾阶段完成，回到终态后才读取设备台账。
  await expect(
    page.locator('[data-testid="conclusion-hero"] .ant-tag').filter({ hasText: "已完成" }),
  ).toBeVisible({ timeout: 30_000 });
}

async function openDevice(page: Page, deviceName: string) {
  await page.goto("/inventory");
  const row = page.getByRole("row").filter({ hasText: deviceName });
  await expect(row).toHaveCount(1);
  await row.getByText(deviceName).click();
  await expect(page).toHaveURL(/\/inventory\/devices\//);
  await expect(page.getByRole("heading", { name: deviceName })).toBeVisible();
}

test("补传执行时间更早的包后设备当前版本与最近观测都不回退", async ({ page }) => {
  await uploadPackage(page, lateZip);
  await uploadPackage(page, earlierZip);

  await page.goto("/inventory");
  const row = page.getByRole("row").filter({ hasText: DEVICE_NAME });
  await expect(row).toHaveCount(1);
  // 当前版本取执行时间最近的观测，不被后补传的旧包覆盖（FR-005、SC-001）。
  await expect(row).toContainText(LATE_VERSION);
  await expect(row).not.toContainText(EARLIER_VERSION);
  await expect(row).toContainText(LATE_DATE);

  await openDevice(page, DEVICE_NAME);
  // 设备详情当前版本同样是较晚执行的版本，来源标注为设备执行时间（SC-004、SC-005）。
  const currentVersionItem = page.locator(".ant-descriptions-item").filter({ hasText: "当前版本" }).first();
  await expect(currentVersionItem).toContainText(LATE_VERSION);

  const versionRows = page
    .locator(".ant-card")
    .filter({ hasText: "版本历史" })
    .getByRole("row")
    .filter({ hasText: "V900R016C10SPC" });
  await expect(versionRows).toHaveCount(2);
  // 版本历史按执行时间升序呈现：较早的补传包在前，较晚的在前一包在后（FR-008）。
  await expect(versionRows.nth(0)).toContainText(EARLIER_VERSION);
  await expect(versionRows.nth(0)).toContainText(EARLIER_DATE);
  await expect(versionRows.nth(0)).not.toContainText("降级");
  await expect(versionRows.nth(1)).toContainText(LATE_VERSION);
  await expect(versionRows.nth(1)).toContainText(LATE_DATE);
  // 较早执行的版本在前、较晚执行的版本在后，方向按执行时间升序判定为升级（FR-008、SC-005）。
  await expect(versionRows.nth(1)).toContainText("升级");
  await expect(versionRows.first()).toContainText("执行时间");
});

test("任务详情台账面板展示本次归档使用的执行时间与来源", async ({ page }) => {
  await uploadPackage(page, lateZip);

  await page.getByRole("tab", { name: "设备台账" }).click();
  const evidence = page.getByTestId("task-inventory-execution-time");
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText("设备执行时间");
  await expect(evidence).toContainText("解析成功");
  await expect(evidence).toContainText("config/LST ME.txt");
  await expect(evidence).toContainText("第 1 行");
  await expect(evidence).toContainText(LATE_DATE);
  // 原始行原文可回溯（FR-012）。
  await expect(evidence).toContainText("CSP/*××××××××××××*/");
});

test("头部无执行时间时回退任务完成时间并标注可读原因", async ({ page }) => {
  await uploadPackage(page, missingZip);

  await page.getByRole("tab", { name: "设备台账" }).click();
  const evidence = page.getByTestId("task-inventory-execution-time");
  await expect(evidence).toContainText("任务完成时间兜底");
  await expect(evidence).toContainText("头部未找到执行时间行");

  await openDevice(page, FALLBACK_DEVICE_NAME);
  const latestItem = page.locator(".ant-descriptions-item").filter({ hasText: "最近观测" });
  await expect(latestItem).toContainText("兜底时间");
  await expect(latestItem).toContainText("头部未找到执行时间行");

  // 观测历史逐行标注来源，悬停可读回退原因（SC-004）。
  const fallbackTag = page.getByText("兜底时间").last();
  await fallbackTag.hover();
  await expect(page.getByRole("tooltip")).toContainText("头部未找到执行时间行");
});
