import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlarmActiveStatePanel, type AlarmActiveMetadata } from "./AlarmActiveStatePanel";

function makeMetadata(overrides: Partial<AlarmActiveMetadata> = {}): AlarmActiveMetadata {
  return {
    schema_version: 1,
    coverage: {
      start_at: "2026-09-01T02:00:01+00:00",
      end_at: "2026-09-01T02:31:05+00:00",
      span_sec: 1864,
      end_basis: "max_valid_alarm_timestamp",
      timezone_policy: "naive_as_utc+08:00_then_utc",
      observation_note: "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻",
    },
    totals: {
      source_files: 2,
      failed_files: 0,
      raw_rows: 27,
      valid_records: 24,
      excluded_records: 2,
      duplicate_records: 1,
      active_records: 3,
      active_groups: 2,
      repeat_totals_complete: true,
      estimated_report_totals_complete: true,
      details_truncated: false,
      findings_truncated: false,
    },
    status_counts: { "Not Cleared": 3, "Normal Cleared": 20, "Reset Cleared": 1, Unknown: 0 },
    active_severity_counts: { CRITICAL: 1, HIGH: 1, MEDIUM: 0, LOW: 1, UNKNOWN: 0 },
    active_summary: {
      highest_severity: "CRITICAL",
      raw_repeat_times_total: 7,
      max_single_repeat_times: 5,
      estimated_report_total: 10,
      estimated_total_is_estimate: true,
    },
    groups: [
      {
        group_key: "group-1",
        app_name: "CSP核心服务",
        alarm_id: "1001",
        alarm_name: "数据库连接池耗尽",
        object: "paas-192.168.2.2",
        severity: "CRITICAL",
        first_raised_at: "2026-09-01T02:00:01+00:00",
        last_raised_at: "2026-09-01T02:20:01+00:00",
        duration_sec: 1864,
        lifecycle_count: 2,
        raw_repeat_times_total: 5,
        max_single_repeat_times: 5,
        estimated_report_total: 7,
        repeat_totals_complete: true,
        source_refs: [{ source_file: "alarm/alarm_history_001.csv", line_no: 2 }],
      },
      {
        group_key: "group-2",
        app_name: "CSP核心服务",
        alarm_id: "1002",
        alarm_name: "NTP 同步失败",
        object: "node-2",
        severity: "HIGH",
        first_raised_at: "2026-09-01T02:05:01+00:00",
        last_raised_at: "2026-09-01T02:05:01+00:00",
        duration_sec: 1564,
        lifecycle_count: 1,
        raw_repeat_times_total: 2,
        max_single_repeat_times: 2,
        estimated_report_total: 3,
        repeat_totals_complete: true,
        source_refs: [{ source_file: "alarm/alarm_history_002.csv", line_no: 7 }],
      },
    ],
    records: [
      {
        app_name: "CSP核心服务",
        alarm_id: "1001",
        alarm_name: "数据库连接池耗尽",
        object: "paas-192.168.2.2",
        severity: "CRITICAL",
        state: "Not Cleared",
        raised_at: "2026-09-01T02:00:01+00:00",
        cleared_at: null,
        duration_sec: 1864,
        repeat_times: 5,
        estimated_report_count: 6,
        source_file: "alarm/alarm_history_001.csv",
        line_no: 2,
      },
    ],
    notes: ["活动状态唯一判据为 Whether Cleared=Not Cleared"],
    ...overrides,
  };
}

describe("AlarmActiveStatePanel", () => {
  it("突出最高严重级、两种上报口径、状态分布和观察末刻口径", () => {
    render(<AlarmActiveStatePanel metadata={makeMetadata()} />);

    const summary = screen.getByTestId("alarm-active-summary");
    expect(summary.textContent).toContain("最高严重级 紧急");
    expect(summary.textContent).toContain("活动记录 3");
    expect(summary.textContent).toContain("原始 Repeat Times 7 次");
    expect(summary.textContent).toContain("估算上报 10 次");
    expect(summary.textContent).toContain("Σ(1 + Repeat Times)");
    expect(summary.textContent).toContain("不是任务执行时刻或真实恢复时刻");
    expect(screen.getByTestId("alarm-active-status-counts").textContent).toContain("未清除 3");
  });

  it("展示分组与记录明细，精简列隐藏来源，全部列显示来源行号", () => {
    const { rerender } = render(<AlarmActiveStatePanel metadata={makeMetadata()} />);

    expect(screen.getByTestId("alarm-active-groups").textContent).toContain("数据库连接池耗尽");
    expect(screen.getByTestId("alarm-active-records").textContent).toContain("数据库连接池耗尽");
    expect(screen.getByTestId("alarm-active-groups").textContent).toContain("原始重复");
    expect(screen.getByTestId("alarm-active-groups").textContent).toContain("估算上报");
    expect(screen.queryByText("alarm/alarm_history_001.csv:2")).toBeNull();

    rerender(<AlarmActiveStatePanel metadata={makeMetadata()} showAllColumns />);
    expect(screen.getAllByText("alarm/alarm_history_001.csv:2").length).toBeGreaterThan(0);
  });

  it("展示截断提示且不修改汇总口径", () => {
    const metadata = makeMetadata({
      totals: {
        ...makeMetadata().totals,
        active_records: 101,
        active_groups: 101,
        details_truncated: true,
        findings_truncated: true,
      },
    });
    render(<AlarmActiveStatePanel metadata={metadata} />);

    const notice = screen.getByTestId("alarm-active-truncated");
    expect(notice.textContent).toContain("明细仅展示前 100 条");
    expect(notice.textContent).toContain("汇总仍基于全部有效活动记录");
  });
});
