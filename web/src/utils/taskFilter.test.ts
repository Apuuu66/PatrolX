import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { RuleResult, RuleStatus } from "../api/http";
import { countByStatus, filterByStatus, toggleStatusFilter } from "./taskFilter.ts";

function makeRule(code: string, status: RuleStatus, category = "config"): RuleResult {
  return {
    code,
    name: code,
    category: category as RuleResult["category"],
    priority: 1,
    execution_order: 0,
    status,
    severity: "medium",
  };
}

describe("countByStatus", () => {
  it("按可见规则列表统计各状态数量", () => {
    const rules = [
      makeRule("a", "pass"),
      makeRule("b", "pass"),
      makeRule("c", "warn"),
      makeRule("d", "fail"),
      makeRule("e", "skip"),
      makeRule("f", "error"),
    ];
    const counts = countByStatus(rules);
    assert.equal(counts.pass, 2);
    assert.equal(counts.warn, 1);
    assert.equal(counts.fail, 1);
    assert.equal(counts.error, 1);
    assert.equal(counts.skip, 1);
  });

  it("空列表返回全零", () => {
    const counts = countByStatus([]);
    for (const key of Object.values(counts)) {
      assert.equal(key, 0);
    }
  });
});

describe("filterByStatus", () => {
  const rules = [
    makeRule("a", "pass"),
    makeRule("b", "warn", "log"),
    makeRule("c", "warn", "config"),
    makeRule("d", "fail"),
  ];

  it("null 返回全量列表", () => {
    assert.equal(filterByStatus(rules, null).length, 4);
  });

  it("按状态过滤只保留匹配规则", () => {
    const result = filterByStatus(rules, "warn");
    assert.equal(result.length, 2);
    assert.deepEqual(result.map((r) => r.code), ["b", "c"]);
  });

  it("过滤后无匹配返回空列表", () => {
    assert.equal(filterByStatus(rules, "error").length, 0);
  });
});

describe("toggleStatusFilter", () => {
  it("点击未激活状态时设置过滤", () => {
    assert.equal(toggleStatusFilter(null, "warn"), "warn");
    assert.equal(toggleStatusFilter("pass", "warn"), "warn");
  });

  it("点击已激活状态时取消过滤", () => {
    assert.equal(toggleStatusFilter("warn", "warn"), null);
  });
});
