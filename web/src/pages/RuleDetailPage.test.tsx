import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    vi.mocked(api.getTask).mockResolvedValue({ status: "completed" } as never);
  });

  it("按结论 → 源文件匹配 → 发现 → 证据 → 技术信息排序，首屏给出状态、严重度、结论与建议", async () => {
    vi.mocked(api.getRuleResult).mockResolvedValue(makeRule());
    vi.mocked(api.listInspectors).mockResolvedValue([makeInspector()]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("rule-section-conclusion")).toBeDefined();
    });

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
    expect(conclusion.textContent).toContain("FAIL");
    expect(conclusion.textContent).toContain("high");
    expect(screen.getByTestId("rule-section-evidence").textContent).toContain("告警生命周期分组");
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
