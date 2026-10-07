import { expect, test } from "@playwright/test";
import path from "node:path";

const inspectionZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e.zip");
const logZip = path.join(process.cwd(), "e2e", ".tmp", "log-supplement-e2e.zip");
const rerunZip = path.join(process.cwd(), "e2e", ".tmp", "inventory-e2e-rerun.zip");

async function uploadPackage(page: import("@playwright/test").Page, file: string, kind: "inspection" | "log") {
  await page.goto("/");
  await page.getByRole("button", { name: /上传/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
  await expect(page.locator(".ant-form-item").filter({ hasText: "任务名称" })).toBeHidden();
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
    await selectByLabel("网元类型").click();
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="核心网"]')
      .click();
  } else {
    await expect(page.getByText("日志补充包不采集设备信息")).toBeVisible();
    await expect(page.locator(".ant-form-item").filter({ hasText: "省份" })).toBeHidden();
    await expect(page.locator(".ant-form-item").filter({ hasText: "运营商" })).toBeHidden();
  }

  await page.getByRole("button", { name: kind === "inspection" ? "提交巡检" : "提交日志包" }).click();
  await page.waitForURL(/\/tasks\//);
}

async function loginAdmin(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

test("巡检包上传后可在任务详情、设备台账和设备详情间追踪", async ({ page }) => {
  await uploadPackage(page, inspectionZip, "inspection");

  await expect(page.getByRole("tab", { name: "设备台账" })).toBeVisible();
  await page.getByRole("tab", { name: "设备台账" }).click();
  await expect(page.getByText("已归档")).toBeVisible();
  await expect(page.getByText("NJ-AGG-001").first()).toBeVisible();
  await expect(page.getByText("1 匹配 / 1 不匹配")).toBeVisible();
  await expect(page.getByText("V900R016C10SPC200").first()).toBeVisible();
  await page.getByRole("link", { name: /查看设备台账：NJ-AGG-001/ }).first().click();
  await expect(page).toHaveURL(/\/inventory\/devices\//);
  await expect(page.getByRole("heading", { name: "NJ-AGG-001" })).toBeVisible();
  await expect(page.getByText("V900R016C10SPC200").first()).toBeVisible();
  await expect(page.getByText("版本历史")).toBeVisible();
  await expect(page.getByText("观测历史")).toBeVisible();

  await page.getByRole("button", { name: "返回台账" }).click();
  await expect(page).toHaveURL(/\/inventory$/);
  await expect(page.getByText("NJ-AGG-001").first()).toBeVisible();
});

test("日志补充包显示不涉及设备台账且不进入设备台账", async ({ page }) => {
  await uploadPackage(page, logZip, "log");

  await page.getByRole("tab", { name: "设备台账" }).click();
  await expect(page.getByText("日志补充包不涉及设备台账")).toBeVisible();
  await expect(page.getByText("该类型不解析设备信息，也不产生台账观测或质量问题。")).toBeVisible();
});

test("设备台账支持管理员新增、编辑备注和物理删除", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/inventory");

  await page.getByRole("button", { name: /新增设备/ }).click();
  await page.getByLabel("省份").fill("江苏省");
  await page.getByLabel("运营商").fill("移动");
  await page.getByLabel("设备名称").fill("JS-CRUD-001");
  await page.getByLabel("备注").fill("初始化备注");
  await page.getByRole("button", { name: /^创\s*建$/ }).click();
  await expect(page.getByText("设备已创建")).toBeVisible();
  await page.reload();
  await expect(page.getByText("JS-CRUD-001").first()).toBeVisible();

  await page.getByText("JS-CRUD-001").first().click();
  await expect(page).toHaveURL(/\/inventory\/devices\//);
  await expect(page.getByText("初始化备注")).toBeVisible();

  await page.getByRole("button", { name: "编辑" }).click();
  const editModal = page.getByRole("dialog", { name: "编辑设备备注" });
  await editModal.getByLabel("备注").fill("维护升级中");
  await editModal.getByRole("button", { name: /^保\s*存$/ }).click();
  await expect(page.getByText("备注已更新")).toBeVisible();
  await expect(page.locator(".ant-descriptions-item-content").filter({ hasText: "维护升级中" })).toBeVisible();
  await page.reload();
  await expect(page.locator(".ant-descriptions-item-content").filter({ hasText: "维护升级中" })).toBeVisible();

  await page.getByRole("button", { name: /^删\s*除$/ }).click();
  await expect(page.getByText("将物理删除设备、全部观测记录和版本历史。")).toBeVisible();
  const popover = page.locator(".ant-popover").filter({ hasText: "确认删除该设备台账？" });
  await popover.getByRole("button", { name: /^删\s*除$/ }).click();
  await expect(page.getByText("设备台账已删除")).toBeVisible();
  await expect(page).toHaveURL(/\/inventory$/);
  await expect(page.getByText("JS-CRUD-001")).toHaveCount(0);

  await uploadPackage(page, rerunZip, "inspection");
  await page.getByRole("tab", { name: "设备台账" }).click();
  await expect(page.getByText("NJ-AGG-001").first()).toBeVisible();
});
