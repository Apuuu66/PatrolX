import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { RuleResult, RuleStatus } from "../api/http";
import {
  filterRuleResults,
  getAttentionDisplayRules,
  getRuleCategoryCounts,
  getRuleCategoryOptions,
  sortRuleResults,
  sortRuleResultsByFocus,
} from "./ruleResults.ts";

type RuleOverrides = Partial<Pick<RuleResult, "code" | "name" | "category" | "status" | "severity" | "duration_ms">>;

function makeRule(code: string, overrides: RuleOverrides = {}): RuleResult {
  return {
    code,
    name: code,
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "pass",
    severity: "medium",
    ...overrides,
  } as RuleResult;
}

describe("filterRuleResults", () => {
  const rules = [
    makeRule("log.a", { name: "日志错误", category: "log", status: "fail" }),
    makeRule("log.b", { name: "日志访问", category: "log", status: "pass" }),
    makeRule("kpi.a", { name: "KPI 检查", category: "kpi", status: "warn" }),
  ];

  it("按名称或编码不区分大小写搜索", () => {
    assert.deepEqual(filterRuleResults(rules, { search: "KPI" }).map((rule) => rule.code), ["kpi.a"]);
    assert.deepEqual(filterRuleResults(rules, { search: "LOG.B" }).map((rule) => rule.code), ["log.b"]);
  });

  it("空条件返回原列表", () => {
    assert.equal(filterRuleResults(rules, {}), rules);
  });
});

describe("sortRuleResults", () => {
  const rules = [
    makeRule("a", { severity: "low", status: "fail" }),
    makeRule("b", { severity: "high", status: "pass" }),
    makeRule("c", { severity: "medium", status: "warn" }),
  ];

  it("严重度优先时先按状态再按严重度排序", () => {
    const result = sortRuleResults(rules, "severity");
    assert.deepEqual(result.map((rule) => rule.code), ["a", "c", "b"]);
  });

  it("默认排序保持原顺序", () => {
    assert.deepEqual(sortRuleResults(rules, "default").map((rule) => rule.code), ["a", "b", "c"]);
  });
});

describe("getRuleCategoryCounts", () => {
  it("按首次出现顺序统计分类", () => {
    const counts = getRuleCategoryCounts([
      makeRule("a", { category: "log" }),
      makeRule("b", { category: "log" }),
      makeRule("c", { category: "kpi" }),
    ]);

    assert.deepEqual(counts, [
      { value: "log", count: 2 },
      { value: "kpi", count: 1 },
    ]);
  });
});

describe("getRuleCategoryOptions", () => {
  const rules = [
    makeRule("config.a", { category: "config", status: "pass" }),
    makeRule("log.a", { category: "log", status: "fail" }),
    makeRule("kpi.a", { category: "kpi", status: "warn" }),
  ];

  it("组合筛选后保留全部分类并显示匹配数量", () => {
    const filtered = rules.filter((rule) => rule.status === "fail");
    const result = getRuleCategoryOptions(rules, filtered);
    assert.deepEqual(result, [
      { value: "config", count: 0 },
      { value: "log", count: 1 },
      { value: "kpi", count: 0 },
    ]);
  });
});

describe("sortRuleResultsByFocus", () => {
  const rules = [
    makeRule("config.a", { category: "config", severity: "low", status: "pass" }),
    makeRule("log.a", { category: "log", severity: "high", status: "fail" }),
    makeRule("kpi.a", { category: "kpi", severity: "medium", status: "warn" }),
    makeRule("log.b", { category: "log", severity: "low", status: "pass" }),
  ];

  it("聚焦分类置顶且不隐藏其他分类", () => {
    const result = sortRuleResultsByFocus(rules, "log", "default");
    assert.deepEqual(result.map((rule) => rule.category), ["log", "log", "config", "kpi"]);
    assert.deepEqual(result.map((rule) => rule.code), ["log.a", "log.b", "config.a", "kpi.a"]);
  });

  it("聚焦分类内部仍支持严重度优先排序", () => {
    const result = sortRuleResultsByFocus(rules, "log", "severity");
    assert.deepEqual(result.map((rule) => rule.code), ["log.a", "log.b", "kpi.a", "config.a"]);
  });
});

describe("getAttentionDisplayRules", () => {
  it("只保留需要关注的规则并按严重程度排序", () => {
    const rules = [
      { code: "warn.a", status: "warn", severity: "medium" },
      { code: "pass.a", status: "pass", severity: "low" },
      { code: "fail.b", status: "fail", severity: "high" },
      { code: "error.a", status: "error", severity: "low" },
    ] as any;

    assert.deepEqual(
      getAttentionDisplayRules(rules, 5).rules.map((rule) => rule.code),
      ["fail.b", "warn.a", "error.a"],
    );
  });

  it("超过展示上限时给出剩余数量", () => {
    const rules = Array.from({ length: 7 }, (_, index) => ({
      code: `fail.${index}`,
      status: "fail",
      severity: "high",
    })) as any;

    const result = getAttentionDisplayRules(rules, 5);
    assert.equal(result.rules.length, 5);
    assert.equal(result.hiddenCount, 2);
  });
});
