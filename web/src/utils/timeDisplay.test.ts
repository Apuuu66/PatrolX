import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  TABULAR_NUMERIC_CLASS,
  formatFullTime,
  formatRelativeTime,
  getRelativeTimeDisplay,
} from "./timeDisplay.ts";

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
