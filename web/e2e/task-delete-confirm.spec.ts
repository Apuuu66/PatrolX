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
  const taskCard = page.locator(".ant-card").filter({ hasText: "首页失败任务样例" }).last();
  await taskCard.getByLabel("更多操作").click();
  await page.getByRole("menuitem", { name: "删除" }).click();

  await expect(page.locator(".ant-modal-confirm-title", { hasText: "删除任务（含现场数据）？" })).toBeVisible();
  expect(deleteRequested).toBe(false);
});
