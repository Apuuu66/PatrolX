import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type InspectorInfo, type RuleResult } from "../api/http";
import { RuleDetailPage } from "./RuleDetailPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    getRuleResult: vi.fn(),
    listInspectors: vi.fn(),
    rerunTask: vi.fn(),
    getTask: vi.fn(),
  },
}));

beforeAll(async () => {
  await Promise.all([
    import("../components/AlarmActiveStatePanel"),
    import("../components/AlarmFlappingPanel"),
    import("../components/AlarmRecurrencePanel"),
    import("../components/MetricPanel"),
  ]);
});

function makeAlarmMetadata() {
  return {
    schema_version: 1,
    policy: {
      short_alarm_sec: 60,
      repeat_window_sec: 600,
      min_repeat_count: 2,
      flap_gap_sec: 30,
      stable_observation_sec: 1200,
      operation_window: "00:00-06:00",
      operation_window_enabled: false,
      parameter_source: "default",
    },
    totals: {
      rows: 17,
      valid_rows: 17,
      groups: 1,
      excluded_rows: 0,
      duplicate_rows: 0,
      failed_files: 0,
      findings_truncated: false,
      groups_truncated: false,
    },
    state_counts: { uncleared_repeated: 1 },
    groups: [
      {
        alarm_code: "1051",
        object: "UMF核心服务",
        state: "uncleared_repeated",
        occurrence_count: 3,
        cleared_count: 1,
        uncleared_count: 2,
        first_seen_at: "2026-10-09T10:00:00Z",
        recent_seen_at: "2026-10-09T10:05:00Z",
        recent_cleared_at: null,
        min_repeat_gap_sec: 30,
        repeated: true,
        is_short: false,
        observation_insufficient: false,
        observation_gap_sec: 600,
        in_window_occurrences: 3,
        out_of_window_occurrences: 0,
        out_of_window_reappear: false,
        unrecovered_after_window: true,
        flap_event_count: 2,
        evidence_records: [{ source_file: "alarm/demo.csv", line_no: 3 }],
      },
    ],
    notes: [],
  };
}

function makeRule(overrides: Partial<RuleResult> = {}): RuleResult {
  return {
    code: "alarm.flapping",
    name: "告警闪断检测",
    category: "alarm",
    priority: 2,
    execution_order: 4,
    status: "fail",
    severity: "high",
    summary: "结论摘要：17 个分组，3 条 Finding",
    skip_reason: null,
    executed_at: "2026-10-10T00:00:00Z",
    duration_ms: 12,
    // 字符串取值触发指标兜底表，用于断言精简列默认值（FR-022）。
    metrics: [
      { key: "groups", label: "告警分组数", value: "17", unit: "个", threshold: null, baseline: null, series: null },
    ],
    findings: [
      {
        finding_id: "finding-1",
        title: "未清除且反复的告警：1051",
        severity: "critical",
        source_file: "alarm/demo.csv",
        evidence: "1051 / UMF核心服务 定位 pod-a",
        details: "窗口后仍未恢复",
        recommendation: "优先确认网元告警收敛配置",
      },
    ],
    metadata: { alarm_flapping: makeAlarmMetadata() },
    ...overrides,
  } as RuleResult;
}

function makeInspector(overrides: Partial<InspectorInfo> = {}): InspectorInfo {
  return {
    code: "alarm.flapping",
    name: "告警闪断检测",
    category: "alarm",
    severity: "high",
    priority: 2,
    rule_version: "1.1.0",
    hidden: false,
    description: "检测告警反复闪断的生命周期状态",
    recommendation: "处理建议：确认网元侧告警收敛配置。",
    source_patterns: ["^alarm/.*\\.csv$"],
    outputs: {},
    params: [],
    ...overrides,
  } as InspectorInfo;
}

function renderPage(ruleCode = "alarm.flapping") {
  return render(
    <App>
      <MemoryRouter initialEntries={[`/tasks/task-001/rules/${ruleCode}`]}>
        <Routes>
          <Route path="/tasks/:taskId/rules/:ruleCode" element={<RuleDetailPage />} />
        </Routes>
      </MemoryRouter>
    </App>,
  );
}

describe("RuleDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getTask).mockResolvedValue({ status: "completed" } as never);
  });

  it("按结论 → 源文件匹配 → 发现 → 证据 → 技术信息排序，首屏给出状态、严重度、结论与建议", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(makeRule());
    vi.mocked(api.listInspectors).mockResolvedValue([makeInspector()]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("rule-section-conclusion")).toBeDefined();
    });
    expect(api.getRuleResult).toHaveBeenCalledWith("task-001", "alarm.flapping", false);

    const order = Array.from(document.querySelectorAll('[data-testid^="rule-section-"]')).map((element) =>
      element.getAttribute("data-testid"),
    );
    expect(order).toEqual([
      "rule-section-conclusion",
      "rule-section-source-patterns",
      "rule-section-findings",
      "rule-section-evidence",
      "rule-section-technical",
    ]);

    const conclusion = screen.getByTestId("rule-section-conclusion");
    expect(conclusion.textContent).toContain("结论摘要：17 个分组，3 条 Finding");
    expect(conclusion.textContent).toContain("处理建议：确认网元侧告警收敛配置。");
    expect(conclusion.textContent).toContain("失败");
    expect(conclusion.textContent).toContain("高");
    expect(screen.getByTestId("rule-section-evidence").textContent).toContain("告警生命周期分组");

    // 源文件匹配降级为结论卡内一行等宽元数据（FR-015、R9、SC-005）。
    const sourcePatterns = screen.getByTestId("rule-section-source-patterns");
    expect(conclusion.contains(sourcePatterns)).toBe(true);
    expect(sourcePatterns.textContent).toContain("^alarm/.*\\.csv$");
    expect(sourcePatterns.querySelector(".ant-card-head")).toBeNull();
    expect(
      screen.getByRole("button", { name: "复制源文件匹配" }),
    ).toBeDefined();

    // 发现条目结构化分行 + 关键数值高亮（FR-012、FR-013）。
    const finding = screen.getByTestId("finding-item");
    expect(finding.querySelector('[data-testid="finding-field-source"]')).not.toBeNull();
    expect(finding.querySelector('[data-testid="finding-field-evidence"]')).not.toBeNull();
    expect(finding.querySelector('[data-testid="finding-field-details"]')).not.toBeNull();
    expect(finding.querySelector('[data-testid="finding-field-recommendation"]')).not.toBeNull();
    expect(finding.querySelectorAll(".rule-finding-highlight").length).toBeGreaterThan(0);
    // 严重度使用轻量色点变体，不再是彩色 Tag（FR-013、R10）。
    expect(finding.querySelector(".severity-plain")?.textContent).toBe("严重");
  });

  it("skip 规则展示跳过原因，缺失时给出兜底文案", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({
        status: "skip",
        skip_reason: "source_patterns 未匹配到文件: ^traffic/.*$",
        metrics: [],
        findings: [],
        metadata: {},
      }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([makeInspector({ code: "traffic.stat" })]);

    renderPage("traffic.stat");

    await waitFor(() => {
      expect(screen.getByTestId("rule-skip-reason")).toBeDefined();
    });
    expect(screen.getByTestId("rule-skip-reason").textContent).toContain("source_patterns 未匹配到文件: ^traffic/.*$");
    // 跳过原因必须与结论同屏可见，不能只藏在技术信息里（FR-015、SC-005）。
    expect(screen.getByTestId("rule-section-conclusion").textContent).toContain(
      "source_patterns 未匹配到文件: ^traffic/.*$",
    );
  });

  it("KPI 规则加载时排除原始记录，避免页面携带大体积证据数据", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({
        code: "kpi.measurement_units",
        name: "KPI 测量单元巡检",
        metadata: { measurement_units: [] },
      }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([
      makeInspector({ code: "kpi.measurement_units", name: "KPI 测量单元巡检" }),
    ]);

    renderPage("kpi.measurement_units");

    await waitFor(() => {
      expect(api.getRuleResult).toHaveBeenCalledWith(
        "task-001",
        "kpi.measurement_units",
        true,
      );
    });
  });

  it("KPI 规则详情不复制旧结果面板，结论只在 v6 工作台呈现", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({
        code: "kpi.measurement_units",
        name: "KPI 测量单元巡检",
        findings: [],
        metrics: [],
        metadata: { measurement_units: [] },
      }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([
      makeInspector({ code: "kpi.measurement_units", name: "KPI 测量单元巡检" }),
    ]);

    renderPage("kpi.measurement_units");

    await waitFor(() => expect(screen.getByTestId("rule-section-evidence")).toBeDefined());
    expect(screen.queryByTestId("measurement-inspection-panel")).toBeNull();
    expect(screen.queryByRole("heading", { name: "KPI 日健康兼容提示" })).toBeNull();
    expect(screen.queryByText("KPI 总览")).toBeNull();
    expect(screen.queryByText(/健康分/)).toBeNull();
  });

  it("skip 且无跳过原因时给出兜底文案，不静默通过", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({ status: "skip", skip_reason: null, metrics: [], findings: [], metadata: {} }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([makeInspector({ code: "traffic.stat" })]);

    renderPage("traffic.stat");

    await waitFor(() => {
      expect(screen.getByTestId("rule-skip-reason")).toBeDefined();
    });
    expect(screen.getByTestId("rule-skip-reason").textContent).toContain("未提供跳过原因");
    expect(screen.getByTestId("rule-section-conclusion").textContent).toContain("未提供跳过原因");
  });

  it("已下线规则展示历史只读提示并禁止重跑，同时保留发现与证据", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(makeRule());
    vi.mocked(api.listInspectors).mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("rule-offline-banner").textContent).toContain("该规则已下线，仅供历史查看");
    });
    expect(screen.getByTestId("rule-offline-banner").textContent).not.toContain("仅执行 KPI");

    const rerunButton = screen.getByRole("button", { name: /重跑本规则/ }) as HTMLButtonElement;
    expect(rerunButton.disabled).toBe(true);
    fireEvent.click(rerunButton);
    expect(api.rerunTask).not.toHaveBeenCalled();
    expect(screen.getByTestId("rule-section-findings").textContent).toContain("未清除且反复的告警");
    expect(screen.getByTestId("rule-section-evidence").textContent).toContain("告警生命周期分组");
    expect(screen.getByTestId("rule-section-source-patterns").textContent).toContain("该规则未声明源文件匹配范围");
  });


  it("仅渲染 alarm_active 命名空间，不混入其它告警面板", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({
        code: "alarm.active_state",
        name: "未清除告警巡检",
        summary: "活动告警 3 条、2 组；最高严重级 CRITICAL",
        metadata: {
          alarm_active: {
            schema_version: 1,
            coverage: { end_at: "2026-09-01T02:31:05+00:00", observation_note: "不是任务执行时刻或真实恢复时刻" },
            totals: { active_records: 3, active_groups: 2, details_truncated: false, findings_truncated: false },
            status_counts: { "Not Cleared": 3 },
            active_severity_counts: { CRITICAL: 1 },
            active_summary: {
              highest_severity: "CRITICAL",
              raw_repeat_times_total: 7,
              estimated_report_total: 10,
              estimated_total_is_estimate: true,
            },
            groups: [],
            records: [],
            notes: [],
          },
        },
      }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([
      makeInspector({ code: "alarm.active_state", name: "未清除告警巡检", severity: "high" }),
    ]);

    renderPage("alarm.active_state");

    await waitFor(() => {
      expect(screen.getByTestId("rule-section-evidence").textContent).toContain("最高严重级");
    });
    const evidence = screen.getByTestId("rule-section-evidence").textContent ?? "";
    expect(evidence).toContain("最高严重级");
    expect(evidence).not.toContain("告警反复上报");
    expect(evidence).not.toContain("告警生命周期分组");
  });

  it("仅渲染 alarm_recurrence 命名空间，并展示反复上报口径", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(
      makeRule({
        code: "alarm.recurrence",
        name: "告警反复上报巡检",
        summary: "有效生命周期 24 条、告警类型 2 种",
        metadata: {
          alarm_recurrence: {
            schema_version: 1,
            coverage: { end_at: "2026-09-01T02:31:05+00:00" },
            totals: { alarm_types: 2, details_truncated: false, findings_truncated: false },
            status_counts: { "Not Cleared": 1 },
            severity_counts: { CRITICAL: 1 },
            types: [],
            notes: ["原始 Repeat Times 合计与估算上报总数是两个独立口径"],
          },
        },
      }),
    );
    vi.mocked(api.listInspectors).mockResolvedValue([
      makeInspector({ code: "alarm.recurrence", name: "告警反复上报巡检", severity: "medium" }),
    ]);

    renderPage("alarm.recurrence");

    await waitFor(() => {
      expect(screen.getByTestId("rule-section-evidence").textContent).toContain("原始 Repeat Times");
    });
    const evidence = screen.getByTestId("rule-section-evidence").textContent ?? "";
    expect(evidence).toContain("原始 Repeat Times");
    expect(evidence).not.toContain("未清除告警");
    expect(evidence).not.toContain("告警生命周期分组");
  });

  it("证据表默认精简列，切换后显示全部列", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(makeRule());
    vi.mocked(api.listInspectors).mockResolvedValue([makeInspector()]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("rule-section-evidence")).toBeDefined();
    });

    expect(screen.getByRole("columnheader", { name: "结论" })).toBeDefined();
    expect(screen.queryByRole("columnheader", { name: "来源" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "阈值" })).toBeNull();

    fireEvent.click(screen.getByRole("switch", { name: "显示全部列" }));

    expect(screen.getByRole("columnheader", { name: "来源" })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: "阈值" })).toBeDefined();
  });
});
