import assert from "node:assert/strict";
import test from "node:test";

import { RESULT_STATUS_META, TASK_STATUS_LABELS } from "./statusLabels.ts";

test("maps task statuses to Chinese labels", () => {
  assert.deepEqual(TASK_STATUS_LABELS, {
    pending: "排队中",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
  });
});

test("uses semantic result labels and colors", () => {
  assert.deepEqual(
    RESULT_STATUS_META.map(({ key, label }) => ({ key, label })),
    [
      { key: "pass", label: "通过" },
      { key: "warn", label: "告警" },
      { key: "fail", label: "失败" },
      { key: "error", label: "异常" },
      { key: "skip", label: "跳过" },
    ],
  );
  assert.equal(RESULT_STATUS_META.find((item) => item.key === "pass")?.color, "#52c41a");
});
