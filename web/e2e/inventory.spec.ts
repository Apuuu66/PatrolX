import { expect, test } from "@playwright/test";
import path from "node:path";

const inspectionZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e.zip");
const logZip = path.join(process.cwd(), "e2e", ".tmp", "log-supplement-e2e.zip");

async function uploadPackage(page: import("@playwright/test").Page, file: string, kind: "inspection" | "log") {
  await page.goto("/");
  await page.getByRole("button", { name: /上传/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
  await page.setInputFiles('input[type="file"]', file);
  const selectByLabel = (label: string) =>
    page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");

  if (kind === "log") {
    await selectByLabel("包类型").click();
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="日志补充包"]')
      .click();
  }

  if (kind === "inspection") {
    await selectByLabel("省份").click();
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="江苏"]')
      .click();
    await selectByLabel("运营商").click();
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="移动"]')
      .click();
  } else {
    await expect(page.getByText("日志补充包不采集设备信息")).toBeVisible();
    await expect(page.locator(".ant-form-item").filter({ hasText: "省份" })).toBeHidden();
    await expect(page.locator(".ant-form-item").filter({ hasText: "运营商" })).toBeHidden();
  }

  await page.getByRole("button", { name: kind === "inspection" ? "提交巡检" : "提交日志包" }).click();
  await page.waitForURL(/\/tasks\//);
}

test("巡检包上传后可在任务详情、局点台账和设备详情间追踪", async ({ page }) => {
  await uploadPackage(page, inspectionZip, "inspection");

  await expect(page.getByRole("tab", { name: "设备台账" })).toBeVisible();
  await page.getByRole("tab", { name: "设备台账" }).click();
  await expect(page.getByText("已归档")).toBeVisible();
  await expect(page.getByText("V900R016C10SPC200")).toBeVisible();
  await page.getByRole("link", { name: "查看设备台账详情" }).click();
  await expect(page).toHaveURL(/\/inventory\/devices\//);
  await expect(page.getByRole("heading", { name: "NJ-AGG-001" })).toBeVisible();
  await expect(page.getByText("V900R016C10SPC200").first()).toBeVisible();
  await expect(page.getByText("版本历史")).toBeVisible();
  await expect(page.getByText("观测历史")).toBeVisible();

  await page.getByRole("button", { name: "返回台账" }).click();
  await expect(page).toHaveURL(/\/inventory$/);
  await expect(page.getByText("NJ-AGG-001").first()).toBeVisible();
});

test("日志补充包显示不涉及设备台账且不进入局点台账", async ({ page }) => {
  await uploadPackage(page, logZip, "log");

  await page.getByRole("tab", { name: "设备台账" }).click();
  await expect(page.getByText("日志补充包不涉及设备台账")).toBeVisible();
  await expect(page.getByText("该类型不解析设备信息，也不产生台账观测或质量问题。")).toBeVisible();
});
