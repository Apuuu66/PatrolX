import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTaskDetailData } from "./useTaskDetailData";
import type { TaskDetailData } from "./taskDetailData";

const loadTaskDetailData = vi.hoisted(() => vi.fn());
const task: TaskDetailData["task"]["data"] = {
  task_id: "task-running",
  name: "运行任务",
  mode: "local",
  status: "running",
  trigger: "ui",
  created_at: "2026-10-07T00:00:00Z",
  stats: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 0 },
};

const data: TaskDetailData = {
  task: { status: "ready", data: task },
  system: { status: "ready", data: null },
  logs: { status: "ready", data: [] },
  hiddenRuleCodes: new Set(),
};

vi.mock("./taskDetailData", () => ({
  loadTaskDetailData,
}));

describe("useTaskDetailData", () => {
  beforeEach(() => {
    loadTaskDetailData.mockResolvedValue(data);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps detail data interactive while polling a running task", async () => {
    const { result } = renderHook(() => useTaskDetailData("task-running"));
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    expect(loadTaskDetailData).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadTaskDetailData).toHaveBeenCalledTimes(2);
    expect(loadTaskDetailData).toHaveBeenNthCalledWith(1, "task-running", undefined, {
      scope: "full",
      previous: null,
    });
    expect(loadTaskDetailData).toHaveBeenNthCalledWith(2, "task-running", undefined, {
      scope: "refresh",
      previous: data,
    });
    expect(result.current.busy).toBe(true);
    expect(result.current.loading).toBe(false);
  });
});
