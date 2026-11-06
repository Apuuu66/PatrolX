import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  type KpiMetricEvidenceV6,
  type KpiMetricResultV6,
  type KpiTechnicalAnalysisV6,
} from "../../api/http";
import { KpiEvidenceDrawer } from "./KpiEvidenceDrawer";

vi.mock("../../api/http", () => ({
  api: {
    getKpiMetricEvidenceV6: vi.fn(),
    getKpiMetricTechnicalAnalysisV6: vi.fn(),
  },
}));

function makeMetric(): KpiMetricResultV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    measurement_unit_id: "MU_MEDIA",
    measurement_unit_name: "媒体资源测量单元",
    metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
    metric_name: "媒体资源创建成功率",
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
    reason: "源包成功率低于失败阈值。",
    evidence_available: true,
  };
}

function makeBaseEvidence(): KpiMetricEvidenceV6 {
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
    groups: [
      {
        object_key: "media-resource",
        period_minutes: 15,
        today: {
          date: "2026-11-05",
          value: 63.7,
          numerator: null,
          denominator: null,
          valid_count: 1,
          first_measured_at: "2026-11-05T08:00:00Z",
          last_measured_at: "2026-11-05T08:00:00Z",
          status: "ok",
        },
        yesterday: {
          date: "2026-11-04",
          value: 75,
          numerator: null,
          denominator: null,
          valid_count: 1,
          first_measured_at: "2026-11-04T08:00:00Z",
          last_measured_at: "2026-11-04T08:00:00Z",
          status: "ok",
        },
        current_status: "fail",
        trend_status: "worsened",
        reason: "源包成功率低于失败阈值。",
        source_files: ["PerfResult_20261105000000.zip"],
      },
    ],
    seven_day_trend: [
      {
        date: "2026-11-05",
        value: 63.7,
        numerator: null,
        denominator: null,
        valid_count: 1,
        first_measured_at: "2026-11-05T08:00:00Z",
        last_measured_at: "2026-11-05T08:00:00Z",
        status: "ok",
      },
    ],
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
  };
}

function makeDerivedEvidence(): KpiMetricEvidenceV6 {
  const base = makeBaseEvidence();
  return {
    ...base,
    metric_resource_id: "ME_DERIVED_MEDIA_SUCCESS_RATE",
    metric: {
      name: "本地派生成功率",
      role: "derived",
      is_percentage: true,
      formula: "成功数 / 请求数 × 100",
      daily_aggregation: "mean",
      current_status: "fail",
      trend_status: "worsened",
    },
    current: { ...base.current, value: 64.5, numerator: 129, denominator: 200 },
    previous: { ...base.previous!, value: 75, numerator: 150, denominator: 200 },
    change_value: -10.5,
    groups: base.groups.map((group) => ({
      ...group,
      today: { ...group.today, value: 64.5 },
      yesterday: { ...group.yesterday, value: 75 },
    })),
    seven_day_trend: base.seven_day_trend.map((point) => ({ ...point, value: 64.5 })),
    components: [
      { metric_resource_id: "ME_SUCCESS", name: "成功数", role: "numerator", value: 129 },
      { metric_resource_id: "ME_REQUESTS", name: "请求数", role: "denominator", value: 200 },
    ],
  };
}

function makeTechnicalAnalysis(): KpiTechnicalAnalysisV6 {
  return {
    task_id: "task-umf",
    measurement_unit_id: "MU_MEDIA",
    metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
    generated_at: "2026-11-05T09:00:00Z",
    cross_task_history: [
      {
        task_id: "task-umf",
        data_date: "2026-11-05",
        value: 63.7,
        status: "ok",
      },
      {
        task_id: "task-umf-yesterday",
        data_date: "2026-11-04",
        value: 75,
        status: "ok",
      },
    ],
    version_comparisons: [],
  };
}

function DrawerHarness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) triggerRef.current?.focus();
  }, [open]);
  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>
        打开指标证据
      </button>
      {open ? (
        <KpiEvidenceDrawer
          metric={makeMetric()}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

describe("KpiEvidenceDrawer", () => {
  beforeEach(() => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockReset();
    vi.mocked(api.getKpiMetricTechnicalAnalysisV6).mockReset();
  });

  it("源包直出指标只展示原值、来源文件和真实源列名，不展示公式或分子分母", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeBaseEvidence());
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));

    expect(await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" })).toBeDefined();
    expect(api.getKpiMetricEvidenceV6).toHaveBeenCalledWith(
      "task-umf",
      "MU_MEDIA",
      "ME_MEDIA_CREATION_SUCCESS_RATE",
    );
    expect(api.getKpiMetricTechnicalAnalysisV6).not.toHaveBeenCalled();
    expect(screen.getByText("源包直出 · base")).toBeDefined();
    expect(screen.getAllByText("PerfResult_20261105000000.zip").length).toBeGreaterThan(0);
    expect(screen.getByText("Media Resource Creation Success Rate(%)")).toBeDefined();
    expect(screen.getByText("Media Resource Creation Requests Success Rate(%)")).toBeDefined();
    expect(screen.queryByText("计算公式")).toBeNull();
    expect(screen.queryByText("分子")).toBeNull();
    expect(screen.queryByText("分母")).toBeNull();
    expect(screen.queryByText(/关联证据/)).toBeNull();
    expect(screen.queryByText(/请求 200/)).toBeNull();
    expect(screen.queryByText(/成功 129/)).toBeNull();
    expect(screen.queryByText("129 / 180")).toBeNull();
    expect(screen.queryByText("71.67")).toBeNull();
  });

  it("只有派生指标展示公式、分子、分母和计算组件", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeDerivedEvidence());
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));

    expect(await screen.findByText("PatrolX 计算 · derived")).toBeDefined();
    expect(screen.getByText("成功数 / 请求数 × 100")).toBeDefined();
    expect(screen.getAllByText("129").length).toBeGreaterThan(0);
    expect(screen.getAllByText("200").length).toBeGreaterThan(0);
    expect(screen.getByText("计算组件")).toBeDefined();
  });

  it("接口省略可选原因码和组件时仍可展示证据", async () => {
    const evidence = makeBaseEvidence();
    delete evidence.reason_codes;
    delete evidence.components;
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(evidence);
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));

    expect(await screen.findByText("源包直出 · base")).toBeDefined();
    expect(screen.getByText("判定原因码").parentElement?.textContent).toContain("—");
  });

  it("技术分析在展开后才请求，并在抽屉内展示跨任务历史", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeBaseEvidence());
    vi.mocked(api.getKpiMetricTechnicalAnalysisV6).mockResolvedValue(makeTechnicalAnalysis());
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));
    await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });
    expect(screen.queryByText("task-umf-yesterday")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "展开技术分析" }));

    await waitFor(() =>
      expect(api.getKpiMetricTechnicalAnalysisV6).toHaveBeenCalledWith(
        "task-umf",
        "MU_MEDIA",
        "ME_MEDIA_CREATION_SUCCESS_RATE",
      ),
    );
    const technical = await screen.findByTestId("kpi-technical-analysis");
    expect(within(technical).getByText("task-umf-yesterday")).toBeDefined();
    expect(within(technical).getByText("75%")).toBeDefined();
  });

  it("证据加载失败保留抽屉并允许重试", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6)
      .mockRejectedValueOnce(new Error("证据文件暂时不可读"))
      .mockResolvedValue(makeBaseEvidence());
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));

    expect(await screen.findByText("证据文件暂时不可读")).toBeDefined();
    expect(screen.getByRole("dialog", { name: "媒体资源创建成功率证据" })).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "重试加载证据" }));
    expect(await screen.findByText("Media Resource Creation Success Rate(%)")).toBeDefined();
    expect(api.getKpiMetricEvidenceV6).toHaveBeenCalledTimes(2);
  });

  it("关闭按钮与 Escape 关闭后都恢复触发按钮焦点", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeBaseEvidence());
    render(<DrawerHarness />);
    const trigger = screen.getByRole("button", { name: "打开指标证据" });

    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole("button", { name: "关闭指标证据" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));

    await userEvent.click(trigger);
    await screen.findByRole("dialog", { name: "媒体资源创建成功率证据" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("打开时焦点进入抽屉且关闭按钮可通过键盘操作", async () => {
    vi.mocked(api.getKpiMetricEvidenceV6).mockResolvedValue(makeBaseEvidence());
    render(<DrawerHarness />);

    await userEvent.click(screen.getByRole("button", { name: "打开指标证据" }));

    const close = await screen.findByRole("button", { name: "关闭指标证据" });
    await waitFor(() => expect(document.activeElement).toBe(close));
    close.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
