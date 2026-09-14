import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { LogEntry } from "../api/http";
import { latestTaskFailure } from "./taskFailure.ts";

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
