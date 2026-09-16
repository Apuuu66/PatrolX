import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const SAMPLE_PATH = path.resolve(process.cwd(), "..", "tests/fixtures/sample/sample.zip");

test("真实富化样例可在页面完成 KPI 查询且无接口或运行时错误", async ({ page, request }) => {
  test.setTimeout(180_000);

  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const apiErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      apiErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  const uploadResponse = await request.post("/api/v2/tasks", {
    multipart: {
      name: "真实样例 KPI E2E",
      package_file: {
        name: "kpi-real-sample.zip",
        mimeType: "application/zip",
        buffer: readFileSync(SAMPLE_PATH),
      },
    },
  });
  expect(uploadResponse.status()).toBe(202);
  const { task_id: taskId } = await uploadResponse.json();

  await expect
    .poll(
      async () => {
        const response = await request.get(`/api/v2/tasks/${taskId}`);
        expect(response.status()).toBe(200);
        return (await response.json()).status;
      },
      { timeout: 120_000, intervals: [1_000] },
    )
    .toBe("completed");

  await page.goto(`/tasks/${taskId}`);
  await expect(page.getByText("呼叫 KPI 巡检")).toBeVisible();
  await page.getByText("呼叫 KPI 巡检").click();
  await expect(page.getByText("呼叫成功率")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("kpi/kpi-call-5.csv").first()).toBeVisible();

  await page.getByText("呼叫成功率").click();
  await expect(page.getByText("原始记录")).toBeVisible({ timeout: 10_000 });

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
});
