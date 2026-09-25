import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getRuleCategoryLabel, getRuleCategoryOptionsText } from "./ruleCategories.ts";

describe("ruleCategories", () => {
  it("返回已知分类的中文标签", () => {
    assert.equal(getRuleCategoryLabel("log"), "日志");
    assert.equal(getRuleCategoryLabel("kpi"), "KPI");
  });

  it("未知分类回退到原始值", () => {
    assert.equal(getRuleCategoryLabel("custom"), "custom");
  });

  it("分类标签和数量使用空格分隔", () => {
    assert.equal(getRuleCategoryOptionsText("log", 2), "日志 2");
    assert.equal(getRuleCategoryOptionsText("custom", 0), "custom 0");
  });
});
