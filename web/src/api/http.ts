import type { components } from "./client";

export type TaskStatus = components["schemas"]["TaskStatusV2"];
export type TaskSummary = components["schemas"]["TaskSummaryV2"];
export type TaskStats = components["schemas"]["TaskStatsV2"];
export type SystemInspection = components["schemas"]["SystemInspectionV2"];
export type RuleResult = components["schemas"]["RuleResultV2"];
export type RuleStatus = components["schemas"]["RuleStatusV2"];
export type Severity = components["schemas"]["SeverityV2"];
export type InspectorInfo = components["schemas"]["InspectorInfoV2"];
export type DictsResponse = components["schemas"]["DictsResponseV2"];
export type OverviewSummary = components["schemas"]["OverviewSummaryV2"];
export type DictItem = components["schemas"]["DictItemV2"];
export type LogEntry = components["schemas"]["LogEntryV2"];

const BASE = "/api/v2";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let message = `请求失败（HTTP ${resp.status}）`;
    let code = "http_error";
    try {
      const body = (await resp.json()) as { code?: string; message?: string; detail?: string };
      if (body.code) {
        code = body.code;
        message = body.message ?? body.code;
      } else if (body.detail) {
        message = body.detail;
      }
    } catch {
      /* 非 JSON 响应 */
    }
    throw new ApiError(code, message, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export interface TaskListQuery {
  page?: number;
  page_size?: number;
  status?: TaskStatus;
}

export const api = {
  listTasks: (q: TaskListQuery = {}) => {
    const params = new URLSearchParams();
    if (q.page) params.set("page", String(q.page));
    if (q.page_size) params.set("page_size", String(q.page_size));
    if (q.status) params.set("status", q.status);
    const qs = params.toString();
    return request<{ items: TaskSummary[]; total: number; page: number; page_size: number }>(
      `${BASE}/tasks${qs ? `?${qs}` : ""}`,
    );
  },

  getTask: (taskId: string) => request<TaskSummary>(`${BASE}/tasks/${encodeURIComponent(taskId)}`),

  getOverview: () => request<OverviewSummary>(`${BASE}/overview`),

  createTask: (form: FormData) =>
    request<{ task_id: string }>(`${BASE}/tasks`, {
      method: "POST",
      body: form,
    }),

  deleteTask: (taskId: string) => request<void>(`${BASE}/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }),

  rerunTask: (taskId: string, ruleCodes?: string[]) =>
    request<{ task_id: string }>(`${BASE}/tasks/${encodeURIComponent(taskId)}/rerun`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule_codes: ruleCodes }),
    }),

  getTaskLogs: (taskId: string) => request<{ task_id: string; entries: LogEntry[] }>(`${BASE}/tasks/${encodeURIComponent(taskId)}/logs`),

  getSystem: (taskId: string) => request<SystemInspection>(`${BASE}/tasks/${encodeURIComponent(taskId)}/system`),

  getRuleResult: (taskId: string, ruleCode: string) =>
    request<RuleResult>(`${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}`),

  listInspectors: (category?: string, includeHidden = false) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (includeHidden) params.set("include_hidden", "true");
    const qs = params.toString();
    return request<InspectorInfo[]>(`${BASE}/inspectors${qs ? `?${qs}` : ""}`);
  },

  listDicts: () => request<DictsResponse>(`${BASE}/dicts`),
};

export const reportUrl = (taskId: string) => `${BASE}/tasks/${encodeURIComponent(taskId)}/report`;
