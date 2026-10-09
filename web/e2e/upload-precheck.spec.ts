import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

const inventoryZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e.zip");
const PACKAGE_NAME = "precheck-e2e.zip";
const TASK_ID = "task-precheck_e2e";

async function openUpload(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /上传数据包/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
  return page.locator('input[type="file"]');
}

/** 巡检包必须携带省份 / 运营商，否则后端按 400 拒绝；这里沿用 E2E 字典项。 */
async function fillInspectionMetadata(page: Page) {
  const selectByLabel = (label: string) =>
    page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");
  for (const [label, option] of [
    ["省份", "江苏"],
    ["运营商", "移动"],
    ["网元类型", "UMF"],
  ] as const) {
    await selectByLabel(label).click();
    await page
      .locator(`.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`)
      .click();
  }
}

test("合法数据包在 1 秒内展示任务 ID 预览、文件大小与校验结论", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const input = await openUpload(page);

  await input.setInputFiles(inventoryZip);

  // SC-007：选择文件后立即（1 秒内）给出可核对的前置信息。
  const precheck = page.locator('[data-testid="upload-precheck"]');
  await expect(precheck).toBeVisible({ timeout: 1000 });
  await expect(precheck).toHaveAttribute("data-precheck-valid", "true");
  await expect(page.locator('[data-testid="upload-task-id-preview"]')).toHaveText(
    "task-inventory_e2e",
  );
  await expect(page.locator('[data-testid="upload-file-size"]')).toHaveText(/^\d+(\.\d+)? (B|KB|MB|GB)$/);
  await expect(precheck).toContainText("校验通过，可以提交");
  await expect(page.getByRole("button", { name: "提交巡检" })).toBeEnabled();
});

test("非法文件在选择阶段即禁用提交并给出具体原因", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const input = await openUpload(page);
  const precheck = page.locator('[data-testid="upload-precheck"]');
  const submit = page.getByRole("button", { name: "提交巡检" });

  await input.setInputFiles({
    name: "sample.rar",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("not a package"),
  });
  await expect(precheck).toHaveAttribute("data-precheck-valid", "false");
  await expect(precheck).toContainText("仅支持 zip");
  await expect(submit).toBeDisabled();

  await input.setInputFiles({
    name: "empty.zip",
    mimeType: "application/zip",
    buffer: Buffer.alloc(0),
  });
  await expect(precheck).toContainText("数据包为空");
  await expect(submit).toBeDisabled();

  await input.setInputFiles({
    name: `${"a".repeat(256)}.zip`,
    mimeType: "application/zip",
    buffer: Buffer.from("payload"),
  });
  await expect(precheck).toContainText("255 字节");
  await expect(submit).toBeDisabled();
});

test("同名数据包分别给出打开已有任务与 checksum 冲突的下一步动作", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const buffer = readFileSync(inventoryZip);

  // 首次上传：创建任务并进入详情。
  const firstInput = await openUpload(page);
  await firstInput.setInputFiles({ name: PACKAGE_NAME, mimeType: "application/zip", buffer });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: "提交巡检" }).click();
  await page.waitForURL(new RegExp(`/tasks/${TASK_ID}$`));

  // 同名且 checksum 相同：提示将打开已有任务，而不是重复创建。
  const sameInput = await openUpload(page);
  await sameInput.setInputFiles({ name: PACKAGE_NAME, mimeType: "application/zip", buffer });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: "提交巡检" }).click();
  await expect(page.locator(".ant-message").getByText("同名数据包已存在，将打开已有任务")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/tasks/${TASK_ID}$`));

  // 同名但 checksum 不同：弹窗内给出两个下一步动作，且提交不会覆盖已有结果。
  const conflictInput = await openUpload(page);
  await conflictInput.setInputFiles({
    name: PACKAGE_NAME,
    mimeType: "application/zip",
    buffer: Buffer.from("different package content"),
  });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: "提交巡检" }).click();

  const conflict = page.locator('[data-testid="upload-conflict"]');
  await expect(conflict).toBeVisible();
  await expect(conflict).toContainText("checksum");
  await expect(conflict.getByRole("button", { name: "修改文件名" })).toBeVisible();
  await expect(conflict.getByRole("button", { name: "查看已有任务" })).toBeVisible();

  // 修改文件名：清空当前选择与提示，等待重新选择。
  await conflict.getByRole("button", { name: "修改文件名" }).click();
  await expect(conflict).toBeHidden();
  await expect(page.locator('[data-testid="upload-precheck"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "提交巡检" })).toBeDisabled();

  // 再次提交同名不同内容的数据包，走"查看已有任务"进入既有任务。
  await page
    .locator('input[type="file"]')
    .setInputFiles({
      name: PACKAGE_NAME,
      mimeType: "application/zip",
      buffer: Buffer.from("different package content"),
    });
  await page.getByRole("button", { name: "提交巡检" }).click();
  await expect(conflict).toBeVisible();
  await conflict.getByRole("button", { name: "查看已有任务" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${TASK_ID}$`));
});
