import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { OverviewSummary } from "../api/http";
import {
  OVERVIEW_METRICS,
  getOverviewDistribution,
  getOverviewMetricValue,
} from "./taskOverview.ts";

function makeOverview(overrides: Partial<OverviewSummary> = {}): OverviewSummary {
  return {
    task_count: 7,
    registered_rule_count: 12,
    rule_result_count: 30,
    finding_count: 5,
    status_counts: { total: 30, pass: 20, warn: 4, fail: 3, error: 1, skip: 2 },
    ...overrides,
  };
}

describe("OVERVIEW_METRICS", () => {
  it("覆盖四项指标并给出统计范围", () => {
    assert.deepEqual(
      OVERVIEW_METRICS.map((metric) => metric.key),
      ["task_count", "registered_rule_count", "rule_result_count", "finding_count"],
    );
    for (const metric of OVERVIEW_METRICS) {
      assert.ok(metric.label.length > 0);
      assert.ok(metric.description.length > 0);
      assert.equal(metric.scope, "统计范围：全部任务");
    }
  });

  it("规则结果与发现问题数的口径说明可以互相区分", () => {
    const ruleResult = OVERVIEW_METRICS.find((metric) => metric.key === "rule_result_count");
    const finding = OVERVIEW_METRICS.find((metric) => metric.key === "finding_count");

    assert.match(finding?.description ?? "", /一条规则可产生多条发现/);
    assert.match(ruleResult?.description ?? "", /五态之和|跳过/);
    assert.notEqual(ruleResult?.description, finding?.description);
  });
});

describe("getOverviewMetricValue", () => {
  it("读取既有 OverviewSummary 字段并在缺失时返回 null", () => {
    const overview = makeOverview();
    assert.equal(getOverviewMetricValue(overview, "finding_count"), 5);
    assert.equal(getOverviewMetricValue(null, "finding_count"), null);
  });
});

describe("getOverviewDistribution", () => {
  it("返回五态计数，供概览条弱化渲染", () => {
    assert.deepEqual(getOverviewDistribution(makeOverview()), {
      pass: 20,
      warn: 4,
      fail: 3,
      error: 1,
      skip: 2,
    });
    assert.equal(getOverviewDistribution(null), null);
  });
});
