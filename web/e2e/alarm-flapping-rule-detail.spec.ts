import { expect, test } from "@playwright/test";

const TASK_ID = "task-alarm-flapping-e2e";
const SECTION_ORDER = [
  "rule-section-conclusion",
  "rule-section-source-patterns",
  "rule-section-findings",
  "rule-section-evidence",
  "rule-section-technical",
];

function collectPageErrors(page: import("@playwright/test").Page) {
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
  return { consoleErrors, pageErrors, apiErrors };
}

test("告警闪断规则详情按结论 → 建议 → 源文件匹配 → 发现 → 证据 → 技术信息组织", async ({ page }) => {
  const { consoleErrors, pageErrors, apiErrors } = collectPageErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/tasks/${TASK_ID}/rules/alarm.flapping`);

  // 结论区首屏可见：状态、严重度、结论摘要、处理建议与重跑入口（FR-020、FR-023、SC-004）。
  const conclusion = page.getByTestId("rule-section-conclusion");
  await expect(conclusion).toBeVisible();
  await expect(conclusion.locator(".ant-tag").filter({ hasText: "失败" })).toBeVisible();
  // 严重度改为轻量"色点 + 文字"，不再占用彩色标签（FR-013、R10）
  await expect(conclusion.getByLabel("严重程度：高")).toBeVisible();
  await expect(conclusion.getByText("告警生命周期判定完成", { exact: false })).toBeVisible();
  await expect(conclusion.getByTestId("rule-recommendation")).toBeVisible();
  await expect(page.getByTestId("rule-section-source-patterns")).toBeInViewport();
  await expect(page.getByRole("button", { name: "重跑本规则" })).toBeInViewport();

  // 证据顺序（FR-020）。
  const order = await page
    .locator('[data-testid^="rule-section-"]')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-testid")));
  expect(order).toEqual(SECTION_ORDER);

  // 源文件匹配降级为结论卡内一行等宽元数据，不再独立占位（FR-015、R9、SC-005）。
  const sourcePatterns = page.getByTestId("rule-section-source-patterns");
  await expect(conclusion.getByTestId("rule-section-source-patterns")).toHaveCount(1);
  await expect(sourcePatterns).toContainText("alarm");
  const sourcePatternsBox = await sourcePatterns.boundingBox();
  expect(sourcePatternsBox?.height ?? 0).toBeLessThan(40);
  await expect(page.locator(".ant-card-head").filter({ hasText: "源文件匹配" })).toHaveCount(0);

  // 一行元数据仍可复制完整 pattern（contracts §5、§7）。
  const copyPattern = sourcePatterns.getByRole("button", { name: "复制源文件匹配" });
  await sourcePatterns.hover();
  await copyPattern.click();
  await expect(copyPattern).not.toHaveAttribute("data-copy-state", "idle");

  // 发现列表：CRITICAL / HIGH / MEDIUM 三条证据可见（SC-008）。
  const findingsCard = page.getByTestId("rule-section-findings");
  await expect(findingsCard).toContainText("发现（3）");
  for (const severity of ["严重", "高", "中"]) {
    await expect(findingsCard.getByLabel(`严重程度：${severity}`)).toHaveCount(1);
  }
  // 发现条目结构化分行：来源 / 证据 / 详情 / 建议（FR-012）。
  const firstFinding = findingsCard.getByTestId("finding-item").first();
  await expect(firstFinding.getByTestId("finding-field-source")).toContainText("alarm/alarm_history_");
  await expect(firstFinding.getByTestId("finding-field-evidence")).toContainText("出现");
  await expect(firstFinding.getByTestId("finding-field-details")).toContainText("判定为");
  await expect(firstFinding.getByTestId("finding-field-recommendation")).toContainText("优先处置");

  // 关键数值高亮（FR-013）。
  const highlights = firstFinding.locator(".rule-finding-highlight");
  await expect(highlights.first()).toBeVisible();
  await expect(highlights.filter({ hasText: "3 次" }).first()).toBeVisible();

  // 来源路径可复制（FR-014）。
  const sourceField = firstFinding.getByTestId("finding-field-source");
  const copySource = sourceField.getByRole("button", { name: "复制来源路径" });
  await sourceField.hover();
  await copySource.click();
  await expect(copySource).not.toHaveAttribute("data-copy-state", "idle");

  // 超过 4 行默认折叠，可展开查看全部证据分段（FR-014）。
  const evidenceParts = firstFinding
    .getByTestId("finding-evidence-parts")
    .locator("[data-evidence-part]");
  const collapsedParts = await evidenceParts.count();
  expect(collapsedParts).toBeGreaterThan(0);
  expect(collapsedParts).toBeLessThan(12);
  await firstFinding.getByRole("button", { name: /展开/ }).click();
  await expect(evidenceParts).toHaveCount(12);
  await expect(firstFinding.getByRole("button", { name: /收起/ })).toBeVisible();

  await expect(findingsCard.getByText("1051 / UMF核心服务").first()).toBeVisible();
  await expect(findingsCard.getByText("1052 / UMF核心服务").first()).toBeVisible();
  // 真实导出的定位信息进入证据分段（应用名称是分组键，实例定位是独立分段）。
  await expect(
    firstFinding.locator("[data-evidence-part]").filter({ hasText: "pod-umf-9" }),
  ).toHaveCount(1);
  const thirdFinding = findingsCard.getByTestId("finding-item").nth(2);
  await thirdFinding.getByRole("button", { name: /展开/ }).click();
  await expect(
    thirdFinding.locator("[data-evidence-part]").filter({ hasText: "umf-node-01" }),
  ).toHaveCount(1);

  // 证据面板：六态分布 + 分组明细（SC-005）。
  const evidence = page.getByTestId("rule-section-evidence");
  await expect(evidence).toContainText("告警生命周期分组");
  await expect(evidence.getByText("未清除且反复 1")).toBeVisible();
  await expect(evidence.getByText("未清除未反复 8")).toBeVisible();
  await expect(evidence.getByText("已清除但反复 1")).toBeVisible();
  await expect(evidence.getByText("已清除但短告警 1")).toBeVisible();
  await expect(evidence.getByText("观察窗不足 1")).toBeVisible();
  await expect(evidence.getByText("已清除且稳定 5")).toBeVisible();
  await expect(evidence.getByRole("columnheader", { name: "分组", exact: true })).toBeVisible();

  const rows = evidence.locator(".ant-table-tbody tr:not(.ant-table-measure-row)");
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

  // 指标表默认精简列，"显示全部列"可切换（FR-022）。
  const columnToggle = page.getByRole("switch", { name: "显示全部列" });
  await expect(columnToggle).toBeVisible();
  await expect(evidence.getByRole("columnheader", { name: "来源" })).toHaveCount(0);
  await expect(evidence.getByRole("columnheader", { name: "首次 / 最近出现" })).toHaveCount(0);
  await expect(evidence.getByRole("columnheader", { name: "结论" })).toBeVisible();

  await columnToggle.click();
  await expect(evidence.getByRole("columnheader", { name: "来源" })).toBeVisible();
  await expect(evidence.getByRole("columnheader", { name: "首次 / 最近出现" })).toBeVisible();

  await columnToggle.click();
  await expect(evidence.getByRole("columnheader", { name: "来源" })).toHaveCount(0);

  // 技术信息默认折叠，展开后可见完整字段（FR-005）。
  const technical = page.getByTestId("rule-section-technical");
  await expect(technical.getByText("技术信息")).toBeVisible();
  await expect(technical.getByText("规则版本")).toHaveCount(0);
  await technical.getByText("技术信息").click();
  await expect(technical.getByText("规则版本")).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(apiErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("skip 规则详情必须展示跳过原因", async ({ page }) => {
  await page.goto(`/tasks/${TASK_ID}/rules/traffic.stat`);

  const conclusion = page.getByTestId("rule-section-conclusion");
  await expect(conclusion.getByText("跳过").first()).toBeVisible();
  await expect(page.getByTestId("rule-skip-reason")).toContainText("source_patterns 未匹配到文件");
  await expect(page.getByTestId("rule-skip-reason")).toContainText("^traffic/.*$");
});

test("规则详情重跑入口在执行中可见，完成后只刷新本页结果", async ({ page }) => {
  const ruleTask = "task-rule-detail-rerun-e2e";
  let accepted = false;
  let taskPolls = 0;

  const ruleResult = (summary: string, duration: number, executedAt: string) => ({
    code: "config.a",
    name: "配置一致性",
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "fail",
    severity: "high",
    summary,
    skip_reason: null,
    executed_at: executedAt,
    duration_ms: duration,
    metrics: [],
    findings: [],
    metadata: {},
  });

  await page.route("**/api/v2/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/rerun")) {
      accepted = true;
      return route.fulfill({ status: 202, json: { task_id: ruleTask } });
    }
    if (url.pathname.endsWith("/api/v2/inspectors")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith(`/api/v2/tasks/${ruleTask}/rules/config.a`)) {
      return route.fulfill({
        json: ruleResult(
          accepted ? "重跑完成：配置不一致" : "配置不一致",
          accepted ? 99 : 12,
          accepted ? "2026-10-10T01:00:00Z" : "2026-10-10T00:00:00Z",
        ),
      });
    }
    if (url.pathname.endsWith(`/api/v2/tasks/${ruleTask}`)) {
      taskPolls += 1;
      return route.fulfill({
        json: {
          task_id: ruleTask,
          name: "规则详情重跑任务",
          mode: "local",
          status: taskPolls === 1 ? "running" : "completed",
          trigger: "ui",
          created_at: "2026-10-10T00:00:00Z",
          completed_at: taskPolls === 1 ? null : "2026-10-10T01:00:00Z",
          stats: { total: 1, pass: 0, warn: 0, fail: 1, error: 0, skip: 0, systems: 1 },
        },
      });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto(`/tasks/${ruleTask}/rules/config.a`);
  await expect(page.getByText("配置不一致", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "重跑本规则" }).click();

  await expect(page.getByTestId("rule-rerun-progress")).toBeVisible();
  await expect(page.getByText("重跑完成：配置不一致", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("rule-rerun-progress")).toHaveCount(0);
});
