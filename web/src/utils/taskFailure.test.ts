import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { LogEntry, TaskSummary } from "../api/http";
import { getTaskFailureStage, latestTaskFailure } from "./taskFailure.ts";

describe("latestTaskFailure", () => {
  it("优先展示最新错误及其详细原因", () => {
    const entries: LogEntry[] = [
      { ts: "2026-01-01T00:00:00Z", level: "error", message: "任务执行失败", detail: {} },
      {
        ts: "2026-01-01T00:00:01Z",
        level: "error",
        message: "主包解压失败，任务失败",
        detail: { error: "解压总量超限：允许解压总量 2.8 GB" },
      },
    ];

    assert.equal(
      latestTaskFailure(entries),
      "主包解压失败，任务失败：解压总量超限：允许解压总量 2.8 GB",
    );
  });

  it("没有错误日志时返回空值", () => {
    const entries: LogEntry[] = [
      { ts: "2026-01-01T00:00:00Z", level: "info", message: "任务开始执行", detail: {} },
    ];

    assert.equal(latestTaskFailure(entries), null);
  });
});

describe("getTaskFailureStage", () => {
  it("数据准备失败归入数据准备阶段", () => {
    const task = {
      status: "failed",
      preparation: {
        status: "fail",
        items: [{ category: "main", status: "fail", total_count: 1, extracted_count: 0, issues: [] }],
        total: 1,
        success_count: 0,
        warning_count: 0,
        failure_count: 1,
        skip_count: 0,
      },
    } as unknown as Pick<TaskSummary, "status" | "preparation">;

    assert.equal(getTaskFailureStage(task), "数据准备");
  });

  it("其余失败归入任务执行阶段，非失败任务返回空值", () => {
    assert.equal(
      getTaskFailureStage({ status: "failed", preparation: null } as Pick<TaskSummary, "status" | "preparation">),
      "任务执行",
    );
    assert.equal(
      getTaskFailureStage({ status: "completed", preparation: null } as Pick<TaskSummary, "status" | "preparation">),
      null,
    );
  });
});
