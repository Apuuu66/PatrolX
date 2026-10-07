import { useCallback, useEffect, useRef, useState } from "react";
import { usePolling } from "./usePolling";
import {
  loadTaskDetailData,
  type TaskDetailData,
  type TaskDetailLoadScope,
} from "./taskDetailData";

export function useTaskDetailData(taskId: string) {
  const [data, setData] = useState<TaskDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const dataRef = useRef<TaskDetailData | null>(null);

  const load = useCallback(
    async (scope: TaskDetailLoadScope = "full") => {
      const previous = dataRef.current;
      if (scope === "full") setLoading(true);
      const next = await loadTaskDetailData(taskId, undefined, { scope, previous });
      dataRef.current = next;
      setData(next);
      if (scope === "full") setLoading(false);
      const currentStatus = next.task.status === "ready" ? next.task.data.status : null;
      const previousStatus = previous?.task.status === "ready" ? previous.task.data.status : null;
      if (
        scope === "refresh" &&
        previousStatus === currentStatus &&
        (currentStatus === "pending" || currentStatus === "running")
      ) {
        return;
      }
      if (scope === "refresh" && (currentStatus === "completed" || currentStatus === "failed")) {
        await load("full");
      }
    },
    [taskId],
  );

  useEffect(() => {
    void load("full");
  }, [load]);

  const refresh = useCallback(() => {
    void load("refresh");
  }, [load]);
  const task = data?.task.status === "ready" ? data.task.data : null;
  const busy = task?.status === "pending" || task?.status === "running";
  usePolling(refresh, 2000, !!busy);

  return { data, loading, busy, reload: load };
}
