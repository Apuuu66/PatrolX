import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("展示最后一次运行时间与任务时长，且创建时间独立", () => {
    render(
      <TaskMetaPanel
        task={makeTask({
          created_at: "2026-10-08T02:00:00Z",
          last_run_at: "2026-10-09T03:00:00Z",
          duration_ms: 95_000,
        })}
        system={null}
      />,
    );

    const panel = screen.getByTestId("task-meta-panel");
    const value = (label: string) =>
      within(panel)
        .getByText(label)
        .closest(".ant-descriptions-item")
        ?.querySelector(".ant-descriptions-item-content")?.textContent ?? "";

    expect(value("任务时长")).toBe("1 分 35 秒");
    // 创建时间与最后运行时间是两个独立字段，均按本地时区完整展示
    expect(value("创建时间")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(value("最后运行时间")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    expect(value("最后运行时间")).not.toBe(value("创建时间"));
  });

  it("从未运行任务不展示误导性时长数值", () => {
    render(
      <TaskMetaPanel
        task={makeTask({ status: "pending", completed_at: null, last_run_at: null, duration_ms: null })}
        system={null}
      />,
    );

    const panel = screen.getByTestId("task-meta-panel");
    const value = (label: string) =>
      within(panel)
        .getByText(label)
        .closest(".ant-descriptions-item")
        ?.querySelector(".ant-descriptions-item-content")?.textContent ?? "";

    expect(value("任务时长")).toBe("-");
    expect(value("最后运行时间")).toBe("-");
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
