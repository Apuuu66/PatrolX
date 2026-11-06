import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  type KpiMeasurementUnitPageV6,
  type KpiMetricEvidenceV6,
  type KpiMetricResultPageV6,
  type KpiMetricResultV6,
  type KpiTeamFocusPageV6,
  type KpiTeamFocusPatchResponseV6,
  type KpiTaskSummaryV6,
} from "../api/http";
import { KpiResultWorkbenchPage } from "./KpiResultWorkbenchPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {
    code: string;
    status: number;
    detail?: unknown;

    constructor(code: string, message: string, status = 400, detail?: unknown) {
      super(message);
      this.code = code;
      this.status = status;
      this.detail = detail;
    }
  },
  api: {
    getKpiTaskSummaryV6: vi.fn(),
    listKpiTaskMetricsV6: vi.fn(),
    getKpiMetricEvidenceV6: vi.fn(),
    getKpiMetricTechnicalAnalysisV6: vi.fn(),
    listKpiTeamFocusV6: vi.fn(),
    patchKpiTeamFocusV6: vi.fn(),
    listKpiMeasurementUnitsV6: vi.fn(),
    rerunTask: vi.fn(),
    rebuildTask: vi.fn(),
  },
}));

function makeSummary(overrides: Partial<KpiTaskSummaryV6> = {}): KpiTaskSummaryV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    result_contract_version: "v6",
    data_date: "2026-11-05",
    previous_date: "2026-11-04",
    latest_measured_at: "2026-11-05T08:00:00Z",
    counts: {
      enabled_measurement_unit_count: 1,
      all_metric_count: 20,
      team_focus_count: 10,
      needs_attention_count: 10,
      no_action_count: 0,
      unavailable_focus_count: 0,
    },
    needs_attention_groups: [
      { group: "failure", order: 1, count: 3 },
      { group: "warning", order: 2, count: 2 },
      { group: "trend_degraded", order: 3, count: 3 },
      { group: "unjudgeable", order: 4, count: 1 },
      { group: "needs_config", order: 5, count: 1 },
    ],
    rule_scope: {
      business_rule_count: 1,
      has_executable_rules: true,
      notice: null,
    },
    notices: [],
    ...overrides,
  };
}

function makeMetric(
  metricResourceId: string,
  metricName: string,
  overrides: Partial<KpiMetricResultV6> = {},
): KpiMetricResultV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    measurement_unit_id: "MU_MEDIA",
    measurement_unit_name: "媒体资源测量单元",
    metric_resource_id: metricResourceId,
    metric_name: metricName,
    role: "base",
    importance: "P1",
    importance_rank: 1,
    availability: "available",
    is_team_focus: true,
    current_status: "fail",
    yesterday_trend: "worsened",
    needs_attention_group: "failure",
    special_state: null,
    today_value: 63.7,
    yesterday_value: 75,
    change_value: -11.3,
    change_unit: "pp",
    reason: "源包成功率低于失败阈值，且较昨日下降超过容差。",
    evidence_available: true,
    ...overrides,
  };
}

function makePage(
  items: KpiMetricResultV6[],
  emptyState: KpiMetricResultPageV6["empty_state"] = "none",
): KpiMetricResultPageV6 {
  return {
    items,
    total: items.length,
    view_total: items.length,
    page: 1,
    page_size: 20,
    empty_state: emptyState,
    applied_filters: {
      search: null,
      measurement_unit_id: null,
      current_status: null,
      yesterday_trend: null,
      needs_attention_group: null,
    },
  };
}

function makeTeamFocusPage(): KpiTeamFocusPageV6 {
  return {
    network_element_type: "UMF",
    revision: 4,
    page: 1,
    page_size: 200,
    total: 1,
    available_count: 1,
    unavailable_count: 0,
    can_write: true,
    items: [
      {
        network_element_type: "UMF",
        measurement_unit_id: "MU_MEDIA",
        measurement_unit_name: "媒体资源测量单元",
        metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
        metric_name: "媒体资源创建成功率",
        availability: "available",
        availability_reason: null,
        added_by: "maintainer",
        added_at: "2026-11-04T08:00:00Z",
      },
    ],
  };
}

const TEAM_FOCUS_PATCH_RESPONSE: KpiTeamFocusPatchResponseV6 = {
  network_element_type: "UMF",
  revision: 5,
  added_count: 1,
  removed_count: 0,
  available_count: 2,
  unavailable_count: 0,
};

function makeMeasurementUnitPage(): KpiMeasurementUnitPageV6 {
  return {
    total: 1,
    page: 1,
    page_size: 200,
    items: [
      {
        network_element_type: "UMF",
        measurement_unit_id: "MU_MEDIA",
        name_zh: "媒体资源测量单元",
        name_en: "Media Resource",
        inspection_enabled: true,
        revision: 1,
        base_metric_count: 20,
        derived_metric_count: 0,
        confirmed_binding_count: 20,
        candidate_binding_count: 0,
        configuration_state: "complete",
        recovery_state: "none",
        source: "preset",
        updated_at: "2026-11-05T08:00:00Z",
      },
    ],
  };
}

function makeEvidence(overrides: Partial<KpiMetricEvidenceV6> = {}): KpiMetricEvidenceV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    measurement_unit_id: "MU_MEDIA",
    metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
    metric: {
      name: "媒体资源创建成功率",
      role: "base",
      is_percentage: true,
      formula: null,
      daily_aggregation: "latest",
      current_status: "fail",
      trend_status: "worsened",
    },
    current: {
      date: "2026-11-05",
      value: 63.7,
      numerator: null,
      denominator: null,
      valid_count: 1,
      first_measured_at: "2026-11-05T08:00:00Z",
      last_measured_at: "2026-11-05T08:00:00Z",
      status: "ok",
    },
    previous: {
      date: "2026-11-04",
      value: 75,
      numerator: null,
      denominator: null,
      valid_count: 1,
      first_measured_at: "2026-11-04T08:00:00Z",
      last_measured_at: "2026-11-04T08:00:00Z",
      status: "ok",
    },
    change_value: -11.3,
    change_unit: "pp",
    reason: "源包成功率低于失败阈值。",
    reason_codes: ["below_critical_threshold"],
    valid_count: 1,
    current_threshold: {
      direction: "higher_better",
      warning_threshold: 80,
      critical_threshold: 70,
      source: "custom",
    },
    change_threshold: { value: 5, unit: "pp", source: "custom" },
    components: [],
    groups: [],
    seven_day_trend: [],
    sources: [
      {
        file: "PerfResult_20261105000000.zip",
        record_group: null,
        raw_source_names: [
          "Media Resource Creation Success Rate(%)",
          "Media Resource Creation Requests Success Rate(%)",
        ],
      },
    ],
    ...overrides,
  };
}

const SIX_METRICS = [
  makeMetric("ME_MEDIA_CREATION_FAILURE_RESPONSES", "媒体资源创建失败响应数"),
  makeMetric("ME_MEDIA_CREATION_SUCCESS_RATE", "媒体资源创建成功率"),
  makeMetric("ME_MEDIA_DELETION_FAILURE_RESPONSES", "媒体资源删除失败响应数"),
  makeMetric("ME_MEDIA_CREATION_REQUESTS", "媒体资源创建请求数"),
  makeMetric("ME_MEDIA_MODIFICATION_SUCCESS_RESPONSES", "媒体资源修改成功响应数"),
  makeMetric("ME_MEDIA_CREATION_SUCCESS_RESPONSES", "媒体资源创建成功响应数"),
];

function renderPage(taskId = "task-umf") {
  return render(
    <MemoryRouter initialEntries={[`/tasks/${taskId}/kpi`]}>
      <Routes>
        <Route path="/tasks/:taskId/kpi" element={<KpiResultWorkbenchPage />} />
        <Route path="/tasks/:taskId/report" element={<div>任务报告页</div>} />
        <Route path="/tasks/:taskId" element={<div>任务详情页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function SwitchingTaskHarness() {
  const navigate = useNavigate();
  return (
    <>
      <button type="button" onClick={() => navigate("/tasks/task-csp/kpi")}>
        切换到任务 CSP
      </button>
      <KpiResultWorkbenchPage />
    </>
  );
}

function setWideEvidenceLayout(wide: boolean) {
  vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
    matches: query === "(min-width: 1440px)" ? wide : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("KpiResultWorkbenchPage", () => {
  beforeEach(() => {
    setWideEvidenceLayout(false);
    vi.mocked(api.getKpiTaskSummaryV6).mockResolvedValue(makeSummary());
    vi.mocked(api.listKpiTaskMetricsV6).mockResolvedValue(makePage(SIX_METRICS));
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeEvidence());
    vi.mocked(api.listKpiTeamFocusV6).mockResolvedValue(makeTeamFocusPage());
    vi.mocked(api.patchKpiTeamFocusV6).mockResolvedValue(TEAM_FOCUS_PATCH_RESPONSE);
    vi.mocked(api.listKpiMeasurementUnitsV6).mockResolvedValue(makeMeasurementUnitPage());
  });

  it("默认读取需处理视图并按服务端顺序展示结果", async () => {
    renderPage();

    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));
    expect(api.listKpiTaskMetricsV6).toHaveBeenCalledWith(
      "task-umf",
      expect.objectContaining({
        view: "needs_attention",
        page: 1,
        page_size: 20,
      }),
    );
    expect(
      screen.getAllByTestId("kpi-metric-row").map((row) => row.getAttribute("data-metric-id")),
    ).toEqual([
      "ME_MEDIA_CREATION_FAILURE_RESPONSES",
      "ME_MEDIA_CREATION_SUCCESS_RATE",
      "ME_MEDIA_DELETION_FAILURE_RESPONSES",
      "ME_MEDIA_CREATION_REQUESTS",
      "ME_MEDIA_MODIFICATION_SUCCESS_RESPONSES",
      "ME_MEDIA_CREATION_SUCCESS_RESPONSES",
    ]);
  });

  it("结果视图只保留一层卡片容器", async () => {
    const { container } = renderPage();

    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));
    expect(container.querySelectorAll(".kpi-results-panel")).toHaveLength(1);
  });

  it("切换三视图和组合筛选只刷新结果，不改写全局汇总", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("tab", { name: "全部指标 20" }));
    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({ view: "all", page: 1 }),
      ),
    );

    await userEvent.click(screen.getByRole("tab", { name: "团队关注 10" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "搜索指标" }), "媒体");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "测量单元筛选" }),
      "MU_MEDIA",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "当前判定筛选" }),
      "fail",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "昨日趋势筛选" }),
      "worsened",
    );

    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({
          view: "team_focus",
          page: 1,
          page_size: 20,
          search: "媒体",
          measurement_unit_id: "MU_MEDIA",
          current_status: "fail",
          yesterday_trend: "worsened",
        }),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: /预警\s*2/ }));
    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({
          view: "needs_attention",
          needs_attention_group: "warning",
          search: "媒体",
          measurement_unit_id: "MU_MEDIA",
          current_status: "fail",
          yesterday_trend: "worsened",
        }),
      ),
    );
    expect(api.getKpiTaskSummaryV6).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10");
    expect(screen.getByTestId("kpi-summary-all").textContent).toContain("20");
  });

  it("清除全部筛选后只恢复当前视图，不重读全局汇总", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.type(screen.getByRole("searchbox", { name: "搜索指标" }), "媒体");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "当前判定筛选" }),
      "fail",
    );
    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({ search: "媒体", current_status: "fail" }),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "清除全部筛选" }));

    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({
          view: "needs_attention",
          page: 1,
          search: undefined,
          measurement_unit_id: undefined,
          current_status: undefined,
          yesterday_trend: undefined,
          needs_attention_group: undefined,
        }),
      ),
    );
    expect(screen.getByRole("searchbox", { name: "搜索指标" })).toHaveProperty("value", "");
    expect(api.getKpiTaskSummaryV6).toHaveBeenCalledTimes(1);
  });

  it("成功率只展示源包直出的 base 值，不在页面重算成功率", async () => {
    renderPage();

    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));
    const row = screen
      .getAllByTestId("kpi-metric-row")
      .find((item) => item.getAttribute("data-metric-id") === "ME_MEDIA_CREATION_SUCCESS_RATE");
    expect(row).toBeDefined();
    expect(row?.textContent).toContain("源包直出 · base");
    expect(row?.textContent).toContain("63.7");
    expect(row?.textContent).not.toContain("71.67");
    expect(row?.textContent).not.toContain("129 / 180");
    expect(screen.queryByText(/公式/)).toBeNull();
  });

  it("从结果行打开证据，关闭后保留列表上下文并恢复触发按钮焦点", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    const trigger = screen.getByRole("button", { name: "查看媒体资源创建成功率证据" });
    await userEvent.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });
    const selectedRow = screen
      .getAllByTestId("kpi-metric-row")
      .find((item) => item.getAttribute("data-metric-id") === "ME_MEDIA_CREATION_SUCCESS_RATE");
    expect(selectedRow?.className).toContain("is-selected");
    expect(api.getKpiMetricEvidenceV6).toHaveBeenCalledWith(
      "task-umf",
      "MU_MEDIA",
      "ME_MEDIA_CREATION_SUCCESS_RATE",
    );
    expect(api.getKpiMetricTechnicalAnalysisV6).not.toHaveBeenCalled();
    expect(within(dialog).getAllByText("Media Resource Creation Success Rate(%)").length).toBeGreaterThan(0);
    expect(within(dialog).queryByText("计算公式")).toBeNull();

    await userEvent.click(within(dialog).getByRole("button", { name: "关闭指标证据" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6);
    expect(selectedRow?.className).not.toContain("is-selected");
    expect(document.activeElement).toBe(trigger);
  });

  it("1440px 宽屏证据与结果列表同屏且不使用模态语义", async () => {
    setWideEvidenceLayout(true);
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: "查看媒体资源创建成功率证据" }));

    const evidence = await screen.findByRole("region", { name: "媒体资源创建成功率证据" });
    expect(evidence.getAttribute("aria-modal")).toBeNull();
    expect(screen.getByTestId("kpi-evidence-overlay").getAttribute("data-layout")).toBe("inline");
    expect(screen.getAllByTestId("kpi-metric-row").length).toBeGreaterThanOrEqual(5);
  });

  it("1280px 窄屏证据作为覆盖层展示", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: "查看媒体资源创建成功率证据" }));

    const evidence = await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });
    expect(evidence.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByTestId("kpi-evidence-overlay").getAttribute("data-layout")).toBe("overlay");
  });

  it("键盘打开另一指标时只请求对应证据并切换选中行", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    const rateTrigger = screen.getByRole("button", { name: "查看媒体资源创建成功率证据" });
    rateTrigger.focus();
    await userEvent.keyboard("{Enter}");
    await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });

    await userEvent.click(screen.getByRole("button", { name: "关闭指标证据" }));
    const requestTrigger = screen.getByRole("button", { name: "查看媒体资源创建请求数证据" });
    requestTrigger.focus();
    await userEvent.keyboard("{Enter}");

    await screen.findByRole("dialog", { name: "媒体资源创建请求数证据" });
    expect(api.getKpiMetricEvidenceV6).toHaveBeenNthCalledWith(
      1,
      "task-umf",
      "MU_MEDIA",
      "ME_MEDIA_CREATION_SUCCESS_RATE",
    );
    expect(api.getKpiMetricEvidenceV6).toHaveBeenNthCalledWith(
      2,
      "task-umf",
      "MU_MEDIA",
      "ME_MEDIA_CREATION_REQUESTS",
    );
    const selectedRows = screen
      .getAllByTestId("kpi-metric-row")
      .filter((item) => item.className.includes("is-selected"));
    expect(selectedRows).toHaveLength(1);
    expect(selectedRows[0].getAttribute("data-metric-id")).toBe("ME_MEDIA_CREATION_REQUESTS");
  });

  it("证据读取失败只影响抽屉，不改变汇总和其他结果行", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockRejectedValueOnce(new Error("证据文件暂时不可读"));
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: "查看媒体资源创建成功率证据" }));

    expect(await screen.findByText("证据文件暂时不可读")).toBeDefined();
    expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10");
    expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "重试加载证据" })).toBeDefined();
  });

  it("分组筛选只刷新结果，不改写全局汇总", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: /预警\s*2/ }));

    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({ needs_attention_group: "warning" }),
      ),
    );
    expect(api.getKpiTaskSummaryV6).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10");
    expect(screen.getByTestId("kpi-summary-all").textContent).toContain("20");
  });

  it("刷新只重读汇总与结果，不触发重跑或重建", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: "刷新当前结果" }));

    await waitFor(() => {
      expect(api.getKpiTaskSummaryV6).toHaveBeenCalledTimes(2);
      expect(api.listKpiTaskMetricsV6).toHaveBeenCalledTimes(2);
    });
    expect(api.rerunTask).not.toHaveBeenCalled();
    expect(api.rebuildTask).not.toHaveBeenCalled();
  });

  it("团队关注只有一个管理入口，且仅在任务网元类型明确时显示", async () => {
    const { unmount } = renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    expect(screen.getAllByRole("button", { name: "管理团队关注" })).toHaveLength(1);
    unmount();

    vi.mocked(api.getKpiTaskSummaryV6).mockResolvedValue(
      makeSummary({ network_element_type: null }),
    );
    renderPage("task-without-type");
    await screen.findByTestId("kpi-summary-needs-attention");

    expect(screen.queryByRole("button", { name: "管理团队关注" })).toBeNull();
  });

  it("保存团队关注后只重读汇总和当前视图，不重跑巡检或重建任务", async () => {
    vi.mocked(api.getKpiTaskSummaryV6)
      .mockResolvedValueOnce(makeSummary())
      .mockResolvedValueOnce(
        makeSummary({
          counts: {
            ...makeSummary().counts,
            team_focus_count: 11,
          },
        }),
      );
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));

    await userEvent.click(screen.getByRole("button", { name: "管理团队关注" }));
    const drawer = await screen.findByRole("dialog", { name: "管理团队关注" });
    await within(drawer).findByText("媒体资源创建成功率");
    await userEvent.click(
      within(drawer).getByRole("checkbox", { name: "关注媒体资源创建请求数" }),
    );
    await userEvent.click(within(drawer).getByRole("button", { name: "保存团队关注" }));

    await waitFor(() => {
      expect(api.patchKpiTeamFocusV6).toHaveBeenCalledWith("UMF", {
        task_id: "task-umf",
        expected_revision: 4,
        add: [
          { measurement_unit_id: "MU_MEDIA", metric_resource_id: "ME_MEDIA_CREATION_REQUESTS" },
        ],
        remove: [],
      });
      expect(api.getKpiTaskSummaryV6).toHaveBeenCalledTimes(2);
      expect(api.listKpiTaskMetricsV6).toHaveBeenCalledTimes(3);
    });
    expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
      "task-umf",
      expect.objectContaining({ view: "needs_attention", page: 1 }),
    );
    expect(screen.queryByRole("dialog", { name: "管理团队关注" })).toBeNull();
    expect(screen.getByTestId("kpi-summary-focus").textContent).toContain("11");
    expect(api.rerunTask).not.toHaveBeenCalled();
    expect(api.rebuildTask).not.toHaveBeenCalled();
  });

  it("查看任务报告进入巡检报告路由", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "查看任务报告" })).toBeDefined());

    await userEvent.click(screen.getByRole("button", { name: "查看任务报告" }));

    expect(await screen.findByText("任务报告页")).toBeDefined();
  });

  it("加载失败显示可重试错误状态", async () => {
    vi.mocked(api.getKpiTaskSummaryV6)
      .mockRejectedValueOnce(new Error("汇总服务不可用"))
      .mockResolvedValue(makeSummary());
    renderPage();

    expect(await screen.findByText("KPI 工作台加载失败")).toBeDefined();
    expect(screen.getByText("汇总服务不可用")).toBeDefined();

    await userEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByTestId("kpi-summary-needs-attention").textContent).toContain("10"));
  });

  it("旧任务 409 只提供重建入口，不伪造结果", async () => {
    vi.mocked(api.getKpiTaskSummaryV6).mockRejectedValue(
      new ApiError("task_result_requires_rebuild", "任务结果需要重建", 409),
    );
    vi.mocked(api.listKpiTaskMetricsV6).mockRejectedValue(
      new ApiError("task_result_requires_rebuild", "任务结果需要重建", 409),
    );
    renderPage();

    expect(await screen.findByText("当前任务需要重建")).toBeDefined();
    expect(screen.getByRole("button", { name: "返回任务详情并重建" })).toBeDefined();
    expect(screen.queryByTestId("kpi-metric-row")).toBeNull();
    expect(screen.queryByText(/无需处理 0/)).toBeNull();
  });

  it.each([
    ["team_focus_empty", "当前网元类型的团队关注为空"],
    ["no_task_metrics", "当前任务没有 KPI 指标"],
    ["no_matching_metrics", "没有符合当前条件的指标"],
  ] as const)("区分 %s 空态", async (emptyState, expectedText) => {
    vi.mocked(api.listKpiTaskMetricsV6).mockResolvedValue(makePage([], emptyState));
    renderPage();

    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining(expectedText));
  });

  it("切换任务时清除上一任务的分组筛选与选择", async () => {
    vi.mocked(api.getKpiTaskSummaryV6).mockImplementation((taskId) =>
      Promise.resolve(
        makeSummary({
          task_id: taskId,
          network_element_type: taskId === "task-csp" ? "CSP" : "UMF",
        }),
      ),
    );
    vi.mocked(api.listKpiTaskMetricsV6).mockImplementation((taskId) =>
      Promise.resolve(makePage(SIX_METRICS.map((item) => ({ ...item, task_id: taskId })))),
    );

    render(
      <MemoryRouter initialEntries={["/tasks/task-umf/kpi"]}>
        <Routes>
          <Route path="/tasks/:taskId/kpi" element={<SwitchingTaskHarness />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));
    await userEvent.click(screen.getByRole("button", { name: /预警\s*2/ }));
    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-umf",
        expect.objectContaining({ needs_attention_group: "warning" }),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "切换到任务 CSP" }));

    await waitFor(() =>
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith(
        "task-csp",
        expect.objectContaining({
          page: 1,
          needs_attention_group: undefined,
        }),
      ),
    );
    expect(api.getKpiTaskSummaryV6).toHaveBeenLastCalledWith("task-csp");
    const groups = screen.getByTestId("kpi-summary-groups");
    expect(
      within(groups).getAllByRole("button").filter((button) => button.getAttribute("aria-pressed") === "true"),
    ).toHaveLength(0);
  });

  it("切换任务时关闭上一任务的证据并清除选中行", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockImplementation((taskId) =>
      Promise.resolve(makeEvidence({ task_id: taskId })),
    );
    vi.mocked(api.getKpiTaskSummaryV6).mockImplementation((taskId) =>
      Promise.resolve(makeSummary({ task_id: taskId })),
    );
    vi.mocked(api.listKpiTaskMetricsV6).mockImplementation((taskId) =>
      Promise.resolve(makePage(SIX_METRICS.map((item) => ({ ...item, task_id: taskId })))),
    );
    render(
      <MemoryRouter initialEntries={["/tasks/task-umf/kpi"]}>
        <Routes>
          <Route path="/tasks/:taskId/kpi" element={<SwitchingTaskHarness />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getAllByTestId("kpi-metric-row")).toHaveLength(6));
    await userEvent.click(screen.getByRole("button", { name: "查看媒体资源创建成功率证据" }));
    await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });

    await userEvent.click(screen.getByRole("button", { name: "切换到任务 CSP" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() =>
      expect(
        screen.getAllByTestId("kpi-metric-row").filter((item) => item.className.includes("is-selected")),
      ).toHaveLength(0),
    );
  });
});
