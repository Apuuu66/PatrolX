import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  applyTaskDetailFilters,
  parseTaskDetailFilters,
  type TaskDetailFilterChanges,
} from "../utils/taskDetailFilters.ts";

export function useTaskDetailFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseTaskDetailFilters(searchParams), [searchParams]);

  const updateFilters = useCallback(
    (changes: TaskDetailFilterChanges) => {
      setSearchParams(applyTaskDetailFilters(searchParams, changes), { replace: true });
    },
    [searchParams, setSearchParams],
  );

  return { filters, updateFilters };
}
