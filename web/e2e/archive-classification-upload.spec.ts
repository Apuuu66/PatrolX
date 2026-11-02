import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

const inventoryZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e.zip");
const logSupplementZip = path.join(process.cwd(), "e2e", ".tmp", "log-supplement-e2e.zip");

function selectByLabel(page: Page, label: string) {
  return page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");
}

async function openUpload(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /上传数据包/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
}

async function pickOption(page: Page, label: string, option: string) {
  const select = selectByLabel(page, label);
  const optionLocator = page.locator(
    `.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`,
  );
  await expect(async () => {
    if ((await optionLocator.count()) === 0) {
      await select.click();
    }
    await optionLocator.dispatchEvent("click");
    await expect(select.locator(".ant-select-selection-item")).toContainText(option);
  }).toPass({ timeout: 15_000 });
  await expect(page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")).toHaveCount(0);
}

async function selectFile(page: Page, name: string, source = inventoryZip) {
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: "application/zip",
    buffer: readFileSync(source),
  });
  await expect(page.locator('[data-testid="upload-precheck"]')).toHaveAttribute(
    "data-precheck-valid",
    "true",
  );
}

async function fillInspectionMetadata(page: Page) {
  await pickOption(page, "省份", "江苏");
  await pickOption(page, "运营商", "移动");
}

function submitButton(page: Page) {
  return page.getByRole("button", { name: /提交巡检|提交日志包|覆盖并重建/ });
}

async function installTaskSubmissionCapture(page: Page): Promise<{ body: Promise<string> }> {
  let resolveBody: (value: string) => void = () => undefined;
  let rejectBody: (reason: Error) => void = () => undefined;
  const bodyPromise = new Promise<string>((resolve, reject) => {
    resolveBody = resolve;
    rejectBody = reject;
  });
  await page.route("**/api/v3/tasks", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const body = route.request().postDataBuffer();
    if (!body) {
      rejectBody(new Error("创建任务请求缺少 multipart 请求体"));
      await route.abort();
      return;
    }
    resolveBody(body.toString("utf8"));
    await route.continue();
  });
  return { body: bodyPromise };
}

test("巡检包未选择网元类型时显示字段错误且不提交", async ({ page }) => {
  await openUpload(page);
  await selectFile(page, "archive-missing-product-e2e.zip");
  await fillInspectionMetadata(page);

  let submitted = false;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v3/tasks") {
      submitted = true;
    }
  });

  await submitButton(page).click();

  await expect(page.getByText("请选择网元类型")).toBeVisible();
  expect(submitted).toBe(false);
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
});

test("小写网元类型提交前规范化为 UMF，并展示准备与分类结果", async ({ page }) => {
  await page.route("**/api/v2/dicts", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({
      json: {
        province: [{ code: "JS", name: "江苏" }],
        operator: [{ code: "CMCC", name: "移动" }],
        product: [{ code: "umf", name: "UMF" }],
        version: [],
      },
    });
  });
  await openUpload(page);
  await selectFile(page, "archive-uppercase-e2e.zip");
  await fillInspectionMetadata(page);
  await pickOption(page, "网元类型", "UMF");

  const submission = await installTaskSubmissionCapture(page);
  await submitButton(page).click();
  const body = await submission.body;
  expect(body).toMatch(/name="product"\r\n\r\nUMF\r\n/);

  await page.waitForURL(/\/tasks\/task-archive_uppercase_e2e$/);
  await expect(
    page.locator('[data-testid="conclusion-hero"] .ant-tag').filter({ hasText: "已完成" }),
  ).toBeVisible({ timeout: 30_000 });

  await page.getByText("执行与技术信息").click();
  await expect(page.getByTestId("preparation-units")).toBeVisible();
  await expect(page.getByTestId("preparation-pkg.extract.main")).toBeVisible();
  const classification = page.getByTestId("preparation-pkg.extract.classification");
  await expect(classification).toBeVisible();
  await expect(classification).toContainText(/分类完成|可巡检/);
});

test("日志补充包隐藏且不提交省份、运营商和网元类型", async ({ page }) => {
  await openUpload(page);
  await selectFile(page, "archive-log-supplement-e2e.zip", logSupplementZip);
  await pickOption(page, "包类型", "日志补充包");

  await expect(page.getByText("日志补充包不采集设备信息")).toBeVisible();
  await expect(selectByLabel(page, "省份")).toHaveCount(0);
  await expect(selectByLabel(page, "运营商")).toHaveCount(0);
  await expect(selectByLabel(page, "网元类型")).toHaveCount(0);

  const submission = await installTaskSubmissionCapture(page);
  await submitButton(page).click();
  const body = await submission.body;
  expect(body).toMatch(/name="package_kind"\r\n\r\nlog_supplement\r\n/);
  expect(body).not.toContain('name="province"');
  expect(body).not.toContain('name="operator"');
  expect(body).not.toContain('name="product"');

  await page.waitForURL(/\/tasks\/task-archive_log_supplement_e2e$/);
});

test("同名任务网元类型冲突时稳定错误码可见", async ({ page }) => {
  await page.route("**/api/v3/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({
      status: 409,
      json: {
        code: "package_product_conflict",
        message: "同名任务网元类型不一致",
        detail: { existing: "UMF", requested: "CSP" },
      },
    });
  });
  await openUpload(page);
  await selectFile(page, "archive-conflict-e2e.zip");
  await fillInspectionMetadata(page);
  await pickOption(page, "网元类型", "UMF");

  await submitButton(page).click();

  await expect(page.locator(".ant-message")).toContainText("package_product_conflict");
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
});
