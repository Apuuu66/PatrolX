import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  TABULAR_NUMERIC_CLASS,
  formatDurationMs,
  formatFullTime,
  formatRelativeTime,
  getRelativeTimeDisplay,
} from "./timeDisplay.ts";
import { formatTaskDuration } from "./taskCard.ts";

describe("timeDisplay", () => {
  it("使用中文相对时间表达过去时间", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    assert.match(formatRelativeTime(threeHoursAgo), /小时前/);
  });

  it("空值与非法时间返回占位符而不抛错", () => {
    assert.equal(formatRelativeTime(null), "-");
    assert.equal(formatRelativeTime(undefined), "-");
    assert.equal(formatRelativeTime(""), "-");
    assert.equal(formatRelativeTime("not-a-time"), "-");
    assert.equal(formatFullTime("not-a-time"), "-");
  });

  it("完整时间使用秒级精度并作为 Tooltip 文案", () => {
    const full = formatFullTime("2026-10-10T08:30:00Z");
    assert.match(full, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

    const display = getRelativeTimeDisplay("2026-10-10T08:30:00Z");
    assert.equal(display.title, full);
    assert.ok(display.text.length > 0);
  });

  it("相对时间展示接口在空值时给出空 Tooltip", () => {
    const display = getRelativeTimeDisplay(null);
    assert.equal(display.text, "-");
    assert.equal(display.title, "");
  });

  it("导出等宽数字类名常量", () => {
    assert.equal(TABULAR_NUMERIC_CLASS, "tabular-nums");
  });
});

describe("formatDurationMs", () => {
  it("按紧凑中文单位格式化任务时长", () => {
    assert.equal(formatDurationMs(950), "<1 秒");
    assert.equal(formatDurationMs(59000), "59 秒");
    assert.equal(formatDurationMs(95_000), "1 分 35 秒");
    assert.equal(formatDurationMs(3 * 3600_000 + 20 * 60_000), "3 小时 20 分钟");
    assert.equal(formatDurationMs(2 * 86400_000 + 5 * 3600_000), "2 天 5 小时");
  });

  it("空值、非法值与负值返回 null 而不是误导性数值", () => {
    assert.equal(formatDurationMs(null), null);
    assert.equal(formatDurationMs(undefined), null);
    assert.equal(formatDurationMs(Number.NaN), null);
    assert.equal(formatDurationMs(-1), null);
  });

  it("与 formatTaskDuration 共用同一格式口径", () => {
    assert.equal(formatDurationMs(90_000), formatTaskDuration("2026-09-13T00:00:00Z", "2026-09-13T00:01:30Z"));
  });
});
