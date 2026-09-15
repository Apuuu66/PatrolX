import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DataPreparation, PreparationItem } from "../api/http";
import {
  formatPreparationIssuePath,
  getPreparationDisplay,
  truncateMiddle,
} from "./preparationDisplay.ts";

function makeItem(code: string, category: string, status: PreparationItem["status"], issueCount = 0): PreparationItem {
  return {
    code,
    name: `${category} 分类解压`,
    category,
    status,
    summary: status === "pass" ? "解压完成" : "存在异常",
    extracted_count: 3,
    total_count: 5,
    issues: Array.from({ length: issueCount }, (_, index) => ({
      type: "failed",
      source: `source-${index}.log`,
      target: `logs/category/file-${index}.log`,
      reason: `原因 ${index + 1}`,
      path_length: 280,
      path_limit: 260,
    })),
  };
}

function makePreparation(items: PreparationItem[]): DataPreparation {
  return {
    status: "fail",
    items,
    total: items.length,
    success_count: items.filter((item) => item.status === "pass").length,
    warning_count: items.filter((item) => item.status === "warn").length,
    failure_count: items.filter((item) => item.status === "fail").length,
    skip_count: items.filter((item) => item.status === "skip").length,
  };
}

describe("getPreparationDisplay", () => {
  const preparation = makePreparation([
    makeItem("extract.warn", "logs", "warn", 2),
    makeItem("extract.fail", "kpi", "fail", 3),
    makeItem("extract.error", "traffic", "error", 2),
    makeItem("extract.pass", "main", "pass"),
    makeItem("extract.skip", "config", "skip"),
  ]);

  it("折叠摘要只输出异常分类、问题数量和正常分类数量", () => {
    const display = getPreparationDisplay(preparation);
    assert.equal(display.hasAbnormal, true);
    assert.equal(display.issueCount, 7);
    assert.equal(display.summary, "⚠ 3 类异常 · 7 个问题 · 正常 2 类");
  });

  it("展开后默认只显示前 3 个异常分类", () => {
    const display = getPreparationDisplay(preparation);
    assert.deepEqual(display.visibleAbnormalItems.map((item) => item.category), ["logs", "kpi", "traffic"]);
    assert.equal(display.hiddenAbnormalCount, 0);
  });

  it("点击展开全部后返回全部异常分类", () => {
    const manyItems = ["a", "b", "c", "d", "e"].map((category) =>
      makeItem(`extract.${category}`, category, "warn", 1),
    );
    const display = getPreparationDisplay(makePreparation(manyItems), true);
    assert.equal(display.visibleAbnormalItems.length, 5);
    assert.equal(display.hiddenAbnormalCount, 0);
  });

  it("正常分类合并为一行分类名", () => {
    const display = getPreparationDisplay(preparation);
    assert.equal(display.normalSummary, "正常：主包 · 配置");
  });

  it("没有异常时输出正常摘要", () => {
    const display = getPreparationDisplay(
      makePreparation([makeItem("extract.main", "main", "pass")]),
    );
    assert.equal(display.hasAbnormal, false);
    assert.equal(display.issueCount, 0);
    assert.equal(display.summary, "✓ 正常 1 类");
  });
});

describe("formatPreparationIssuePath", () => {
  it("展示来源、目标和长度限制", () => {
    const text = formatPreparationIssuePath({
      type: "failed",
      source: "a.log",
      target: "logs/a.log",
      reason: "失败",
      path_length: 280,
      path_limit: 260,
    });
    assert.equal(text, "a.log → logs/a.log · 长度 280/260");
  });

  it("缺失字段显示占位符", () => {
    const text = formatPreparationIssuePath({ type: "failed", reason: "失败" });
    assert.equal(text, "- → -");
  });
});

describe("truncateMiddle", () => {
  it("短路径保持原样", () => {
    assert.equal(truncateMiddle("logs/a.log"), "logs/a.log");
  });

  it("长路径中间截断并限制长度", () => {
    const value = `${"a".repeat(50)}/middle/${"b".repeat(50)}`;
    const result = truncateMiddle(value, 40);
    assert.equal(result.length, 40);
    assert.ok(result.startsWith("aaaaaaaaaa"));
    assert.ok(result.includes("…"));
    assert.ok(result.endsWith("bbbbbbbbbb"));
  });
});
