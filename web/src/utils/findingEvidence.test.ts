import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  estimateEvidenceLines,
  parseFindingEvidence,
  sliceEvidenceParts,
} from "./findingEvidence.ts";

describe("parseFindingEvidence", () => {
  it("按中文分号拆段并识别键值结构", () => {
    const view = parseFindingEvidence("分组数：3；持续时长：120 分钟；来源文件：a.log");

    assert.equal(view?.parts.length, 3);
    assert.deepEqual(
      view?.parts.map((part) => ({ label: part.label, value: part.value })),
      [
        { label: "分组数", value: "3" },
        { label: "持续时长", value: "120 分钟" },
        { label: "来源文件", value: "a.log" },
      ],
    );
  });

  it("高亮数字、次数与时长", () => {
    const view = parseFindingEvidence("告警次数 12 次，窗口 5 分钟；阈值：80%");
    const highlights = view?.parts.flatMap((part) => part.highlights) ?? [];

    assert.ok(highlights.some((item) => item.includes("12")));
    assert.ok(highlights.some((item) => item.includes("5")));
    assert.ok(highlights.some((item) => item.includes("80")));
  });

  it("超过 4 行时标记折叠", () => {
    const short = parseFindingEvidence("计数：1");
    assert.equal(short?.collapsed, false);

    const long = parseFindingEvidence(
      [
        `描述：${"很长的证据内容".repeat(6)}`,
        `描述：${"很长的证据内容".repeat(6)}`,
        `描述：${"很长的证据内容".repeat(6)}`,
        `描述：${"很长的证据内容".repeat(6)}`,
      ].join("；"),
    );
    assert.equal(long?.collapsed, true);
  });

  it("无法解析时降级为原文且不丢信息", () => {
    const raw = "自由文本证据没有分隔符也没有数值";
    const view = parseFindingEvidence(raw);

    assert.equal(view?.parts.length, 1);
    assert.equal(view?.parts[0]?.label, undefined);
    assert.equal(view?.parts[0]?.value, raw);
  });

  it("空证据返回 null 而不是空结构", () => {
    assert.equal(parseFindingEvidence(""), null);
    assert.equal(parseFindingEvidence("   "), null);
    assert.equal(parseFindingEvidence(null), null);
    assert.equal(parseFindingEvidence(undefined), null);
  });
});

describe("sliceEvidenceParts", () => {
  it("按行数预算截取前缀，至少保留一段", () => {
    const view = parseFindingEvidence(
      ["分组：1051；出现：3 次；最近清除：无；定位：pod-a；来源：a.csv"].join("；"),
    );
    const parts = view?.parts ?? [];

    const visible = sliceEvidenceParts(parts, 3);
    assert.ok(visible.length >= 1);
    assert.ok(visible.length < parts.length);
    assert.ok(estimateEvidenceLines(visible) <= 3 || visible.length === 1);
  });

  it("预算足够时返回全部分段", () => {
    const view = parseFindingEvidence("分组：1051；出现：3 次");
    const parts = view?.parts ?? [];

    assert.deepEqual(sliceEvidenceParts(parts, 10), parts);
  });

  it("非正预算至少保留一段，空输入返回空数组", () => {
    const view = parseFindingEvidence("分组：1051；出现：3 次");
    assert.equal(sliceEvidenceParts(view?.parts ?? [], 0).length, 1);
    assert.deepEqual(sliceEvidenceParts([], 4), []);
  });
});
