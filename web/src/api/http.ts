import type { components } from "./client";
import { clearSession, getToken } from "./auth.ts";

export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskSummary = components["schemas"]["TaskSummary"];
export type TaskStats = components["schemas"]["TaskStats"];
export type SystemInspection = components["schemas"]["SystemInspection"];
export type RuleResult = components["schemas"]["RuleResult"];
export type RuleStatus = components["schemas"]["RuleStatus"];
export type Severity = components["schemas"]["Severity"];
export type InspectorInfo = components["schemas"]["InspectorInfo"];
export type InspectorState = components["schemas"]["InspectorState"];
export type InspectorStateList = components["schemas"]["InspectorStateListResponse"];
export type MeasurementUnit = components["schemas"]["KpiMeasurementUnit"];
export type MeasurementUnitList = components["schemas"]["KpiMeasurementUnitList"];
export type MeasurementUnitImportResult = components["schemas"]["KpiMeasurementImportResult"];
export type MeasurementBinding = components["schemas"]["KpiMeasurementBinding"];
export type MeasurementBindingList = components["schemas"]["KpiMeasurementBindingList"];
export type MeasurementBindingStatus = MeasurementBinding["status"];
export type MeasurementDerived = components["schemas"]["KpiMeasurementDerived"];
export type MeasurementDerivedCreatePayload = components["schemas"]["KpiMeasurementDerivedCreateRequest"];
export interface MeasurementMetadataMetricObservation {
  object_key: string;
  row_count: number;
  valid_count: number;
  null_count: number;
  parse_error_count: number;
  zero_count: number;
  min_value: number | null;
  max_value: number | null;
  avg_value?: number | null;
  value_pattern: "normal" | "all_zero" | "unknown";
  source_rows?: { source_file: string; line_number: number; value: string }[];
}
export interface MeasurementMetadataMetric {
  metric_resource_id: string;
  raw_source_name: string;
  base_source_name?: string;
  display_unit?: string | null;
  read_status: "ok" | "missing" | "parse_error";
  value_pattern: "normal" | "all_zero" | "unknown";
  source_file?: string;
  source_files?: string[];
  observations?: MeasurementMetadataMetricObservation[];
  errors?: unknown[];
}
export interface MeasurementMetadataObject {
  object_key: string;
  row_count: number;
  valid_count: number;
  null_count: number;
  parse_error_count: number;
  zero_count: number;
  min_value: number | null;
  max_value: number | null;
  avg_value?: number | null;
  value_pattern: "normal" | "all_zero" | "unknown";
}
export interface MeasurementMetadataUnit {
  measurement_unit_id: string;
  name_zh: string;
  name_en: string;
  status: "pass" | "warn" | "fail" | "error" | "skip";
  reason?: string | null;
  file_count: number;
  object_count?: number;
  metric_coverage?: string;
  metrics: MeasurementMetadataMetric[];
  objects?: Record<string, MeasurementMetadataObject>;
  source_files?: string[];
  derived_metrics?: {
    metric_resource_id: string;
    template: string;
    status: "pass" | "warn" | "fail";
    message?: string | null;
    observations: { object_key: string; status: "pass" | "warn" | "fail"; message?: string | null; value?: number | null }[];
  }[];
}
export type DataPreparation = components["schemas"]["DataPreparation"];
export type PreparationItem = components["schemas"]["PreparationItem"];
export type PreparationIssue = components["schemas"]["PreparationIssue"];
export type DictsResponse = components["schemas"]["DictsResponse"];
export type OverviewSummary = components["schemas"]["OverviewSummary"];
export type DictItem = components["schemas"]["DictItem"];
export type LogEntry = components["schemas"]["LogEntry"];
export type User = components["schemas"]["UserV1"];
export type UserPage = components["schemas"]["UserListResponseV1"];
export type UserCreatePayload = components["schemas"]["UserCreateRequestV1"];
export type UserRolePayload = components["schemas"]["UserRoleRequestV1"];
export type UserPasswordPayload = components["schemas"]["UserPasswordRequestV1"];
export type TaskDeleteError = TaskDeleteErrorDetail;
export type RebuildMode = components["schemas"]["RebuildMode"];
export type RebuildTriggerSource = components["schemas"]["RebuildRequest"]["trigger_source"];
export type RebuildRequestPayload = Omit<components["schemas"]["RebuildRequest"], "confirmed"> & {
  confirmed: true;
};

const BASE = "/api/v2";
const KPI_V5_BASE = "/api/v5";
const AUTH_BASE = "/api/v1";

export interface TaskDeleteErrorDetail { task_id: string; locations: string[]; failed_path: string; reason: string; path_length?: number; path_limit?: number; }

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: unknown;

  constructor(code: string, message: string, status: number, detail?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const resp = await fetch(url, { ...init, headers });
  if (!resp.ok) {
    let message = `请求失败（HTTP ${resp.status}）`;
    let code = "http_error";
    let detail: unknown;
    try {
      const body = (await resp.json()) as { code?: string; message?: string; detail?: unknown };
      if (body.code) {
        code = body.code;
        message = body.message ?? body.code;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      }
      if (body.detail !== undefined) {
        detail = body.detail;
      }
    } catch {
      /* 非 JSON 响应 */
    }
    if (resp.status === 401) {
      clearSession();
      if (typeof window !== "undefined") {
        window.location.reload();
      }
    }
    throw new ApiError(code, message, resp.status, detail);
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
    return request<components["schemas"]["TaskListResponse"]>(
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

  rebuildTask: (taskId: string, payload: RebuildRequestPayload) =>
    request<{ task_id: string }>(`${BASE}/tasks/${encodeURIComponent(taskId)}/rebuild`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getTaskLogs: (taskId: string) =>
    request<{ task_id: string; entries: LogEntry[] }>(`${BASE}/tasks/${encodeURIComponent(taskId)}/logs`),

  getSystem: (taskId: string, excludeDetails = false) =>
    request<SystemInspection>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/system${excludeDetails ? "?exclude_details=true" : ""}`,
    ),

  getRuleResult: (taskId: string, ruleCode: string, excludeRecords = false) => {
    const query = excludeRecords ? "?exclude_records=true" : "";
    return request<RuleResult>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}${query}`,
    );
  },


  listInspectors: (category?: string, includeHidden = false) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (includeHidden) params.set("include_hidden", "true");
    const qs = params.toString();
    return request<InspectorInfo[]>(`${BASE}/inspectors${qs ? `?${qs}` : ""}`);
  },

  listInspectorStates: (query: { page?: number; page_size?: number; category?: string; enabled?: boolean; search?: string } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<InspectorStateList>(`${BASE}/inspector-states${qs ? `?${qs}` : ""}`);
  },

  setInspectorStateEnabled: (ruleCode: string, enabled: boolean) =>
    request<InspectorState>(`${BASE}/inspector-states/${encodeURIComponent(ruleCode)}/enabled`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),

  listDicts: () => request<DictsResponse>(`${BASE}/dicts`),
  importMeasurementUnits: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<components["schemas"]["KpiMeasurementImportResult"]>(`${KPI_V5_BASE}/kpi/measurement-units/import`, {
      method: "POST",
      body: form,
    });
  },

  listMeasurementUnits: (query: { search?: string; enabled?: boolean; page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<MeasurementUnitList>(`${KPI_V5_BASE}/kpi/measurement-units${qs ? `?${qs}` : ""}`);
  },

  setMeasurementUnitEnabled: (resourceId: string, enabled: boolean) =>
    request<{ resource_id: string; enabled: boolean }>(
      `${KPI_V5_BASE}/kpi/measurement-units/${encodeURIComponent(resourceId)}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) },
    ),

  listMeasurementBindings: (
    query: { measurement_unit_id?: string; status?: string; search?: string; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<MeasurementBindingList>(`${KPI_V5_BASE}/kpi/measurement-bindings${qs ? `?${qs}` : ""}`);
  },

  setMeasurementBindingStatus: (bindingId: number, status: "candidate" | "confirmed" | "ignored", enabled?: boolean) =>
    request<{ id: number; status: string; enabled: boolean }>(
      `${KPI_V5_BASE}/kpi/measurement-bindings/${bindingId}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, enabled }) },
    ),

  createMeasurementDerived: (payload: MeasurementDerivedCreatePayload) =>
    request<MeasurementDerived>(`${KPI_V5_BASE}/kpi/measurement-derived`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),



  listUsers: async (query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    const data = await request<UserPage>(`${AUTH_BASE}/users${qs ? `?${qs}` : ""}`);
    return { ...data, items: data.items ?? [] };
  },

  createUser: (payload: UserCreatePayload) =>
    request<User>(`${AUTH_BASE}/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateUserRole: (username: string, payload: UserRolePayload) =>
    request<User>(`${AUTH_BASE}/users/${encodeURIComponent(username)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  resetUserPassword: (username: string, payload: UserPasswordPayload) =>
    request<User>(`${AUTH_BASE}/users/${encodeURIComponent(username)}/password`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteUser: (username: string) =>
    request<void>(`${AUTH_BASE}/users/${encodeURIComponent(username)}`, { method: "DELETE" }),
};

export const reportUrl = (taskId: string) => `${BASE}/tasks/${encodeURIComponent(taskId)}/report`;
