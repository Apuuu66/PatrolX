import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlarmRecurrencePanel, type AlarmRecurrenceMetadata } from "./AlarmRecurrencePanel";

const zeroStatus = { "Not Cleared": 0, "Normal Cleared": 0, "Reset Cleared": 0, Unknown: 0 };
const zeroSeverity = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, UNKNOWN: 0 };
const flags = {
  multi_lifecycle: true,
  repeat_reporting: true,
  short_alarm: false,
  rapid_recurrence: true,
  reset_cleared: false,
};

function makeMetadata(): AlarmRecurrenceMetadata {
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
      alarm_types: 2,
      multi_lifecycle_types: 1,
      repeat_reporting_types: 1,
      short_alarm_types: 0,
      rapid_recurrence_types: 1,
      reset_cleared_records: 1,
      repeat_positive_records: 5,
      repeat_totals_complete: true,
      estimated_report_totals_complete: true,
      types_truncated: false,
      details_truncated: false,
      findings_truncated: false,
    },
    status_counts: { "Not Cleared": 1, "Normal Cleared": 22, "Reset Cleared": 1, Unknown: 0 },
    severity_counts: { CRITICAL: 2, HIGH: 1, MEDIUM: 0, LOW: 0, UNKNOWN: 0 },
    types: [
      {
        type_key: "alarm.recurrence:1001",
        app_name: "CSP核心服务",
        alarm_id: "1001",
        alarm_name: "数据库连接池耗尽",
        lifecycle_count: 3,
        not_cleared_count: 1,
        raw_repeat_times_total: 7,
        max_single_repeat_times: 5,
        estimated_report_total: 10,
        repeat_totals_complete: true,
        first_raised_at: "2026-09-01T02:00:01+00:00",
        last_raised_at: "2026-09-01T02:20:01+00:00",
        max_duration_sec: 1864,
        min_adjacent_gap_sec: 900,
        status_counts: { "Not Cleared": 1, "Normal Cleared": 2, "Reset Cleared": 0, Unknown: 0 },
        severity_counts: { CRITICAL: 2, HIGH: 1, MEDIUM: 0, LOW: 0, UNKNOWN: 0 },
        flags,
        object_count: 1,
        objects: [
          {
            object: "pod-umf-1",
            lifecycle_count: 3,
            not_cleared_count: 1,
            raw_repeat_times_total: 7,
            max_single_repeat_times: 5,
            estimated_report_total: 10,
            repeat_totals_complete: true,
            first_raised_at: "2026-09-01T02:00:01+00:00",
            last_raised_at: "2026-09-01T02:20:01+00:00",
            max_duration_sec: 1864,
            min_adjacent_gap_sec: 900,
            status_counts: { "Not Cleared": 1, "Normal Cleared": 2, "Reset Cleared": 0, Unknown: 0 },
            severity_counts: { CRITICAL: 2, HIGH: 1, MEDIUM: 0, LOW: 0, UNKNOWN: 0 },
            flags,
          },
        ],
        objects_truncated: false,
        source_refs: [{ source_file: "alarm/alarm_history_001.csv", line_no: 2 }],
      },
      {
        type_key: "alarm.recurrence:2001",
        app_name: "CSP核心服务",
        alarm_id: "2001",
        alarm_name: "仅重置清除",
        lifecycle_count: 1,
        not_cleared_count: 0,
        raw_repeat_times_total: 0,
        max_single_repeat_times: 0,
        estimated_report_total: 1,
        repeat_totals_complete: true,
        first_raised_at: "2026-09-01T02:10:01+00:00",
        last_raised_at: "2026-09-01T02:10:01+00:00",
        max_duration_sec: 60,
        min_adjacent_gap_sec: null,
        status_counts: { ...zeroStatus, "Reset Cleared": 1 },
        severity_counts: { ...zeroSeverity, LOW: 1 },
        flags: {
          multi_lifecycle: false,
          repeat_reporting: false,
          short_alarm: true,
          rapid_recurrence: false,
          reset_cleared: true,
        },
        object_count: 1,
        objects: [],
        objects_truncated: false,
        source_refs: [{ source_file: "alarm/alarm_history_002.csv", line_no: 9 }],
      },
    ],
    notes: [
      "原始 Repeat Times 合计与估算上报总数是两个独立口径",
      "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
      "Reset Cleared 不代表稳定恢复",
    ],
  };
}

const metrics = [
  { key: "valid_lifecycles", value: 24 },
  { key: "alarm_types", value: 2 },
  { key: "raw_repeat_times_total", value: 7 },
  { key: "estimated_reports_total", value: 10 },
];

describe("AlarmRecurrencePanel", () => {
  it("汇总生命周期、类型及两种重复计数口径，并标记反复风险", () => {
    render(<AlarmRecurrencePanel metadata={makeMetadata()} metrics={metrics} />);

    const summary = screen.getByTestId("alarm-recurrence-summary");
    expect(summary.textContent).toContain("有效生命周期 24");
    expect(summary.textContent).toContain("告警类型 2");
    expect(summary.textContent).toContain("原始 Repeat Times 7 次");
    expect(summary.textContent).toContain("估算上报 10 次");
    expect(summary.textContent).toContain("Σ(1 + Repeat Times)");

    const table = screen.getByTestId("alarm-recurrence-types");
    expect(table.textContent).toContain("数据库连接池耗尽");
    expect(table.textContent).toContain("生命周期");
    expect(table.textContent).toContain("原始重复");
    expect(table.textContent).toContain("估算上报");
    expect(table.textContent).toContain("最大单条重复");
    expect(table.textContent).toContain("快速复发");
    expect(table.textContent).toContain("Reset Cleared");
  });

  it("展开告警类型后展示对象级状态和严重级明细", () => {
    render(<AlarmRecurrencePanel metadata={makeMetadata()} metrics={metrics} />);

    fireEvent.click(screen.getAllByRole("button", { name: "展开行" })[0]);

    const objects = screen.getByTestId("alarm-recurrence-objects");
    expect(objects.textContent).toContain("pod-umf-1");
    expect(objects.textContent).toContain("未清除 1");
    expect(objects.textContent).toContain("紧急 2");
  });

  it("全部列显示首次/最近时间和来源，精简列隐藏", () => {
    const { rerender } = render(<AlarmRecurrencePanel metadata={makeMetadata()} metrics={metrics} />);
    expect(screen.queryByText("alarm/alarm_history_001.csv:2")).toBeNull();

    rerender(<AlarmRecurrencePanel metadata={makeMetadata()} metrics={metrics} showAllColumns />);
    expect(screen.getAllByText("alarm/alarm_history_001.csv:2").length).toBeGreaterThan(0);
    expect(screen.getByTestId("alarm-recurrence-types").textContent).toContain("首次 / 最近上报");
  });

  it("展示截断与质量口径提示", () => {
    const metadata = makeMetadata();
    metadata.totals.details_truncated = true;
    metadata.totals.findings_truncated = true;
    render(<AlarmRecurrencePanel metadata={metadata} metrics={metrics} />);

    const notice = screen.getByTestId("alarm-recurrence-truncated");
    expect(notice.textContent).toContain("类型或对象明细仅展示前 100 条");
    expect(notice.textContent).toContain("汇总与指标仍基于全部有效数据");
  });
});
