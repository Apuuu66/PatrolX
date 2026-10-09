import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

import type { RuleResult } from "../../api/http";
import { RuleBrowser } from "./RuleBrowser";

function makeRule(overrides: Partial<RuleResult>): RuleResult {
  return {
    code: "config.a",
    name: "配置通过",
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "pass",
    severity: "low",
    summary: "通过",
    ...overrides,
  } as RuleResult;
}

const rules: RuleResult[] = [
  makeRule({ code: "config.a", name: "配置通过" }),
  makeRule({ code: "log.a", name: "日志访问", category: "log", execution_order: 1 }),
  makeRule({
    code: "log.b",
    name: "日志错误",
    category: "log",
    execution_order: 2,
    status: "fail",
    severity: "high",
    summary: "命中错误",
  }),
];

function renderBrowser(props: Partial<Parameters<typeof RuleBrowser>[0]> = {}) {
  return render(
    <App>
      <RuleBrowser
        sortedRules={rules}
        attentionRuleCodes={["log.b"]}
        statusFilter={null}
        search=""
        sort="default"
        category={null}
        onSearchChange={() => {}}
        onSortChange={() => {}}
        onCategoryChange={() => {}}
        onOpenRule={() => {}}
        onRerunRule={() => {}}
        {...props}
      />
    </App>,
  );
}

describe("RuleBrowser", () => {
  it("默认排除已在重点关注中的规则并提示数量", () => {
    renderBrowser();

    expect(screen.getByText("配置通过")).toBeDefined();
    expect(screen.getByText("日志访问")).toBeDefined();
    expect(screen.queryByText("日志错误")).toBeNull();
    expect(screen.getByTestId("rule-browser-dedupe").textContent).toContain(
      "另有 1 条已在上方重点关注",
    );
  });

  it("显示全部后恢复完整列表并可恢复默认", async () => {
    renderBrowser();

    await userEvent.click(screen.getByTestId("rule-browser-show-all"));

    expect(await screen.findByText("日志错误")).toBeDefined();
    expect(screen.queryByTestId("rule-browser-dedupe")).toBeNull();

    await userEvent.click(screen.getByTestId("rule-browser-hide-all"));
    expect(screen.queryByText("日志错误")).toBeNull();
    expect(screen.getByTestId("rule-browser-dedupe")).toBeDefined();
  });

  it("搜索命中被排除规则时自动纳入结果", () => {
    // 父级先按搜索过滤，RuleBrowser 在搜索态不做去重（R7）
    renderBrowser({ search: "log.b", sortedRules: [rules[2]] });

    expect(screen.getByText("日志错误")).toBeDefined();
    expect(screen.queryByTestId("rule-browser-dedupe")).toBeNull();
  });

  it("状态筛选生效时保持既有筛选语义", () => {
    renderBrowser({ statusFilter: "fail", sortedRules: [rules[2]] });

    expect(screen.getByText("日志错误")).toBeDefined();
    expect(screen.queryByTestId("rule-browser-dedupe")).toBeNull();
  });

  it("没有重点关注规则时不显示去重提示", () => {
    renderBrowser({ attentionRuleCodes: [] });

    expect(screen.queryByTestId("rule-browser-dedupe")).toBeNull();
    expect(screen.getByText("日志错误")).toBeDefined();
  });

  it("点击规则名回调打开规则详情", async () => {
    const onOpenRule = vi.fn();
    renderBrowser({ onOpenRule });

    await userEvent.click(screen.getByText("配置通过"));
    expect(onOpenRule).toHaveBeenCalledWith("config.a");
  });
});
