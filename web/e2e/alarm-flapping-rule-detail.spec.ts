import { expect, test } from "@playwright/test";

const TASK_ID = "task-alarm-flapping-e2e";
const CARD_TITLE = "告警生命周期分组";

test("告警闪断规则详情展示四类生命周期结论与三条 Finding", async ({ page }) => {
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

  await page.goto(`/tasks/${TASK_ID}/rules/alarm.flapping`);

  // 顶部 Finding 列表：CRITICAL / HIGH / MEDIUM 三条证据可见（SC-008）。
  const findingsCard = page.locator(".ant-card").filter({ hasText: "发现（3）" });
  await expect(findingsCard).toBeVisible();
  for (const severity of ["critical", "high", "medium"]) {
    await expect(findingsCard.locator(".ant-tag").filter({ hasText: severity })).toHaveCount(1);
  }
  await expect(findingsCard.getByText("1051 / UMF核心服务").first()).toBeVisible();
  await expect(findingsCard.getByText("1052 / UMF核心服务").first()).toBeVisible();
  // 真实导出的定位信息进入证据文案（应用名称是分组键，实例定位在 定位信息 列）。
  await expect(findingsCard.getByText("定位 pod-umf-9", { exact: false }).first()).toBeVisible();
  await expect(findingsCard.getByText("定位 umf-node-01", { exact: false }).first()).toBeVisible();

  // 生命周期分组卡片：六态分布 + 分组明细（SC-005）。
  const panel = page.locator(".ant-card").filter({ hasText: CARD_TITLE });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("未清除且反复 1")).toBeVisible();
  await expect(panel.getByText("未清除未反复 8")).toBeVisible();
  await expect(panel.getByText("已清除但反复 1")).toBeVisible();
  await expect(panel.getByText("已清除但短告警 1")).toBeVisible();
  await expect(panel.getByText("观察窗不足 1")).toBeVisible();
  await expect(panel.getByText("已清除且稳定 5")).toBeVisible();
  await expect(panel.getByText("告警分组")).toBeVisible();

  const rows = panel.locator(".ant-table-tbody tr:not(.ant-table-measure-row)");
  await expect(rows).toHaveCount(17);

  // 结论分类：未恢复 / 反复闪断 / 单次短告警 / 稳定恢复
  const unclearedRepeated = rows.filter({ hasText: "1051" });
  await expect(unclearedRepeated).toContainText("未清除且反复");
  await expect(unclearedRepeated).toContainText("窗口后仍未恢复");

  const clearedRepeated = rows.filter({ hasText: "1052" });
  await expect(clearedRepeated).toContainText("已清除但反复");
  await expect(clearedRepeated).toContainText("600 秒");

  const shortAlarm = page.locator('tr[data-row-key="1002-UMF核心服务"]');
  await expect(shortAlarm).toContainText("已清除但短告警");
  await expect(shortAlarm).toContainText("短告警");

  const stable = rows.filter({ hasText: "1050" });
  await expect(stable).toContainText("已清除且稳定");
  await expect(stable).toContainText("窗口外再现");

  const insufficient = rows.filter({ hasText: "1053" });
  await expect(insufficient).toContainText("观察窗不足");

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
