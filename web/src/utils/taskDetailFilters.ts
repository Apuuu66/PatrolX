import type { RuleStatus } from "../api/http";
import { STATUS_KEYS, type StatusFilter } from "./taskFilter.ts";
import type { RuleSortMode } from "./ruleResults.ts";

export type TaskDetailTab = "rules" | "logs" | "report";

export interface TaskDetailFilterState {
  tab: TaskDetailTab;
  status: StatusFilter;
  category: string | null;
  search: string;
  sort: RuleSortMode;
}

export interface TaskDetailFilterChanges {
  tab?: TaskDetailTab;
  status?: StatusFilter;
  category?: string | null;
  search?: string;
  sort?: RuleSortMode;
}

const TABS: TaskDetailTab[] = ["rules", "logs", "report"];

export function parseTaskDetailFilters(
  searchParams: URLSearchParams,
): TaskDetailFilterState {
  const view = searchParams.get("view") as TaskDetailTab | null;
  const status = searchParams.get("status") as RuleStatus | null;
  const sort = searchParams.get("sort") as RuleSortMode | null;

  return {
    tab: view && TABS.includes(view) ? view : "rules",
    status: status && STATUS_KEYS.includes(status) ? status : null,
    category: searchParams.get("category") || null,
    search: searchParams.get("search") ?? "",
    sort: sort === "severity" ? "severity" : "default",
  };
}

export function applyTaskDetailFilters(
  current: URLSearchParams,
  changes: TaskDetailFilterChanges,
): URLSearchParams {
  const next = new URLSearchParams(current);
  const setValue = (key: string, value?: string | null) => {
    if (value == null || value === "") next.delete(key);
    else next.set(key, value);
  };

  if (changes.tab !== undefined) setValue("view", changes.tab === "rules" ? null : changes.tab);
  if (changes.status !== undefined) setValue("status", changes.status);
  if (changes.category !== undefined) setValue("category", changes.category);
  if (changes.search !== undefined) setValue("search", changes.search.trim());
  if (changes.sort !== undefined) setValue("sort", changes.sort === "severity" ? "severity" : null);

  return next;
}
