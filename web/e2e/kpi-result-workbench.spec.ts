import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

const UMF_TASK_ID = "KPI-V6-UMF-TASK";
const UMF_EVIDENCE_FAILURE_METRIC = "ME_MEDIA_CREATION_FAILURE_RESPONSES";
const LOG_SUPPLEMENT = path.join(process.cwd(), "e2e", ".tmp", "KPI_V6_Log_Supplement_20261105.zip");
const TEAM_FOCUS_PATH = "/api/v6/kpi/team-focus/UMF";
const DUAL_SESSION_ADDED_METRICS = [
  "ME_AV_TERMINATION_UPDATE_SUCCESS_RESPONSES",
  "ME_AV_STREAM_ASSOCIATION_REQUESTS",
] as const;

async function loginAdmin(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /^登\s*录$/ }).first().click();
  await page.getByLabel("用户名").fill("e2e-admin");
  await page.getByLabel("密码").fill("e2e-admin-123");
  await page.locator(".ant-modal").getByRole("button", { name: /^登\s*录$/ }).click();
  await expect(page.getByText("e2e-admin")).toBeVisible();
}

async function authorizationHeaders(page: Page): Promise<{ Authorization: string }> {
  const token = await page.evaluate(() => localStorage.getItem("patrolx_token"));
  expect(token).toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function removeTeamFocusMetrics(
  page: Page,
  headers: { Authorization: string },
  metricResourceIds: ReadonlySet<string>,
) {
  const params = new URLSearchParams({ task_id: UMF_TASK_ID, page_size: "200" });
  const response = await page.request.get(`${TEAM_FOCUS_PATH}?${params}`, { headers });
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    revision: number;
    items: Array<{ measurement_unit_id: string; metric_resource_id: string }>;
  };
  const remove = body.items
    .filter((item) => metricResourceIds.has(item.metric_resource_id))
    .map((item) => ({
      measurement_unit_id: item.measurement_unit_id,
      metric_resource_id: item.metric_resource_id,
    }));
  if (remove.length === 0) return;

  const patchResponse = await page.request.patch(TEAM_FOCUS_PATH, {
    headers,
    data: {
      task_id: UMF_TASK_ID,
      expected_revision: body.revision,
      add: [],
      remove,
    },
  });
  expect(patchResponse.status()).toBe(200);
}

async function openTeamFocus(page: Page): Promise<{ drawer: Locator; revision: number }> {
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === TEAM_FOCUS_PATH &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: "管理团队关注" }).click();
  const drawer = page.getByRole("dialog", { name: "管理团队关注" });
  await expect(drawer).toBeVisible();
  const response = await responsePromise;
  const body = (await response.json()) as { revision: number };
  return { drawer, revision: body.revision };
}

test("从任务进入 KPI 工作台，核验需处理证据并维护团队关注", async ({ page }) => {
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

  await loginAdmin(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/tasks/${UMF_TASK_ID}`);

  const entry = page.getByTestId("task-kpi-entry");
  await expect(entry).toContainText("UMF");
  await expect(entry).toContainText("全部指标 20");
  await expect(entry).toContainText("团队关注 10");
  await entry.getByRole("button", { name: "查看 KPI 巡检结果" }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${UMF_TASK_ID}/kpi$`));

  const viewTabs = page.getByRole("tablist", { name: "KPI 结果视图" });
  await expect(viewTabs.getByRole("tab", { name: /需处理/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("kpi-result-visible-total")).toContainText("当前可见 10 / 视图总计 10 项");
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(10);
  await expect(page.getByTestId("kpi-metric-row").filter({ hasText: "媒体资源创建失败响应次数" })).toBeVisible();

  await page.getByRole("button", { name: "查看媒体资源创建失败响应次数证据" }).click();
  const evidence = page.getByRole("region", { name: "媒体资源创建失败响应次数证据" });
  await expect(page.getByTestId("kpi-evidence-overlay")).toHaveAttribute("data-layout", "inline");
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText("当前结论与证据");
  await expect(evidence).toContainText("7 日趋势");
  await expect(evidence).toContainText("超过严重阈值");
  const technicalResponse = page.waitForResponse(
    (response) => response.url().includes(
      `/api/v6/kpi/tasks/${UMF_TASK_ID}/metrics/MU_MEDIA_DATA_CHANNEL_CALL/ME_MEDIA_CREATION_FAILURE_RESPONSES`,
    ) && response.url().includes("technical-analysis") && response.status() === 200,
  );
  await evidence.getByRole("button", { name: "展开技术分析" }).click();
  expect((await technicalResponse).status()).toBe(200);
  await expect(evidence.getByTestId("kpi-technical-analysis")).toContainText("跨任务历史");
  await expect(evidence.getByTestId("kpi-technical-analysis")).toContainText("同设备版本对比");
  await evidence.getByRole("button", { name: "关闭指标证据" }).click();
  await expect(evidence).toBeHidden();

  await page.getByRole("button", { name: "管理团队关注" }).click();
  const focusDrawer = page.getByRole("dialog", { name: "管理团队关注" });
  await expect(focusDrawer).toContainText("UMF 内共享");
  const remove = focusDrawer.getByRole("checkbox", { name: "关注媒体资源创建请求次数" });
  const add = focusDrawer.getByRole("checkbox", { name: "关注音视频终止资源更新请求次数" });
  await expect(remove).toBeChecked();
  await expect(add).not.toBeChecked();
  await remove.uncheck();
  await add.check();
  await expect(focusDrawer).toContainText("1 项待加入 · 1 项待移出");
  await focusDrawer.getByRole("button", { name: "保存团队关注" }).click();
  await expect(focusDrawer).toBeHidden();

  await viewTabs.getByRole("tab", { name: /团队关注/ }).click();
  await expect(page.getByTestId("kpi-result-visible-total")).toContainText("当前可见 10 / 视图总计 10 项");
  await expect(page.getByTestId("kpi-metric-row").filter({ hasText: "音视频终止资源更新请求次数" })).toBeVisible();
  await expect(page.getByTestId("kpi-metric-row").filter({ hasText: "媒体资源创建请求次数" })).toHaveCount(0);

  await viewTabs.getByRole("tab", { name: /全部指标/ }).click();
  await expect(page.getByTestId("kpi-result-visible-total")).toContainText("当前可见 20 / 视图总计 20 项");
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(20);

  const restoreFocus = await openTeamFocus(page);
  const restoredRemove = restoreFocus.drawer.getByRole("checkbox", {
    name: "关注音视频终止资源更新请求次数",
  });
  const restoredAdd = restoreFocus.drawer.getByRole("checkbox", {
    name: "关注媒体资源创建请求次数",
  });
  await expect(restoredRemove).toBeChecked();
  await expect(restoredAdd).not.toBeChecked();
  await restoredRemove.uncheck();
  await restoredAdd.check();
  await expect(restoreFocus.drawer).toContainText("1 项待加入 · 1 项待移出");
  await restoreFocus.drawer.getByRole("button", { name: "保存团队关注" }).click();
  await expect(restoreFocus.drawer).toBeHidden();

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("证据失败只影响当前抽屉并在原地重试", async ({ page }) => {
  await loginAdmin(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/tasks/${UMF_TASK_ID}/kpi`);

  const needsAttentionSummary = page.getByTestId("kpi-summary-needs-attention-count");
  const summaryBefore = await needsAttentionSummary.textContent();
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(10);

  let summaryRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      new URL(request.url()).pathname === `/api/v6/kpi/tasks/${UMF_TASK_ID}/summary`
    ) {
      summaryRequests += 1;
    }
  });

  const evidencePath = `/api/v6/kpi/tasks/${UMF_TASK_ID}/metrics/MU_MEDIA_DATA_CHANNEL_CALL/${UMF_EVIDENCE_FAILURE_METRIC}/evidence`;
  const evidenceRoute = (url: URL) => url.pathname === evidencePath;
  await page.route(evidenceRoute, async (route) => {
    await route.fulfill({
      status: 424,
      contentType: "application/json",
      body: JSON.stringify({
        code: "kpi_evidence_unavailable",
        message: "证据文件暂时不可读",
        detail: { retryable: true, reason: "source_unreadable" },
      }),
    });
  });

  await page.getByRole("button", { name: "查看媒体资源创建失败响应次数证据" }).click();
  const evidence = page.getByRole("region", { name: "媒体资源创建失败响应次数证据" });
  await expect(evidence).toBeVisible();
  await expect(evidence).toContainText("指标证据加载失败");
  await expect(evidence).toContainText("证据文件暂时不可读");
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(10);
  await expect(needsAttentionSummary).toHaveText(summaryBefore ?? "");

  await page.unroute(evidenceRoute);
  const retryResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === evidencePath &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await evidence.getByRole("button", { name: "重试加载证据" }).click();
  await retryResponse;
  await expect(evidence).toContainText("当前结论与证据");
  await expect(evidence).toContainText("超过严重阈值");
  await expect(page.getByTestId("kpi-metric-row")).toHaveCount(10);
  await expect(needsAttentionSummary).toHaveText(summaryBefore ?? "");
  expect(summaryRequests).toBe(0);
});

test("双会话 revision 冲突保留双方关注且不部分写入", async ({ browser, page }) => {
  await loginAdmin(page);
  const headers = await authorizationHeaders(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/tasks/${UMF_TASK_ID}/kpi`);

  const contextB = await browser.newContext({
    baseURL: new URL(page.url()).origin,
    viewport: { width: 1440, height: 900 },
  });
  const pageB = await contextB.newPage();
  try {
    await loginAdmin(pageB);
    await pageB.goto(`/tasks/${UMF_TASK_ID}/kpi`);

    const sessionA = await openTeamFocus(page);
    const sessionB = await openTeamFocus(pageB);
    expect(sessionB.revision).toBe(sessionA.revision);
    const initialRevision = sessionA.revision;

    const metricA = sessionA.drawer.getByRole("checkbox", {
      name: "关注音视频终止资源更新成功响应次数",
    });
    const metricB = sessionB.drawer.getByRole("checkbox", {
      name: "关注音视频流关联设置请求次数",
    });
    await expect(metricA).not.toBeChecked();
    await expect(metricB).not.toBeChecked();

    await metricA.check();
    const saveAResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === TEAM_FOCUS_PATH &&
        response.request().method() === "PATCH" &&
        response.status() === 200,
    );
    await sessionA.drawer.getByRole("button", { name: "保存团队关注" }).click();
    await saveAResponse;
    await expect(sessionA.drawer).toBeHidden();

    await metricB.check();
    const conflictResponsePromise = pageB.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === TEAM_FOCUS_PATH &&
        response.request().method() === "PATCH" &&
        response.status() === 409,
    );
    await sessionB.drawer.getByRole("button", { name: "保存团队关注" }).click();
    const conflictResponse = await conflictResponsePromise;
    const conflictBody = (await conflictResponse.json()) as {
      code: string;
      detail: {
        expected_revision: number;
        current_revision: number;
        network_element_type: string;
      };
    };
    expect(conflictBody.code).toBe("team_focus_revision_conflict");
    expect(conflictBody.detail).toEqual({
      expected_revision: initialRevision,
      current_revision: initialRevision + 1,
      network_element_type: "UMF",
    });
    await expect(sessionB.drawer.getByRole("alert")).toContainText("你的暂存选择已保留");
    await expect(metricB).toBeChecked();

    const afterConflictA = await openTeamFocus(page);
    expect(afterConflictA.revision).toBe(initialRevision + 1);
    await expect(
      afterConflictA.drawer.getByRole("checkbox", {
        name: "关注音视频终止资源更新成功响应次数",
      }),
    ).toBeChecked();
    await expect(
      afterConflictA.drawer.getByRole("checkbox", {
        name: "关注音视频流关联设置请求次数",
      }),
    ).not.toBeChecked();
    await afterConflictA.drawer.getByRole("button", { name: "关闭团队关注" }).click();
    await expect(afterConflictA.drawer).toBeHidden();

    const latestResponse = pageB.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === TEAM_FOCUS_PATH &&
        response.request().method() === "GET" &&
        response.status() === 200,
    );
    await sessionB.drawer.getByRole("button", { name: "载入最新版本并保留修改" }).click();
    const latestBody = (await (await latestResponse).json()) as { revision: number };
    expect(latestBody.revision).toBe(initialRevision + 1);
    await expect(
      sessionB.drawer.getByRole("checkbox", {
        name: "关注音视频终止资源更新成功响应次数",
      }),
    ).toBeChecked();
    await expect(metricB).toBeChecked();

    const saveBResponse = pageB.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === TEAM_FOCUS_PATH &&
        response.request().method() === "PATCH" &&
        response.status() === 200,
    );
    await sessionB.drawer.getByRole("button", { name: "保存团队关注" }).click();
    await saveBResponse;
    await expect(sessionB.drawer).toBeHidden();

    const finalA = await openTeamFocus(page);
    expect(finalA.revision).toBe(initialRevision + 2);
    await expect(
      finalA.drawer.getByRole("checkbox", {
        name: "关注音视频终止资源更新成功响应次数",
      }),
    ).toBeChecked();
    await expect(
      finalA.drawer.getByRole("checkbox", {
        name: "关注音视频流关联设置请求次数",
      }),
    ).toBeChecked();
  } finally {
    try {
      await contextB.close();
    } finally {
      await removeTeamFocusMetrics(page, headers, new Set(DUAL_SESSION_ADDED_METRICS));
    }
  }
});

test("规则归属支持多网元编辑并可恢复原归属", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/inspectors");

  const ruleRow = page.getByRole("row").filter({ hasText: "kpi.measurement_units" });
  await expect(ruleRow).toContainText("UMF");
  await ruleRow.getByRole("button", { name: "编辑归属" }).click();

  const dialog = page.getByRole("dialog", { name: "编辑规则归属" });
  const umf = dialog.getByRole("checkbox", { name: "UMF" });
  const csp = dialog.getByRole("checkbox", { name: "CSP" });
  await expect(umf).toBeChecked();
  await expect(csp).not.toBeChecked();
  await umf.click();
  await expect(umf).not.toBeChecked();
  await csp.click();
  await expect(csp).toBeChecked();
  await dialog.getByRole("button", { name: "保存归属" }).click();
  await expect(page.locator(".ant-message").getByText("规则 kpi.measurement_units 的网元归属已更新")).toBeVisible();
  await expect(ruleRow).toContainText("CSP");

  await ruleRow.getByRole("button", { name: "编辑归属" }).click();
  await expect(dialog.getByRole("checkbox", { name: "CSP" })).toBeChecked();
  await dialog.getByRole("checkbox", { name: "UMF" }).click();
  await dialog.getByRole("checkbox", { name: "CSP" }).click();
  await expect(dialog.getByRole("checkbox", { name: "CSP" })).not.toBeChecked();
  await dialog.getByRole("button", { name: "保存归属" }).click();
  await expect(ruleRow).toContainText("UMF");
  await expect(ruleRow).not.toContainText("CSP");
});

test("日志补充包默认不指定规则适用网元类型，并可选 UMF 或 CSP", async ({ page }) => {
  await loginAdmin(page);
  await page.getByRole("button", { name: /上传数据包/ }).first().click();

  const modal = page.locator(".ant-modal").filter({ hasText: "上传数据包" });
  await expect(modal).toBeVisible();
  await modal.locator('input[type="file"]').setInputFiles(LOG_SUPPLEMENT);

  await modal.locator(".ant-form-item").filter({ hasText: "包类型" }).locator(".ant-select").click();
  await page
    .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option[title="日志补充包"]')
    .click();

  await expect(modal.getByText("日志补充包不采集设备信息")).toBeVisible();
  const networkType = modal.getByRole("combobox", { name: "规则适用网元类型" });
  const networkTypeField = modal.locator(".ant-form-item").filter({ hasText: "规则适用网元类型" });
  await expect(networkType).toHaveValue("");
  await expect(networkTypeField.locator(".ant-select-selection-item")).toHaveText("不指定");
  await networkTypeField.locator(".ant-select-selector").click();
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  await expect(dropdown.locator('.ant-select-item-option[title="不指定"]')).toBeVisible();
  await expect(dropdown.locator('.ant-select-item-option[title="UMF"]')).toBeVisible();
  await expect(dropdown.locator('.ant-select-item-option[title="CSP"]')).toBeVisible();
  await dropdown.locator('.ant-select-item-option[title="UMF"]').click();
  await expect(networkTypeField.locator(".ant-select-selection-item")).toHaveText("UMF");

  await modal.getByRole("button", { name: "提交日志包" }).click();
  await expect(page.locator(".ant-message").getByText("任务已创建")).toBeVisible();
  await page.waitForURL(/\/tasks\/task-kpi_v6_log_supplement_20261105$/);
  await expect(page.getByRole("heading", { name: "KPI_V6_Log_Supplement_20261105.zip" })).toBeVisible();
  await expect(page.getByText("未选择规则适用网元类型")).toBeVisible();
});
