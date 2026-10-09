import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { STATUS_TEXT_COLORS, contrastRatio, getStatusTextColor } from "./statusTextColors.ts";

const WHITE = "#ffffff";

describe("statusTextColors", () => {
  it("为五态提供文本安全色，并保持与填充色区分", () => {
    // 与 research R13 的色相族一致，但为满足 AA 4.5:1 采用更深的 gold-8 / green-8。
    assert.equal(STATUS_TEXT_COLORS.warn, "#874d00");
    assert.equal(STATUS_TEXT_COLORS.pass, "#237804");
    assert.equal(STATUS_TEXT_COLORS.skip, "#0958d9");
    assert.equal(STATUS_TEXT_COLORS.error, "#595959");
    assert.equal(STATUS_TEXT_COLORS.fail, "#cf1322");
  });

  it("每个文本状态色在白底上的对比度不低于 4.5:1", () => {
    for (const [status, color] of Object.entries(STATUS_TEXT_COLORS)) {
      const ratio = contrastRatio(color, WHITE);
      assert.ok(ratio >= 4.5, `${status} ${color} 对比度 ${ratio.toFixed(2)} 低于 4.5:1`);
    }
  });

  it("contrastRatio 对黑白极值给出 21:1", () => {
    assert.equal(Math.round(contrastRatio("#000000", "#ffffff")), 21);
    assert.equal(contrastRatio("#ffffff", "#ffffff"), 1);
  });

  it("未知状态回退到给定兜底色", () => {
    assert.equal(getStatusTextColor("unknown"), "inherit");
    assert.equal(getStatusTextColor("unknown", "#000000"), "#000000");
    assert.equal(getStatusTextColor("warn"), STATUS_TEXT_COLORS.warn);
  });
});
