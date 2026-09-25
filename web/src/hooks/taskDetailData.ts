import type {
  InspectorInfo,
  LogEntry,
  SystemInspection,
  TaskSummary,
} from "../api/http.ts";
import { api } from "../api/http.ts";

export type ResourceState<T> =
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

export interface TaskDetailData {
  task: ResourceState<TaskSummary>;
  system: ResourceState<SystemInspection | null>;
  logs: ResourceState<LogEntry[]>;
  hiddenRuleCodes: Set<string>;
}

export interface TaskDetailDataDependencies {
  getTask: (taskId: string) => Promise<TaskSummary>;
  getSystem: (taskId: string) => Promise<SystemInspection>;
  listInspectors: () => Promise<InspectorInfo[]>;
  getLogs: (taskId: string) => Promise<{ entries: LogEntry[] } | null>;
}

const defaultDependencies: TaskDetailDataDependencies = {
  getTask: (taskId) => api.getTask(taskId),
  getSystem: (taskId) => api.getSystem(taskId, true),
  listInspectors: () => api.listInspectors(undefined, true),
  getLogs: (taskId) => api.getTaskLogs(taskId),
};

function toErrorState(error: unknown): { status: "error"; message: string } {
  return {
    status: "error",
    message: error instanceof Error ? error.message : "加载失败",
  };
}

export async function loadTaskDetailData(
  taskId: string,
  dependencies: TaskDetailDataDependencies = defaultDependencies,
): Promise<TaskDetailData> {
  const [taskResult, systemResult, inspectorsResult, logsResult] = await Promise.allSettled([
    dependencies.getTask(taskId),
    dependencies.getSystem(taskId),
    dependencies.listInspectors(),
    dependencies.getLogs(taskId),
  ]);

  const task =
    taskResult.status === "fulfilled"
      ? { status: "ready" as const, data: taskResult.value }
      : toErrorState(taskResult.reason);

  const system =
    systemResult.status === "fulfilled"
      ? { status: "ready" as const, data: systemResult.value }
      : toErrorState(systemResult.reason);

  const hiddenRuleCodes = new Set(
    inspectorsResult.status === "fulfilled"
      ? inspectorsResult.value.filter((inspector) => inspector.hidden).map((inspector) => inspector.code)
      : [],
  );

  const logs =
    logsResult.status === "fulfilled"
      ? { status: "ready" as const, data: logsResult.value?.entries ?? [] }
      : toErrorState(logsResult.reason);

  return { task, system, logs, hiddenRuleCodes };
}
