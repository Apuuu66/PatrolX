import type { components } from "./client";
import { clearSession, getToken } from "./auth.ts";
import { createLogger } from "../utils/logger.ts";

const logger = createLogger("api");

export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskSummary = components["schemas"]["TaskSummary"];
export type TaskStats = components["schemas"]["TaskStats"];
export type SystemInspection = components["schemas"]["SystemInspection"];
export type RuleResult = components["schemas"]["RuleResult"];
export type MeasurementMetricDetail = components["schemas"]["MeasurementMetricDetail"];
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
export type MeasurementBindingBatchConfirmResult = components["schemas"]["KpiMeasurementBindingConfirmResult"];
export type MeasurementBindingBatchConfirmResponse = components["schemas"]["KpiMeasurementBindingBatchConfirmResponse"];
export type MeasurementResource = components["schemas"]["KpiMeasurementResource"];
export type MeasurementResourceList = components["schemas"]["KpiMeasurementResourceList"];
export type MeasurementMetricRegisterPayload = components["schemas"]["KpiMeasurementMetricRegisterRequest"];
export type MeasurementResourceUpdatePayload = components["schemas"]["KpiMeasurementResourceUpdateRequest"];
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
  business_status?: "normal" | "warn" | "fail" | "unconfigured" | "not_applicable" | "not_judgeable";
  source_rows?: { source_file: string; line_number: number; value: string }[];
}

export type MeasurementHistoryTrend = components["schemas"]["MeasurementHistoryTrend"];
export type MeasurementHistoryPoint = components["schemas"]["MeasurementHistoryPoint"];

export interface MeasurementTrendPoint {
  time: string;
  period_minutes?: number | null;
  object_key?: string | null;
  value: number;
  source_rows?: { source_file: string; line_number: number; value: string }[];
}

export interface MeasurementTrend {
  label: "stable" | "rising" | "falling" | "spike" | "plunge" | "fluctuating" | "all_zero" | "recovering" | "cannot_determine";
  signal: "improved" | "worsened" | "none";
  reason?: string | null;
  object_key?: string | null;
  period_minutes?: number | null;
  point_count?: number;
  points?: MeasurementTrendPoint[];
}

export interface MeasurementMetadataMetric {
  metric_resource_id: string;
  metric_resource_name_zh?: string | null;
  raw_source_name: string;
  base_source_name?: string;
  display_unit?: string | null;
  read_status: "ok" | "missing" | "parse_error";
  value_pattern: "normal" | "all_zero" | "unknown";
  business_status?: "normal" | "warn" | "fail" | "unconfigured" | "not_applicable" | "not_judgeable";
  direction?: "higher_better" | "lower_better" | "neutral";
  importance?: "P0" | "P1" | "P2" | "normal";
  metric_group?: string | null;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
  trend_label?: string;
  trend_signal?: "improved" | "worsened" | "none";
  trend_reason?: string | null;
  trend_points?: MeasurementTrendPoint[];
  trends?: MeasurementTrend[];
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
export interface MeasurementRiskSummary {
  health_score: number;
  business_fail_count: number;
  business_warn_count: number;
  data_error_count: number;
  trend_worsened_count: number;
  unconfigured_count: number;
}

export interface MeasurementKpiOverview extends MeasurementRiskSummary {
  unit_count: number;
  status_counts: Record<string, number>;
  metric_count: number;
  auto_registered_count?: number;
  conflict_count?: number;
  unmatched_file_count?: number;
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
  risk_summary?: MeasurementRiskSummary;
  source_files?: string[];
  derived_metrics?: {
    metric_resource_id: string;
    metric_resource_name_zh?: string | null;
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
  const method = init?.method ?? "GET";
  const startedAt = performance.now();
  try {
    const resp = await fetch(url, { ...init, headers });
    const durationMs = Math.round(performance.now() - startedAt);
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
      logger.error("API request failed", {
        method,
        url,
        status: resp.status,
        duration_ms: durationMs,
        code,
      });
      if (resp.status === 401) {
        clearSession();
        if (typeof window !== "undefined") {
          window.location.reload();
        }
      }
      throw new ApiError(code, message, resp.status, detail);
    }
    logger.info("API request succeeded", {
      method,
      url,
      status: resp.status,
      duration_ms: durationMs,
    });
    if (resp.status === 204) return undefined as T;
    return (await resp.json()) as T;
  } catch (error) {
    if (!(error instanceof ApiError)) {
      logger.error("API request network error", {
        method,
        url,
        duration_ms: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? error.message : String(error),
      });
    }
    throw error;
  }
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

  updateTaskDeviceId: (taskId: string, deviceId: string) =>
    request<TaskSummary>(`${BASE}/tasks/${encodeURIComponent(taskId)}/device-id`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId }),
    }),

  getMeasurementHistoryTrend: (
    taskId: string,
    ruleCode: string,
    unitId: string,
    metricId: string,
    query: { object_key: string; period_minutes: number | null },
  ) => {
    const params = new URLSearchParams({ object_key: query.object_key });
    params.set("period_minutes", query.period_minutes === null ? "none" : String(query.period_minutes));
    return request<MeasurementHistoryTrend>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}` +
        `/measurement-units/${encodeURIComponent(unitId)}/metrics/${encodeURIComponent(metricId)}` +
        `/history-trend?${params.toString()}`,
    );
  },

  getMeasurementMetricDetail: (taskId: string, ruleCode: string, unitId: string, metricId: string) =>
    request<MeasurementMetricDetail>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}` +
        `/measurement-units/${encodeURIComponent(unitId)}/metrics/${encodeURIComponent(metricId)}`,
    ),


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

  listMeasurementResources: (query: { kind?: "mu" | "me" | "unit"; search?: string; enabled?: boolean; page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<MeasurementResourceList>(`${KPI_V5_BASE}/kpi/measurement-resources${qs ? `?${qs}` : ""}`);
  },

  registerMeasurementMetric: (bindingId: number, payload: MeasurementMetricRegisterPayload) =>
    request<components["schemas"]["KpiMeasurementMetricRegisterResponse"]>(
      `${KPI_V5_BASE}/kpi/measurement-bindings/${bindingId}/register-metric`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    ),

  updateMeasurementResource: (resourceId: string, payload: MeasurementResourceUpdatePayload) =>
    request<MeasurementResource>(
      `${KPI_V5_BASE}/kpi/measurement-resources/${encodeURIComponent(resourceId)}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    ),

  listMeasurementBindings: (
    query: { measurement_unit_id?: string; unit_search?: string; status?: string; search?: string; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<MeasurementBindingList>(`${KPI_V5_BASE}/kpi/measurement-bindings${qs ? `?${qs}` : ""}`);
  },

  batchConfirmMeasurementBindings: (bindingIds: number[]) =>
    request<MeasurementBindingBatchConfirmResponse>(
      `${KPI_V5_BASE}/kpi/measurement-bindings/batch-confirm`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ binding_ids: bindingIds }) },
    ),

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
