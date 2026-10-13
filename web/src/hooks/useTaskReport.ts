import { useCallback, useEffect, useState } from "react";
import { api } from "../api/http";
import { toResourceError, type ResourceErrorState } from "../utils/sceneError";

export type TaskReportState =
  | { status: "loading" }
  | { status: "ready"; html: string }
  | { status: "error"; error: ResourceErrorState };

/** 读取巡检报告 HTML；现场已清理等失败以结构化错误态返回，不与空白报告混淆（FR-011）。 */
export function useTaskReport(taskId: string) {
  const [state, setState] = useState<TaskReportState>({ status: "loading" });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setState((current) => (current.status === "ready" ? current : { status: "loading" }));
    setLoading(true);
    try {
      const html = await api.getTaskReportHtml(taskId);
      setState({ status: "ready", html });
    } catch (error) {
      setState({ status: "error", error: toResourceError(error, "报告加载失败") });
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { state, loading, reload: load };
}
