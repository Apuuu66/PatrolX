import { expect, test } from "@playwright/test";

test("任务列表删除菜单需要二次确认", async ({ page }) => {
  let deleteRequested = false;
  await page.route("**/api/v2/tasks/task-home-failed", async (route) => {
    if (route.request().method() === "DELETE") {
      deleteRequested = true;
      return route.fulfill({ json: { task_id: "task-home-failed" } });
    }
    return route.continue();
  });

  await page.goto("/");
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();
  await taskRow.getByLabel("更多操作").click();
  await page.getByRole("menuitem", { name: "删除" }).click();

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
  const taskRow = page
    .locator(".task-table .ant-table-tbody > tr.ant-table-row")
    .filter({ hasText: "首页失败任务样例" })
    .first();
  await taskRow.getByLabel("更多操作").click();
  await page.getByRole("menuitem", { name: "删除" }).click();
  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toBeVisible();

  // AntD 会在两字中文按钮中插入空格，因此用宽松名称匹配取消按钮
  const dialog = page.getByRole("dialog", { name: "删除任务（含现场数据）？" });
  await dialog.getByRole("button", { name: /取\s*消/ }).click();
  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toHaveCount(0);
  expect(deleteRequested).toBe(false);
  await expect(page.locator(".task-table code", { hasText: "task-home-failed" })).toBeVisible();
});
