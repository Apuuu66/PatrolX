import { useCallback, useEffect, useState } from "react";
import { usePolling } from "./usePolling";
import { loadTaskDetailData, type TaskDetailData } from "./taskDetailData";

export function useTaskDetailData(taskId: string) {
  const [data, setData] = useState<TaskDetailData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const next = await loadTaskDetailData(taskId);
    setData(next);
    setLoading(false);
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const task = data?.task.status === "ready" ? data.task.data : null;
  const busy = task?.status === "pending" || task?.status === "running";
  usePolling(load, 2000, !!busy);

  return { data, loading, busy, reload: load };
}
