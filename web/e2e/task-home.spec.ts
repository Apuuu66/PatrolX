import { expect, test } from "@playwright/test";

import type { Locator, Page } from "@playwright/test";

const FAILED_TASK_ID = "task-home-failed";
const COMPLETED_TASK_ID = "task-kpi-history-current";

function taskRows(page: Page): Locator {
  return page.locator(".task-table .ant-table-tbody > tr.ant-table-row");
}

function rowOf(page: Page, taskId: string): Locator {
  return taskRows(page).filter({ has: page.locator(`code:text-is("${taskId}")`) }).first();
}

test("任务首页以行式列表呈现并让失败任务置顶", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 首屏可见概览条与种子任务（SC-001）
  await expect(page.locator('[data-testid="task-overview"]')).toBeVisible();
  const rows = taskRows(page);
  // 全量套件并行运行时会创建额外任务，这里只要求 5 条种子任务都在首屏（SC-001）。
  await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(5);
  for (const taskId of [
    "task-home-failed",
    "task-alarm-flapping-e2e",
    "task-kpi-history-current",
    "task-kpi-history-past",
  ]) {
    await expect(page.locator(".task-table code", { hasText: taskId })).toBeVisible();
  }

  // 单一表行式列表，不再是卡片网格（FR-006）
  await expect(page.locator(".task-table")).toHaveCount(1);

  // 失败任务必须位于第一行（SC-001、FR-001）
  const firstRow = rows.first();
  await expect(firstRow.locator("code", { hasText: FAILED_TASK_ID })).toBeVisible();

  // 失败原因摘要在行内直接可见，无需展开（SC-003、FR-008）
  await expect(firstRow.locator('[data-testid="task-failure-reason"]')).toBeVisible();
  await expect(firstRow.locator('[data-testid="task-failure-reason"]')).toContainText("失败原因：");

  // 状态摘要只保留非零状态，不出现彩色 0 值（FR-003）
  await expect(firstRow.locator('[data-status-count="error"]')).toHaveText(/异常 1/);
  for (const status of ["pass", "warn", "fail", "skip"]) {
    await expect(firstRow.locator(`[data-status-count="${status}"]`)).toHaveCount(0);
    await expect(firstRow.locator(`[data-status-segment="${status}"]`)).toHaveCount(0);
  }

  // 失败原因本身即唯一行内日志入口，一次点击进入失败日志（SC-003、FR-008）
  await firstRow.locator('[data-testid="task-failure-reason"]').click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${FAILED_TASK_ID}/logs$`));
  await expect(page.getByText("任务执行失败：解析主清单失败")).toBeVisible();
});

test("任务首页行内元数据与操作分层保持可读", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  await expect(failedRow.locator('[data-metadata-key="device_id"]')).toContainText("home-device-001");
  await expect(failedRow.locator('[data-metadata-key="province"]')).toContainText("江苏");

  // 常驻行内操作只有详情（FR-008、R5）
  await expect(failedRow.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "失败日志" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: "报告" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: /重跑|全量重建|删除/ })).toHaveCount(0);

  // 低频与危险操作收进 ⋯ 菜单，失败日志也在菜单内仍可及（FR-008）
  await failedRow.getByRole("button", { name: "更多操作" }).click();
  await expect(page.getByRole("menuitem", { name: "失败日志" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "全量重建" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();
  await page.keyboard.press("Escape");

  // 已完成任务：报告按钮默认不抢注意力，行 hover 后显示且在菜单内同样可达（FR-008）
  const completedRow = rowOf(page, COMPLETED_TASK_ID);
  const revealButton = completedRow.locator(".task-table-action-reveal");
  await expect(revealButton).toHaveText("报告");
  await expect(revealButton).toHaveCSS("opacity", "0");
  await completedRow.hover();
  await expect(revealButton).toHaveCSS("opacity", "1");
  await completedRow.getByRole("button", { name: "更多操作" }).click();
  await expect(page.getByRole("menuitem", { name: "报告" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "重跑" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();
  await page.keyboard.press("Escape");

  // 详情仍然一次点击可达（FR-008）
  await completedRow.getByRole("button", { name: "详情" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${COMPLETED_TASK_ID}$`));
});

test("概览条弱化通过状态并给出计数与占比 Tooltip", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const overview = page.locator('[data-testid="task-overview"]');
  await expect(overview).toBeVisible();

  // 通过 / 跳过使用弱化色，其它状态保留标准关注色（FR-002、R1）
  await expect(overview.locator('[data-status-segment="pass"]')).toHaveClass(
    /status-distribution-segment-quiet/,
  );
  await expect(overview.locator('[data-status-segment="pass"]')).toHaveCSS(
    "background-color",
    "rgb(183, 235, 143)",
  );
  await expect(overview.locator('[data-status-segment="error"]')).toHaveClass(
    /status-distribution-segment-attention/,
  );

  // 计数与分段顺序一致：异常优先、通过最后（FR-001）
  const renderedOrder = await overview
    .locator("[data-status-segment]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-status-segment")));
  const expectedOrder = ["fail", "warn", "error", "skip", "pass"].filter((status) =>
    renderedOrder.includes(status),
  );
  expect(renderedOrder).toEqual(expectedOrder);

  const renderedCounts = await overview
    .locator("[data-status-count]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-status-count")));
  expect(renderedCounts).toEqual(expectedOrder);

  // 0 值状态不渲染（FR-003）：所有可见计数都大于 0
  await expect
    .poll(async () =>
      overview.locator("[data-status-count]").evaluateAll((nodes) =>
        nodes.every((node) => !/\s0$/.test((node.textContent ?? "").trim())),
      ),
    )
    .toBe(true);

  // 每段 Tooltip 文案为"状态 计数（整数百分比）"（FR-002、SC-002）
  const errorSegment = overview.locator('[data-status-segment="error"]');
  await expect(errorSegment).toHaveAttribute("aria-label", /^异常 \d+（\d+%）$/);
  await errorSegment.hover();
  await expect(
    page.locator(".ant-tooltip-inner").filter({ hasText: /^异常 \d+（\d+%）$/ }).first(),
  ).toBeVisible();

  // 指标口径可查：发现问题数说明包含"一条规则可产生多条发现"（FR-004）
  await overview.locator('[aria-label="发现问题数口径说明"]').hover();
  await expect(
    page.locator(".ant-tooltip-inner").filter({ hasText: "一条规则可产生多条发现" }).first(),
  ).toBeVisible();
  await expect(
    page.locator(".ant-tooltip-inner").filter({ hasText: "统计范围：全部任务" }).first(),
  ).toBeVisible();
});

test("时间与耗时列以耗时为主并给出完整时间 Tooltip", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  const timeCell = failedRow.locator(".task-table-time");
  await expect(timeCell).toHaveClass(/tabular-nums/);
  await expect(failedRow.locator('[data-testid="task-duration"]')).toHaveText(/^耗时 /);

  // 创建 / 完成为相对时间次要信息，不在列内直接堆叠完整时间戳（FR-006）
  await expect(timeCell.getByText(/^创建 /)).toBeVisible();
  await expect(timeCell.getByText(/^完成 /)).toBeVisible();
  await expect(timeCell).not.toContainText(/\d{4}-\d{2}-\d{2}/);

  // 完整时间通过 Tooltip 提供（FR-007）
  await timeCell.getByText(/^创建 /).hover();
  await expect(
    page.locator(".ant-tooltip-inner").filter({ hasText: /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/ }).first(),
  ).toBeVisible();
});

test("概览统计加载中不渲染 0 值假分布", async ({ page }) => {
  let releaseOverview: () => void = () => {};
  const overviewGate = new Promise<void>((resolve) => {
    releaseOverview = resolve;
  });

  await page.route("**/api/v2/overview", async (route) => {
    await overviewGate;
    return route.continue();
  });

  await page.goto("/");
  const overview = page.locator('[data-testid="task-overview"]');
  await expect(overview.getByText("统计数据加载中")).toBeVisible();
  await expect(overview.locator("[data-status-count]")).toHaveCount(0);
  await expect(overview.locator("[data-status-segment]")).toHaveCount(0);
  await expect(overview.locator(".status-distribution-bar")).toHaveCount(0);
  await expect(overview.locator('[data-overview-metric="task_count"] .task-overview-value')).toHaveText("—");

  releaseOverview();
  await expect(overview.locator(".status-distribution-bar")).toBeVisible();
  await expect(overview.getByText("统计数据加载中")).toHaveCount(0);
});

test("任务首页从失败任务行一次点击进入任务详情", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  await failedRow.getByRole("button", { name: "详情" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${FAILED_TASK_ID}$`));
});
