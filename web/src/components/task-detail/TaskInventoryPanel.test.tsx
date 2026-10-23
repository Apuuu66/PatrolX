import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { TaskSummary } from "../../api/http";
import { TaskInventoryPanel } from "./TaskInventoryPanel";

type Inventory = NonNullable<TaskSummary["inventory"]>;

const SAMPLE_RAW_TEXT = "+++    CSP/*××××××××××××*/     2025-05-26  14:40:36";

function makeInventory(overrides: Partial<Inventory> = {}): Inventory {
  return {
    package_kind: "inspection",
    status: "archived",
    parser_id: "inventory.lst_me",
    parser_version: "4",
    schema_version: 3,
    site: { status: "ok", source: "upload_metadata", province: "江苏省", operator: "移动", site_key: "江苏省|移动" },
    network_element_type_filter: { requested: "UMF", status: "ok", matched_count: 1, unmatched_count: 0 },
    devices: [{ status: "ok", normalized_name: "NJ-AGG-001", network_element_type: "UMF", version: { status: "ok", raw_version: "V900R016C10SPC200" }, source_file: "config/LST ME.txt" }],
    records: [],
    source_files: ["config/LST ME.txt"],
    execution_time: {
      status: "ok",
      source: "lst_me",
      per_file: [
        {
          source_file: "config/LST ME.txt",
          raw_text: SAMPLE_RAW_TEXT,
          line: 1,
          parsed_at: "2025-05-26T06:40:36Z",
          status: "ok",
          reason: null,
        },
      ],
    },
    conflicts: [],
    errors: [],
    archived: { archived: true, device_id: "dev-1", observation_id: "obs-1", devices: [] },
    ...overrides,
  };
}

function makeTask(inventory: Inventory | null): TaskSummary {
  return {
    task_id: "task-035",
    name: "035 样例任务",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-10-23T02:00:00Z",
    completed_at: "2026-10-23T02:05:00Z",
    device_id: null,
    stats: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 0 },
    inventory,
  };
}

function renderPanel(inventory: Inventory | null) {
  return render(
    <MemoryRouter>
      <TaskInventoryPanel task={makeTask(inventory)} />
    </MemoryRouter>,
  );
}

function executionTimeSection(): HTMLElement {
  return screen.getByTestId("task-inventory-execution-time");
}

describe("TaskInventoryPanel 执行时间证据", () => {
  it("展示本次归档使用的执行时间、来源、原文、行号与解析结果", () => {
    renderPanel(makeInventory());

    const section = executionTimeSection();
    expect(within(section).getByText("设备执行时间")).toBeTruthy();
    expect(within(section).getByText(/解析成功/)).toBeTruthy();
    expect(within(section).getByText("config/LST ME.txt")).toBeTruthy();
    expect(within(section).getByText(/第 1 行/)).toBeTruthy();
    // 原文按原样保留（测试库会归一化连续空白，这里用宽松正则断言）。
    expect(
      within(section).getByText(/^\+{3}\s+CSP\/\*××××××××××××\*\/\s+2025-05-26\s+14:40:36$/),
    ).toBeTruthy();
    // 解析结果按本地时区完整展示，秒级精度；不断言具体时区偏移。
    expect(within(section).getByText(/解析结果：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/)).toBeTruthy();
  });

  it("头部无执行时间时标注兜底来源与可读原因", () => {
    renderPanel(
      makeInventory({
        execution_time: {
          status: "missing",
          source: "task",
          per_file: [
            {
              source_file: "config/LST ME.txt",
              raw_text: null,
              line: null,
              parsed_at: null,
              status: "missing",
              reason: "header_time_missing",
            },
          ],
        },
      }),
    );

    const section = executionTimeSection();
    expect(within(section).getByText("任务完成时间兜底")).toBeTruthy();
    expect(within(section).getByText(/头部未找到执行时间行/)).toBeTruthy();
  });

  it("执行时间不可信时解释回退原因", () => {
    renderPanel(
      makeInventory({
        execution_time: {
          status: "missing",
          source: "task",
          per_file: [
            {
              source_file: "config/LST ME.txt",
              raw_text: SAMPLE_RAW_TEXT,
              line: 1,
              parsed_at: null,
              status: "time_in_future",
              reason: "time_in_future",
            },
          ],
        },
      }),
    );

    expect(within(executionTimeSection()).getByText(/执行时间晚于任务完成时间/)).toBeTruthy();
  });

  it("历史证据没有执行时间时说明按任务完成时间兜底而不是留空", () => {
    renderPanel(makeInventory({ execution_time: null }));

    const section = executionTimeSection();
    expect(within(section).getByText(/历史证据/)).toBeTruthy();
    expect(within(section).getByText("任务完成时间兜底")).toBeTruthy();
  });

  it("多个来源文件各自展示自己的执行时间", () => {
    renderPanel(
      makeInventory({
        source_files: ["config/A/LST ME.txt", "config/B/LST ME.txt"],
        execution_time: {
          status: "partial",
          source: "task",
          per_file: [
            {
              source_file: "config/A/LST ME.txt",
              raw_text: SAMPLE_RAW_TEXT,
              line: 1,
              parsed_at: "2025-05-26T06:40:36Z",
              status: "ok",
              reason: null,
            },
            {
              source_file: "config/B/LST ME.txt",
              raw_text: null,
              line: null,
              parsed_at: null,
              status: "invalid",
              reason: "header_time_invalid",
            },
          ],
        },
      }),
    );

    const section = executionTimeSection();
    expect(within(section).getByText("config/A/LST ME.txt")).toBeTruthy();
    expect(within(section).getByText("config/B/LST ME.txt")).toBeTruthy();
    expect(within(section).getByText(/执行时间格式非法/)).toBeTruthy();
    expect(within(section).getByText(/部分来源回退/)).toBeTruthy();
  });
});
