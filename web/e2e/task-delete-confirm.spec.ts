import { expect, test } from "@playwright/test";

import type { Page } from "@playwright/test";

async function showAllTasks(page: Page) {
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

test("任务列表行内删除需要二次确认", async ({ page }) => {
  let deleteRequested = false;
  await page.route("**/api/v2/tasks/task-home-failed", async (route) => {
    if (route.request().method() === "DELETE") {
      deleteRequested = true;
      return route.fulfill({ json: { task_id: "task-home-failed" } });
    }
    return route.continue();
  });

  await page.goto("/");
  await showAllTasks(page);
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();
  // 删除不再收进 ⋯ 菜单，行内平铺的删除按钮直接触发二次确认。
  await taskRow.getByRole("button", { name: "删除" }).click();

  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toBeVisible();
  expect(deleteRequested).toBe(false);
});

test("删除确认弹窗取消后不发起删除且任务仍在列表", async ({ page }) => {
  let deleteRequested = false;
  await page.route("**/api/v2/tasks/task-home-failed", async (route) => {
    if (route.request().method() === "DELETE") {
      deleteRequested = true;
      return route.fulfill({ json: { task_id: "task-home-failed" } });
    }
    return route.continue();
  });

  await page.goto("/");
  await showAllTasks(page);
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();
  // 删除不再收进 ⋯ 菜单，行内平铺的删除按钮直接触发二次确认。
  await taskRow.getByRole("button", { name: "删除" }).click();
  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toBeVisible();

  // AntD 会在两字中文按钮中插入空格，因此用宽松名称匹配取消按钮
  const dialog = page.getByRole("dialog", { name: "删除任务（含现场数据）？" });
  await dialog.getByRole("button", { name: /取\s*消/ }).click();
  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toHaveCount(0);
  expect(deleteRequested).toBe(false);
  await expect(page.locator(".task-table code", { hasText: "task-home-failed" })).toBeVisible();
});
