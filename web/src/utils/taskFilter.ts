import type { RuleResult, RuleStatus } from "../api/http";

export type StatusFilter = RuleStatus | null;

const STATUS_KEYS: RuleStatus[] = ["pass", "warn", "fail", "error", "skip"];

export function countByStatus(rules: RuleResult[]): Record<RuleStatus, number> {
  const counts: Record<RuleStatus, number> = { pass: 0, warn: 0, fail: 0, error: 0, skip: 0 };
  for (const rule of rules) {
    if (STATUS_KEYS.includes(rule.status)) {
      counts[rule.status] += 1;
    }
  }
  return counts;
}

export function filterByStatus(rules: RuleResult[], filter: StatusFilter): RuleResult[] {
  if (filter === null) return rules;
  return rules.filter((r) => r.status === filter);
}

export function toggleStatusFilter(current: StatusFilter, clicked: RuleStatus): StatusFilter {
  return current === clicked ? null : clicked;
}

export { STATUS_KEYS };
