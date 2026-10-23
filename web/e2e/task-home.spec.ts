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
  // 元数据列平铺 3 项，其余收进"更多元数据"，行内不再堆叠全部字段（FR-011、契约 §3）
  await expect(failedRow.locator("[data-metadata-key]")).toHaveCount(3);
  await expect(failedRow.locator('[data-metadata-key="province"]')).toContainText("江苏");
  await expect(failedRow.getByTestId("metadata-more")).toContainText("2");

  // 操作列不再收缩：失败任务的详情、失败日志、重建、删除全部平铺常驻（2026-10-13 修订）
  await expect(failedRow.getByRole("button", { name: "详情" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "失败日志" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "重建" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "删除" })).toBeVisible();
  await expect(failedRow.getByRole("button", { name: "报告" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: "更多操作" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: "重跑" })).toHaveCount(0);
  // 去掉收缩：行首不再有展开 / 收起箭头（FR-011 改由数据准备列承载）
  await expect(page.locator(".ant-table-row-expand-icon")).toHaveCount(0);

  // 已完成任务：报告按钮常驻可见，不再 hover 才显现（2026-10-13 修订）
  const completedRow = rowOf(page, COMPLETED_TASK_ID);
  await expect(completedRow.getByRole("button", { name: "报告" })).toBeVisible();
  await expect(completedRow.getByRole("button", { name: "重建" })).toBeVisible();
  await expect(completedRow.getByRole("button", { name: "删除" })).toBeVisible();

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

test("列表展示最后运行时间与任务时长，未运行任务显示占位", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  // 已运行任务：最后运行时间为相对时间，任务时长取最近一次运行耗时（FR-008、FR-009、SC-004）
  const failedRow = rowOf(page, FAILED_TASK_ID);
  const lastRunCell = failedRow.locator('[data-testid="task-last-run"]');
  await expect(lastRunCell).toHaveClass(/tabular-nums/);
  await expect(lastRunCell).not.toHaveText("-");
  await expect(failedRow.locator('[data-testid="task-duration"]')).toHaveText("10 秒");

  // 列内不堆叠完整时间戳，完整时间通过 Tooltip 提供（FR-007）
  await expect(failedRow.locator('[data-testid="task-created-at"]')).not.toHaveText("-");
  await expect(failedRow).not.toContainText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
  await lastRunCell.hover();
  await expect(
    page.locator(".ant-tooltip-inner").filter({ hasText: /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/ }).first(),
  ).toBeVisible();

  // 详情页同步展示两字段（FR-009）
  await page.goto(`/tasks/${FAILED_TASK_ID}`);
  await page.getByTestId("technical-collapse").getByText("执行与技术信息").click();
  const metaPanel = page.getByTestId("task-meta-panel");
  await expect(metaPanel.getByText("最后运行时间")).toBeVisible();
  await expect(metaPanel.getByText("任务时长")).toBeVisible();
  await expect(metaPanel.getByText("10 秒")).toBeVisible();

  // 从未运行/现场无运行字段的历史任务显示占位，不编造 0 秒耗时（SC-004）
  await page.goto("/tasks/task-legacy-e2e");
  await page.getByTestId("technical-collapse").getByText("执行与技术信息").click();
  const legacyPanel = page.getByTestId("task-meta-panel");
  const legacyValues = await legacyPanel
    .locator(".ant-descriptions-item")
    .filter({ hasText: /最后运行时间|任务时长/ })
    .locator(".ant-descriptions-item-content")
    .allTextContents();
  expect(legacyValues).toEqual(["-", "-"]);
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

test("1440 视口一屏看全 6 列且表格内部无横向滚动", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const table = page.locator(".task-table");
  await expect(table).toBeVisible();

  // 物理列固定为 6 个且顺序固定（FR-001、契约 §1）
  const headers = table.locator(".ant-table-thead > tr > th");
  await expect(headers).toHaveCount(6);
  expect((await headers.allInnerTexts()).map((text) => text.trim())).toEqual([
    "任务",
    "状态摘要",
    "数据准备",
    "元数据",
    "时间",
    "操作",
  ]);

  // 时间三段（耗时 → 最后运行 → 创建）同处一个单元格（FR-006~FR-010、SC-003）
  const timeCell = rowOf(page, FAILED_TASK_ID).locator('[data-testid="task-time"]');
  await expect(timeCell.locator('[data-testid="task-duration"]')).toHaveText("10 秒");
  await expect(timeCell.locator('[data-testid="task-last-run"]')).not.toHaveText("-");
  await expect(timeCell.locator('[data-testid="task-created-at"]')).not.toHaveText("-");
  // 单元格内只留相对时间，完整时间走 Tooltip（FR-010、契约 §2）
  await expect(table).not.toContainText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);

  await page.screenshot({ path: "e2e/.tmp/036-task-list-1440.png", fullPage: true });
  // 1440×900：表格内部与页面级都不出现横向滚动（FR-002、FR-004、SC-001、SC-002）
  const metrics = await page.evaluate(() => {
    const scroller = document.querySelector<HTMLElement>(".task-table .ant-table-content");
    return {
      innerScrollWidth: scroller?.scrollWidth ?? 0,
      innerClientWidth: scroller?.clientWidth ?? 0,
      pageScrollWidth: document.documentElement.scrollWidth,
      pageClientWidth: document.documentElement.clientWidth,
    };
  });
  expect(metrics.innerScrollWidth).toBeLessThanOrEqual(metrics.innerClientWidth);
  expect(metrics.pageScrollWidth).toBeLessThanOrEqual(metrics.pageClientWidth);
});

test("1280 视口下操作列贴右固定且入口不换行", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  const actionsCell = failedRow.locator("td.ant-table-cell-fix-right").first();
  await expect(actionsCell).toBeVisible();

  // 1280 允许表格内部横向滚动，但页面级横向滚动必须为 0（FR-004、SC-002）
  const pageMetrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(pageMetrics.scrollWidth).toBeLessThanOrEqual(pageMetrics.clientWidth);

  const scroller = page.locator(".task-table .ant-table-content");
  await scroller.evaluate((node) => {
    node.scrollLeft = node.scrollWidth;
  });

  // 横向滚到底后操作列仍贴在表格右缘可见（FR-015、SC-004）
  const tableBox = await page.locator(".task-table .ant-table-container").boundingBox();
  const cellBox = await actionsCell.boundingBox();
  expect(tableBox).not.toBeNull();
  expect(cellBox).not.toBeNull();
  const tableRight = (tableBox?.x ?? 0) + (tableBox?.width ?? 0);
  const cellRight = (cellBox?.x ?? 0) + (cellBox?.width ?? 0);
  expect(Math.abs(cellRight - tableRight)).toBeLessThanOrEqual(2);

  await page.screenshot({ path: "e2e/.tmp/036-task-list-1280.png", fullPage: true });
  // 平铺常驻、单行不换行：四个入口顶端一致（FR-016、契约 §4）
  const tops: number[] = [];
  for (const name of ["详情", "失败日志", "重建", "删除"]) {
    const button = failedRow.getByRole("button", { name });
    await expect(button).toBeVisible();
    const box = await button.boundingBox();
    tops.push(Math.round(box?.y ?? 0));
  }
  expect(new Set(tops).size).toBe(1);
  await expect(failedRow.getByRole("button", { name: "重跑" })).toHaveCount(0);
  await expect(failedRow.getByRole("button", { name: "更多操作" })).toHaveCount(0);
});

test("任务列表元数据平铺 3 项，其余收进更多元数据", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  // 5 项有值元数据：平铺前 3 项，剩余 2 项进"更多元数据（2）"（FR-011、SC-006）
  await expect(failedRow.locator("[data-metadata-key]")).toHaveCount(3);
  const moreTrigger = failedRow.getByTestId("metadata-more");
  await expect(moreTrigger).toContainText("2");

  // 收纳不改变行高：展开前后整行高度一致（FR-013、契约 §3）
  const rowHeightBefore = (await failedRow.boundingBox())?.height ?? 0;
  await moreTrigger.click();
  const panel = page.getByTestId("metadata-more-panel");
  await expect(panel.locator('[data-metadata-key="device_id"]')).toContainText("home-device-001");
  await expect(panel.getByRole("button", { name: "复制设备 ID值" })).toBeVisible();
  expect((await failedRow.boundingBox())?.height ?? 0).toBe(rowHeightBefore);

  // 键盘可关闭、可再次开启（FR-012、契约 §6）
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await moreTrigger.press("Enter");
  await expect(panel).toBeVisible();
});

test("任务首页从失败任务行一次点击进入任务详情", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const failedRow = rowOf(page, FAILED_TASK_ID);
  await failedRow.getByRole("button", { name: "详情" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${FAILED_TASK_ID}$`));
});
