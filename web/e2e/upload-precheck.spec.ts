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
    const select = selectByLabel(label);
    const optionLocator = page.locator(
      `.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`,
    );
    // 上传预览响应会使上传弹窗重渲染并替换下拉选项，被替换的元素点击会报 detached；
    // 同时 AntD 虚拟列表会在 Playwright 自动滚动时回收边缘选项。这里对已渲染选项
    // 直接派发点击，并用选中结果兜住重渲染，不触发虚拟列表滚动。
    await expect(async () => {
      if ((await optionLocator.count()) === 0) {
        await select.click();
      }
      await optionLocator.dispatchEvent("click");
      await expect(select.locator(".ant-select-selection-item")).toHaveText(option);
    }).toPass({ timeout: 15_000 });
    await expect(page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")).toHaveCount(0);
  }
}

test("同名数据包提交前确认覆盖，确认后清空旧现场并全量重建", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const buffer = readFileSync(inventoryZip);

  // 首次上传：创建任务并进入详情。
  const firstInput = await openUpload(page);
  await firstInput.setInputFiles({ name: PACKAGE_NAME, mimeType: "application/zip", buffer });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: "提交巡检" }).click();
  await page.waitForURL(new RegExp(`/tasks/${TASK_ID}$`));

  // 同名同内容：不再静默打开旧任务，先确认覆盖，确认后删除旧现场再全量重建。
  const duplicateInput = await openUpload(page);
  await duplicateInput.setInputFiles({ name: PACKAGE_NAME, mimeType: "application/zip", buffer });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: /提交巡检|覆盖并重建/ }).click();

  const confirm = page.locator(".ant-modal-confirm");
  await expect(confirm).toBeVisible();
  await expect(confirm).toContainText("覆盖同名任务并全量重建？");
  await expect(confirm).toContainText("原数据包与巡检结果会被清除");
  await confirm.getByRole("button", { name: "覆盖并重建" }).click();

  await expect(page.locator(".ant-message").getByText("已覆盖同名数据包，开始全量重建")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/tasks/${TASK_ID}$`));

  // 同名不同内容：同样先确认覆盖，不再以 checksum 冲突阻断提交。
  const conflictInput = await openUpload(page);
  await conflictInput.setInputFiles({
    name: PACKAGE_NAME,
    mimeType: "application/zip",
    buffer: Buffer.from("different package content"),
  });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: /提交巡检|覆盖并重建/ }).click();
  await expect(confirm).toBeVisible();
  await expect(confirm).toContainText("覆盖同名任务并全量重建？");

  // 取消覆盖：既有任务保持可用，弹窗内继续给出覆盖说明。
  // AntD 会在两字中文按钮中插入空格，因此用宽松名称匹配取消按钮
  await confirm.getByRole("button", { name: /取\s*消/ }).click();
  await expect(confirm).toBeHidden();
  await expect(page.locator('[data-testid="upload-existing-task-hint"]')).toContainText(
    "覆盖原数据包并全量重建",
  );
});

test("同名任务探测不通过时以 checksum 冲突提示给出覆盖与保留现场动作", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v2/tasks") {
      // 同名任务不在当前页，预览阶段无法从列表命中。
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 10 } });
    }
    if (url.pathname === `/api/v2/tasks/${TASK_ID}`) {
      return route.fulfill({
        status: 404,
        json: { code: "not_found", message: "任务不存在", detail: null },
      });
    }
    return route.continue();
  });
  await page.route("**/api/v3/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({
      status: 409,
      json: {
        code: "package_checksum_conflict",
        message: "同名任务已存在，但数据包 checksum 不同",
        detail: null,
      },
    });
  });

  const input = await openUpload(page);
  await input.setInputFiles({
    name: PACKAGE_NAME,
    mimeType: "application/zip",
    buffer: readFileSync(inventoryZip),
  });
  await fillInspectionMetadata(page);
  await page.getByRole("button", { name: "提交巡检" }).click();

  const conflict = page.locator('[data-testid="upload-conflict"]');
  await expect(conflict).toBeVisible();
  await expect(conflict).toContainText("checksum");
  await expect(conflict.getByRole("button", { name: "覆盖并全量重建" })).toBeVisible();
  await expect(conflict.getByRole("button", { name: "修改文件名" })).toBeVisible();
  await expect(conflict.getByRole("button", { name: "查看已有任务" })).toBeVisible();

  // 修改文件名：清空当前选择与提示，等待重新选择。
  await conflict.getByRole("button", { name: "修改文件名" }).click();
  await expect(conflict).toBeHidden();
  await expect(page.locator('[data-testid="upload-precheck"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "提交巡检" })).toBeDisabled();
});
