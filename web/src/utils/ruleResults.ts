import type { RuleResult } from "../api/http";

export type RuleSortMode = "default" | "severity";

export interface RuleSearchOptions {
  search?: string;
}

const STATUS_WEIGHT: Record<RuleResult["status"], number> = {
  fail: 0,
  warn: 1,
  error: 2,
  pass: 3,
  skip: 4,
};

const SEVERITY_WEIGHT: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

export function filterRuleResults(rules: RuleResult[], options: RuleSearchOptions): RuleResult[] {
  const search = options.search?.trim().toLowerCase();

  if (!search) return rules;

  return rules.filter((rule) => {
    return rule.name.toLowerCase().includes(search) || rule.code.toLowerCase().includes(search);
  });
}

export function sortRuleResultsByFocus(
  rules: RuleResult[],
  focusCategory: string | null,
  mode: RuleSortMode,
): RuleResult[] {
  if (!focusCategory) return sortRuleResults(rules, mode);

  const focused = sortRuleResults(
    rules.filter((rule) => rule.category === focusCategory),
    mode,
  );
  const others = sortRuleResults(
    rules.filter((rule) => rule.category !== focusCategory),
    mode,
  );
  return [...focused, ...others];
}

export function sortRuleResults(rules: RuleResult[], mode: RuleSortMode): RuleResult[] {
  if (mode === "default") return [...rules];

  return [...rules].sort((left, right) => {
    const statusDelta = STATUS_WEIGHT[left.status] - STATUS_WEIGHT[right.status];
    if (statusDelta !== 0) return statusDelta;

    const severityDelta =
      (SEVERITY_WEIGHT[left.severity] ?? Number.MAX_SAFE_INTEGER) -
      (SEVERITY_WEIGHT[right.severity] ?? Number.MAX_SAFE_INTEGER);
    if (severityDelta !== 0) return severityDelta;

    return left.code.localeCompare(right.code);
  });
}

export interface RuleCategoryCount {
  value: string;
  count: number;
}

export function getRuleCategoryOptions(
  rules: RuleResult[],
  filteredRules: RuleResult[],
): RuleCategoryCount[] {
  const filteredCounts = new Map(
    getRuleCategoryCounts(filteredRules).map((category) => [category.value, category.count]),
  );

  return getRuleCategoryCounts(rules).map(({ value }) => ({
    value,
    count: filteredCounts.get(value) ?? 0,
  }));
}

export function getRuleCategoryCounts(rules: RuleResult[]): RuleCategoryCount[] {
  const counts = new Map<string, number>();
  for (const rule of rules) {
    counts.set(rule.category, (counts.get(rule.category) ?? 0) + 1);
  }
  return Array.from(counts, ([value, count]) => ({ value, count }));
}

const ATTENTION_STATUS_WEIGHT: Record<RuleResult["status"], number> = {
  fail: 0,
  warn: 1,
  error: 2,
  pass: 9,
  skip: 9,
};

export interface AttentionDisplayRules {
  rules: RuleResult[];
  hiddenCount: number;
}

export function getAttentionDisplayRules(
  rules: RuleResult[],
  limit = 5,
): AttentionDisplayRules {
  const attentionRules = rules
    .filter((rule) => rule.status === "fail" || rule.status === "warn" || rule.status === "error")
    .sort(
      (left, right) =>
        ATTENTION_STATUS_WEIGHT[left.status] - ATTENTION_STATUS_WEIGHT[right.status],
    );

  return {
    rules: attentionRules.slice(0, limit),
    hiddenCount: Math.max(0, attentionRules.length - limit),
  };
}
