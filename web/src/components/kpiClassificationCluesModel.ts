import type { KpiClueStatusV4 } from "../api/http";

const ACTIONABLE_CLUE_STATUSES: KpiClueStatusV4[] = ["unclassified", "unregistered", "ambiguous"];

export function hasActionableKpiClassificationClues(
  summary: Partial<Record<KpiClueStatusV4, number>> | undefined,
): boolean {
  return ACTIONABLE_CLUE_STATUSES.some((status) => (summary?.[status] ?? 0) > 0);
}
