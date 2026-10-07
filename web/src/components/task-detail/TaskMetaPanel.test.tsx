import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../api/http";
import { TaskMetaPanel } from "./TaskMetaPanel";

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-demo",
    name: "样例任务",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-10-08T02:00:00Z",
    completed_at: "2026-10-08T02:05:00Z",
    stats: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
    device_id: null,
    ...overrides,
  };
}

function ledgerInventory(names: string[]): NonNullable<TaskSummary["inventory"]> {
  return {
    devices: names.map((normalized_name) => ({ normalized_name })),
  } as unknown as NonNullable<TaskSummary["inventory"]>;
}

describe("TaskMetaPanel", () => {
  it("设备 ID 缺省时展示台账解析出的网元名称", () => {
    render(
      <TaskMetaPanel
        task={makeTask({ inventory: ledgerInventory(["CSP-SZ-01", "UMF-SZ-01"]) })}
        system={null}
      />,
    );

    expect(screen.getByText("CSP-SZ-01、UMF-SZ-01")).toBeTruthy();
    expect(screen.getByText("（台账解析）")).toBeTruthy();
  });

  it("已填写设备 ID 时保持手工值且不展示台账解析提示", () => {
    render(
      <TaskMetaPanel
        task={makeTask({ device_id: "manual-001", inventory: ledgerInventory(["CSP-SZ-01"]) })}
        system={null}
      />,
    );

    expect(screen.getByText("manual-001")).toBeTruthy();
    expect(screen.queryByText("（台账解析）")).toBeNull();
  });

  it("管理员编辑设备 ID 时使用手工值而不是台账名称", () => {
    const onEditDevice = vi.fn();
    render(
      <TaskMetaPanel
        task={makeTask({ inventory: ledgerInventory(["CSP-SZ-01"]) })}
        system={null}
        deviceEditable
        onEditDevice={onEditDevice}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(onEditDevice).toHaveBeenCalledWith("");
  });
});
