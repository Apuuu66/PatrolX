import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { TaskStats, TaskSummary } from "../api/http";
import { getTaskFailureReason, sortTasksForList } from "./taskListSort.ts";

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1, ...overrides };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task",
    name: "任务",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-10-01T00:00:00Z",
    completed_at: "2026-10-01T00:01:00Z",
    stats: makeStats(),
    ...overrides,
  };
}

describe("sortTasksForList", () => {
  it("按 failed → running → pending → completed 排序", () => {
    const sorted = sortTasksForList([
      makeTask({ task_id: "completed" }),
      makeTask({ task_id: "pending", status: "pending" }),
      makeTask({ task_id: "running", status: "running" }),
      makeTask({ task_id: "failed", status: "failed" }),
    ]);

    assert.deepEqual(
      sorted.map((task) => task.task_id),
      ["failed", "running", "pending", "completed"],
    );
  });

  it("failed 严格排在异常 completed 之前（SC-003）", () => {
    const sorted = sortTasksForList([
      makeTask({
        task_id: "abnormal",
        created_at: "2026-10-10T00:49:00Z",
        stats: makeStats({ pass: 0, fail: 5 }),
      }),
      makeTask({ task_id: "failed", status: "failed", created_at: "2026-09-22T00:00:00Z" }),
    ]);

    assert.deepEqual(
      sorted.map((task) => task.task_id),
      ["failed", "abnormal"],
    );
  });

  it("completed 且存在 fail/error 的任务提前为异常任务", () => {
    const sorted = sortTasksForList([
      makeTask({ task_id: "clean" }),
      makeTask({ task_id: "abnormal", stats: makeStats({ pass: 0, fail: 1 }) }),
      makeTask({ task_id: "running", status: "running" }),
    ]);

    assert.deepEqual(
      sorted.map((task) => task.task_id),
      ["abnormal", "running", "clean"],
    );
  });

  it("同优先级按 created_at 倒序", () => {
    const sorted = sortTasksForList([
      makeTask({ task_id: "older", created_at: "2026-10-01T00:00:00Z" }),
      makeTask({ task_id: "newer", created_at: "2026-10-03T00:00:00Z" }),
      makeTask({ task_id: "middle", created_at: "2026-10-02T00:00:00Z" }),
    ]);

    assert.deepEqual(
      sorted.map((task) => task.task_id),
      ["newer", "middle", "older"],
    );
  });

  it("不修改入参顺序", () => {
    const tasks = [makeTask({ task_id: "completed" }), makeTask({ task_id: "failed", status: "failed" })];
    const sorted = sortTasksForList(tasks);

    assert.equal(tasks[0].task_id, "completed");
    assert.equal(sorted[0].task_id, "failed");
  });
});

describe("getTaskFailureReason", () => {
  it("优先使用任务失败时数据准备的失败原因", () => {
    const reason = getTaskFailureReason(
      makeTask({
        status: "failed",
        preparation: {
          status: "fail",
          items: [
            {
              category: "inventory",
              status: "fail",
              total_count: 1,
              extracted_count: 0,
              issues: [{ type: "failed", reason: "主清单解析失败" }],
            },
          ],
          total: 1,
          success_count: 0,
          warning_count: 0,
          failure_count: 1,
          skip_count: 0,
        },
      }),
    );

    assert.equal(reason, "主清单解析失败");
  });

  it("无数据准备问题时回退到失败阶段兜底文案", () => {
    const reason = getTaskFailureReason(makeTask({ status: "failed" }));

    assert.ok(reason);
    assert.match(reason ?? "", /失败/);
  });

  it("非失败任务不产生原因摘要", () => {
    assert.equal(getTaskFailureReason(makeTask()), null);
    assert.equal(
      getTaskFailureReason(makeTask({ stats: makeStats({ pass: 0, fail: 1 }) })),
      null,
    );
  });
});
