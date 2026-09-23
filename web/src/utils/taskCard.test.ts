import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { DictsResponse, TaskSummary } from "../api/http";
import { formatTaskDuration, getTaskMetadataTags } from "./taskCard.ts";

function makeDicts(): DictsResponse {
  return {
    province: [{ code: "js", name: "江苏" }],
    operator: [{ code: "cmcc", name: "中国移动" }],
    product: [{ code: "router", name: "路由器" }],
    version: [{ code: "v2", name: "V2" }],
  };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-1",
    name: "任务 1",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-09-13T00:00:00Z",
    completed_at: "2026-09-13T00:01:30Z",
    stats: { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1 },
    ...overrides,
  } as TaskSummary;
}

describe("formatTaskDuration", () => {
  it("formats completed task duration in compact Chinese units", () => {
    assert.equal(formatTaskDuration("2026-09-13T00:00:00Z", "2026-09-13T00:01:30Z"), "1 分 30 秒");
  });

  it("returns null while a task is running", () => {
    assert.equal(formatTaskDuration("2026-09-13T00:00:00Z", null), null);
  });

  it("returns null for invalid or reversed times", () => {
    assert.equal(formatTaskDuration("invalid", "2026-09-13T00:01:30Z"), null);
    assert.equal(formatTaskDuration("2026-09-13T00:01:30Z", "2026-09-13T00:00:00Z"), null);
  });
});

describe("getTaskMetadataTags", () => {
  it("maps metadata codes to labeled values and includes device id", () => {
    const tags = getTaskMetadataTags(
      makeTask({
        customer_province: "js",
        customer_operator: "cmcc",
        customer_product: "router",
        customer_version: "v2",
        device_id: "dev-001",
      }),
      makeDicts(),
    );

    assert.deepEqual(tags, [
      { key: "province", label: "省份", value: "江苏" },
      { key: "operator", label: "运营商", value: "中国移动" },
      { key: "product", label: "产品形态", value: "路由器" },
      { key: "version", label: "版本", value: "V2" },
      { key: "device_id", label: "设备 ID", value: "dev-001" },
    ]);
  });

  it("uses raw code and trims device id when dictionaries are unavailable", () => {
    const tags = getTaskMetadataTags(
      makeTask({ customer_province: "unknown", device_id: "  dev-002  " }),
      null,
    );
    assert.deepEqual(tags, [
      { key: "province", label: "省份", value: "unknown" },
      { key: "device_id", label: "设备 ID", value: "dev-002" },
    ]);
  });
});
