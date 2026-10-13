import { expect, test } from "@playwright/test";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

/**
 * 034 磁盘留存治理端到端场景。
 *
 * 由 `playwright.retention.config.ts` 在独立后端（e2e/.tmp-retention、8011/5184）运行，
 * 该后端只播种 51 个留存任务，因此"仅留最近 50 个现场"、清理后仍可查、重传恢复
 * 三类断言可以精确复现，不受默认套件其他用例触发的全局清理影响。
 */

const E2E_DIR = path.join(process.cwd(), "e2e", ".tmp-retention");
const REPORT_PATH = path.join(E2E_DIR, "retention-report.json");
const SOURCE_PACKAGE = path.join(E2E_DIR, "retention-source", "retention-scene-01.zip");
const CLEANED_TASK_ID = "task-retention_scene_01";
const NEWEST_TASK_ID = "task-retention_scene_51";
const NEWEST_PACKAGE = "retention-scene-51.zip";
const KPI_RULE_CODE = "kpi.measurement_units";
const RETENTION_SCENE_PREFIX = "task-retention_scene_";

type RetentionReport = {
  package_file: string;
  package_checksum: string;
  seeded_task_ids: string[];
  cleaned_task_id: string;
  newest_task_id: string;
  retained_task_ids: string[];
  removed_task_ids: string[];
  failed_paths: string[];
};

const report: RetentionReport = JSON.parse(readFileSync(REPORT_PATH, "utf-8"));

function sceneDirs(kind: "output" | "uploads"): string[] {
  return readdirSync(path.join(E2E_DIR, kind), { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith(RETENTION_SCENE_PREFIX))
    .map((entry) => entry.name)
    .sort();
}

function isRequestTo(response: { url: () => string }, pathname: string): boolean {
  return new URL(response.url()).pathname === pathname;
}

async function openUpload(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /上传数据包/ }).first().click();
  await expect(page.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeVisible();
  return page.locator('input[type="file"]');
}

/** 巡检包必须携带省份 / 运营商，否则后端按 400 拒绝；沿用 E2E 字典项。 */
async function fillInspectionMetadata(page: Page) {
  const selectByLabel = (label: string) =>
    page.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select");
  for (const [label, option] of [
    ["省份", "江苏"],
    ["运营商", "移动"],
  ] as const) {
    await selectByLabel(label).click();
    await page
      .locator(
        `.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="${option}"]`,
      )
      .click();
  }
}

test("51 个任务现场只保留最近 50 个，最旧任务的磁盘现场被清理", async () => {
  expect(report.cleaned_task_id).toBe(CLEANED_TASK_ID);
  expect(report.newest_task_id).toBe(NEWEST_TASK_ID);
  expect(report.retained_task_ids).toHaveLength(50);
  expect(report.removed_task_ids).toEqual([CLEANED_TASK_ID]);
  expect(report.failed_paths).toEqual([]);

  // 被清理任务：输出目录与上传包现场都已删除。
  expect(existsSync(path.join(E2E_DIR, "output", CLEANED_TASK_ID))).toBe(false);
  expect(existsSync(path.join(E2E_DIR, "uploads", CLEANED_TASK_ID))).toBe(false);

  // 其余 50 个任务现场完整保留，且与留存集合一一对应（不多留、不误删）。
  expect(sceneDirs("output")).toEqual([...report.retained_task_ids].sort());
  expect(sceneDirs("uploads")).toEqual([...report.retained_task_ids].sort());
  expect(existsSync(path.join(E2E_DIR, "uploads", NEWEST_TASK_ID, NEWEST_PACKAGE))).toBe(true);
});

test("清理后任务详情、规则结果与 KPI 趋势仍可查", async ({ page }) => {
  await page.goto(`/tasks/${CLEANED_TASK_ID}`);
  await expect(page.getByTestId("conclusion-hero").getByRole("heading", { name: "留存场景 01" })).toBeVisible();
  // 规则结果完全来自数据库，现场缺失不影响展示。
  const ruleRow = page
    .getByTestId("rule-browser")
    .getByRole("row", { name: /KPI 测量单元检查/ });
  await expect(ruleRow).toBeVisible();
  await expect(ruleRow).toContainText(KPI_RULE_CODE);

  await page.goto(`/tasks/${CLEANED_TASK_ID}/rules/${KPI_RULE_CODE}`);
  await expect(page.getByText("呼叫统计")).toBeVisible();

  const detailResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      isRequestTo(response, `/api/v2/tasks/${CLEANED_TASK_ID}/rules/${KPI_RULE_CODE}/measurement-units/MU_CALL/metrics/ME_CALL`),
  );
  await page.getByRole("button", { name: "查看呼叫请求次数完整趋势" }).click();
  const detailResponse = await detailResponsePromise;
  expect(detailResponse.status()).toBe(200);
  // 完整趋势的时间点明细来自数据库中的 KPI 明细，两条窗口仍可核对。
  await expect(page.getByRole("cell", { name: "101 次", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "105 次", exact: true })).toBeVisible();

  const historyResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      isRequestTo(
        response,
        `/api/v2/tasks/${CLEANED_TASK_ID}/rules/${KPI_RULE_CODE}/measurement-units/MU_CALL/metrics/ME_CALL/history-trend`,
      ),
  );
  await page.getByRole("tab", { name: "历史对比" }).click();
  const historyResponse = await historyResponsePromise;
  expect(historyResponse.status()).toBe(200);
  // 设备身份与窗口来自数据库中的任务记录（现场已删除）。
  await expect(page.getByText("设备 retention-device-001")).toBeVisible();
  await expect(page.getByText("暂无历史")).toBeVisible();
});

test("报告与执行日志在磁盘现场缺失时给出明确提示，不静默空白", async ({ page }) => {
  await page.goto(`/tasks/${CLEANED_TASK_ID}`);

  await page.getByRole("tab", { name: "执行日志" }).click();
  const logsAlert = page.getByTestId("logs-scene-cleaned");
  await expect(logsAlert).toBeVisible();
  await expect(logsAlert).toContainText("执行日志不入库，已随磁盘现场清理，不可查看");
  await expect(logsAlert).toContainText("任务详情、规则结果与 KPI 等核心数据仍可在界面查询");

  await page.getByRole("tab", { name: "报告预览" }).click();
  const reportAlert = page.getByTestId("report-scene-cleaned");
  await expect(reportAlert).toBeVisible();
  await expect(reportAlert).toContainText("报告已随磁盘现场清理，不可查看");
  await expect(reportAlert).toContainText("重新上传同名且校验和一致的原始包可恢复磁盘现场");

  // 独立报告页同样不展示空白报告。
  await page.goto(`/tasks/${CLEANED_TASK_ID}/report`);
  await expect(page.getByTestId("report-scene-cleaned")).toBeVisible();
});

test("重跑与重建在磁盘现场缺失时拒绝执行并给出恢复指引", async ({ page }) => {
  await page.goto(`/tasks/${CLEANED_TASK_ID}`);
  await expect(page.getByTestId("conclusion-hero").getByRole("heading", { name: "留存场景 01" })).toBeVisible();

  const rerunResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      isRequestTo(response, `/api/v2/tasks/${CLEANED_TASK_ID}/rerun`),
  );
  await page.getByLabel("更多操作").click();
  await page.getByRole("menuitem", { name: "重跑全部" }).click();
  const rerunResponse = await rerunResponsePromise;
  expect(rerunResponse.status()).toBe(410);
  expect((await rerunResponse.json()).code).toBe("scene_cleaned");

  await expect(
    page.locator(".ant-modal-confirm-title", { hasText: "磁盘现场已清理" }),
  ).toBeVisible();
  await expect(page.locator(".ant-modal-confirm-content")).toContainText(
    "重新上传同名且校验和一致的原始包",
  );

  // 拒绝后不进入队列：任务状态仍是已完成。
  const statusResponse = await page.request.get(`/api/v2/tasks/${CLEANED_TASK_ID}`);
  expect(statusResponse.status()).toBe(200);
  expect((await statusResponse.json()).status).toBe("completed");
});

test("重传同名且校验和一致的原始包可恢复现场，内容不一致仍被拒绝", async ({ page }) => {
  const buffer = readFileSync(SOURCE_PACKAGE);
  const restoredPackage = path.join(E2E_DIR, "uploads", CLEANED_TASK_ID, report.package_file);

  // 同名同 checksum：写回原始包恢复现场，返回 202 并打开已有任务（不自动重跑）。
  const input = await openUpload(page);
  await input.setInputFiles({ name: report.package_file, mimeType: "application/zip", buffer });
  await fillInspectionMetadata(page);
  const restoreResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && isRequestTo(response, "/api/v3/tasks"),
  );
  await page.getByRole("button", { name: "提交巡检" }).click();
  const restoreResponse = await restoreResponsePromise;
  expect(restoreResponse.status()).toBe(202);
  await page.waitForURL(new RegExp(`/tasks/${CLEANED_TASK_ID}$`));

  await expect.poll(() => existsSync(restoredPackage)).toBe(true);
  // 恢复只写回原始包：输出目录仍需显式重跑/重建。
  expect(existsSync(path.join(E2E_DIR, "output", CLEANED_TASK_ID))).toBe(false);

  // 同名但 checksum 不同：409 冲突，且不覆盖已恢复的现场。
  const conflictInput = await openUpload(page);
  await conflictInput.setInputFiles({
    name: report.package_file,
    mimeType: "application/zip",
    buffer: Buffer.concat([buffer, Buffer.from("x")]),
  });
  await fillInspectionMetadata(page);
  const conflictResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && isRequestTo(response, "/api/v3/tasks"),
  );
  await page.getByRole("button", { name: "提交巡检" }).click();
  const conflictResponse = await conflictResponsePromise;
  expect(conflictResponse.status()).toBe(409);
  expect((await conflictResponse.json()).code).toBe("package_checksum_conflict");

  const conflict = page.locator('[data-testid="upload-conflict"]');
  await expect(conflict).toBeVisible();
  await expect(conflict).toContainText("checksum");
  expect(readFileSync(restoredPackage)).toEqual(buffer);
});
