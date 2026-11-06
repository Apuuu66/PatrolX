import type { components, operations, paths } from "./client";
import { clearSession, getToken } from "./auth.ts";
import { createLogger } from "../utils/logger.ts";

const logger = createLogger("api");

export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskSummary = components["schemas"]["TaskSummary"];
export type TaskStats = components["schemas"]["TaskStats"];
export type SystemInspection = components["schemas"]["SystemInspection"];
export type RuleResult = components["schemas"]["RuleResult"];
export type RuleFinding = components["schemas"]["Finding"];
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
export type MeasurementVersionCandidateList = components["schemas"]["MeasurementVersionCandidateList"];
export type MeasurementVersionCandidate = components["schemas"]["MeasurementVersionCandidate"];
export type MeasurementVersionComparison = components["schemas"]["MeasurementVersionComparison"];
export type KpiDailyHealthMetricDetail = components["schemas"]["KpiDailyHealthMetricDetail"];
export type KpiDailyHealthMetricEvidence = components["schemas"]["KpiDailyHealthMetricEvidence"];
export type KpiDailyHealthGroup = components["schemas"]["KpiDailyHealthGroup"];
export type KpiDailyBucket = components["schemas"]["KpiDailyBucket"];
export type KpiMetricMaintenanceConfig = components["schemas"]["KpiMetricMaintenanceConfig"];
export type KpiMetricMaintenanceConfigList = components["schemas"]["KpiMetricMaintenanceConfigList"];
export type KpiMetricMaintenanceConfigUpdateRequest = components["schemas"]["KpiMetricMaintenanceConfigUpdateRequest"];
export type KpiMetricMaintenanceAudit = components["schemas"]["KpiMetricMaintenanceAudit"];
export type KpiMetricMaintenanceAuditList = components["schemas"]["KpiMetricMaintenanceAuditList"];
export type KpiMeasurementDerived = components["schemas"]["KpiMeasurementDerived"];
export type KpiMeasurementDerivedList = components["schemas"]["KpiMeasurementDerivedList"];
export type KpiMeasurementDerivedUpdateRequest = components["schemas"]["KpiMeasurementDerivedUpdateRequest"];
export type KpiTaskSummaryV6 = components["schemas"]["KpiTaskSummaryV6"];
export type KpiMetricResultV6 = components["schemas"]["KpiMetricResultV6"];
export type KpiMetricResultPageV6 = components["schemas"]["KpiMetricResultPageV6"];
export type KpiTeamFocusPageV6 = components["schemas"]["KpiTeamFocusPageV6"];
export type KpiTeamFocusItemV6 = components["schemas"]["KpiTeamFocusItemV6"];
export type KpiTeamFocusPatchRequestV6 = components["schemas"]["KpiTeamFocusPatchRequestV6"];
export type KpiTeamFocusPatchResponseV6 = components["schemas"]["KpiTeamFocusPatchResponseV6"];
export type KpiTeamFocusQueryV6 = NonNullable<
  operations["listKpiTeamFocusV6"]["parameters"]["query"]
>;
export type KpiMetricEvidenceV6 = components["schemas"]["KpiMetricEvidenceV6"];
export type KpiTechnicalAnalysisV6 = components["schemas"]["KpiTechnicalAnalysisV6"];
export type KpiDailyBucketV6 = components["schemas"]["KpiDailyBucketV6"];
export type KpiResultView = components["schemas"]["KpiResultView"];
export type KpiNeedsAttentionGroup = components["schemas"]["NeedsAttentionGroup"];
export type KpiCurrentHealthStatus = components["schemas"]["CurrentHealthStatus"];
export type KpiTrendHealthStatus = components["schemas"]["TrendHealthStatus"];
export type KpiTaskMetricQueryV6 = NonNullable<
  operations["listKpiTaskMetricsV6"]["parameters"]["query"]
>;

export type KpiMeasurementUnitV6 = components["schemas"]["KpiMeasurementUnitV6"];
export type KpiMeasurementUnitPageV6 = components["schemas"]["KpiMeasurementUnitPageV6"];
export type KpiMeasurementInspectionPatchV6 = components["schemas"]["KpiMeasurementInspectionPatchV6"];
export type KpiMeasurementUnitQueryV6 = NonNullable<
  operations["listKpiMeasurementUnitsV6"]["parameters"]["query"]
>;
export type KpiMeasurementBindingV6 = components["schemas"]["KpiMeasurementBindingV6"];
export type KpiMeasurementBindingPageV6 = components["schemas"]["KpiMeasurementBindingPageV6"];
export type KpiMeasurementBindingPatchV6 = components["schemas"]["KpiMeasurementBindingPatchV6"];
export type KpiMeasurementBindingQueryV6 = NonNullable<
  operations["listKpiMeasurementBindingsV6"]["parameters"]["query"]
>;
export type KpiLegacyRecoveryAuditV6 = components["schemas"]["KpiLegacyRecoveryAuditV6"];
export type KpiLegacyRecoveryAuditPageV6 = components["schemas"]["KpiLegacyRecoveryAuditPageV6"];
export type KpiLegacyRecoveryAuditQueryV6 = NonNullable<
  operations["listKpiLegacyRecoveryAuditsV6"]["parameters"]["query"]
>;
export type KpiLegacyRecoveryRetryRequestV6 = components["schemas"]["KpiLegacyRecoveryRetryRequestV6"];
export type KpiPendingAttributionV6 = components["schemas"]["KpiPendingAttributionV6"];
export type KpiPendingAttributionPageV6 = components["schemas"]["KpiPendingAttributionPageV6"];
export type KpiPendingAttributionQueryV6 = NonNullable<
  operations["listKpiPendingAttributionsV6"]["parameters"]["query"]
>;
export type KpiPendingAttributionResolveRequestV6 = components["schemas"]["KpiPendingAttributionResolveRequestV6"];
export type KpiMaintenanceOperationAcceptedV6 = components["schemas"]["KpiMaintenanceOperationAcceptedV6"];
export type KpiMaintenanceOperationV6 = components["schemas"]["KpiMaintenanceOperationV6"];
export type KpiRuleNetworkAssignmentV6 = components["schemas"]["KpiRuleNetworkAssignmentV6"];
export type KpiRuleNetworkAssignmentPageV6 = components["schemas"]["KpiRuleNetworkAssignmentPageV6"];
export type KpiRuleAssignmentWriteResultV6 = components["schemas"]["KpiRuleAssignmentWriteResultV6"];
export type KpiRuleAssignmentPatchRequestV6 = components["schemas"]["KpiRuleAssignmentPatchRequestV6"];
export type KpiRuleAssignmentBatchRequestV6 = components["schemas"]["KpiRuleAssignmentBatchRequestV6"];
export type KpiRuleAssignmentBatchResponseV6 = components["schemas"]["KpiRuleAssignmentBatchResponseV6"];
export type KpiRuleNetworkAssignmentQueryV6 = NonNullable<
  operations["listKpiRuleNetworkAssignmentsV6"]["parameters"]["query"]
>;

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
  trend_point_count?: number;
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
export type PackageKind = components["schemas"]["PackageKind"];
export type InventoryDevice = components["schemas"]["InventoryDevice"];
export type InventoryDeviceList = components["schemas"]["InventoryDeviceList"];
export type InventoryObservation = components["schemas"]["InventoryObservation"];
export type InventoryObservationList = components["schemas"]["InventoryObservationList"];
export type InventoryVersionPoint = components["schemas"]["InventoryVersionPoint"];
export type InventoryVersionHistory = components["schemas"]["InventoryVersionHistory"];
export type InventoryQualityIssue = components["schemas"]["InventoryQualityIssue"];
export type InventoryQualityIssueList = components["schemas"]["InventoryQualityIssueList"];
export type InventoryQualityIssueType = components["schemas"]["InventoryQualityIssueType"];
export type RebuildRequestPayload = Omit<components["schemas"]["RebuildRequest"], "confirmed"> & {
  confirmed: true;
};

const BASE = "/api/v2";
const KPI_V5_BASE = "/api/v5";
const AUTH_BASE = "/api/v1";

type V6PathKey = Extract<keyof paths, `/api/v6/${string}`>;

const KPI_V6_PATHS = {
  taskSummary: "/api/v6/kpi/tasks/{task_id}/summary",
  taskMetrics: "/api/v6/kpi/tasks/{task_id}/metrics",
  metricEvidence: "/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/evidence",
  metricTechnicalAnalysis: "/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/technical-analysis",
  teamFocus: "/api/v6/kpi/team-focus/{network_element_type}",
  measurementUnits: "/api/v6/kpi/measurement-units",
  measurementUnit: "/api/v6/kpi/measurement-units/{network_element_type}/{measurement_unit_id}",
  measurementBindings: "/api/v6/kpi/measurement-bindings",
  measurementBinding: "/api/v6/kpi/measurement-bindings/{network_element_type}/{binding_id}",
  legacyRecoveryAudits: "/api/v6/kpi/legacy-recovery-audits",
  legacyRecoveryRetry: "/api/v6/kpi/legacy-recovery-audits/retry",
  pendingAttributions: "/api/v6/kpi/pending-attributions",
  pendingAttributionResolve: "/api/v6/kpi/pending-attributions/{pending_id}/resolve",
  maintenanceOperation: "/api/v6/kpi/maintenance-operations/{operation_id}",
  ruleNetworkAssignments: "/api/v6/kpi/rule-network-assignments",
  ruleNetworkAssignmentBatch: "/api/v6/kpi/rule-network-assignments/batch",
  ruleNetworkAssignmentAudits: "/api/v6/kpi/rule-network-assignments/audits",
  ruleNetworkAssignment: "/api/v6/kpi/rule-network-assignments/{rule_code}",
} satisfies Record<string, V6PathKey>;

/** 用生成契约中的路径模板构造实际请求地址。 */
function v6Path(template: V6PathKey, params: Record<string, string | number> = {}): string {
  return template.replace(/\{([^}]+)\}/g, (_match, key: string) => {
    const value = params[key];
    if (value === undefined) {
      throw new Error(`缺少路径参数: ${key}`);
    }
    return encodeURIComponent(String(value));
  });
}

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

/** 统一附加会话头并映射错误响应；调用方只关心成功后的响应体。 */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
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
        // 未登录（本地无会话）时不能再触发整页重载，否则受保护接口会形成
        // 401 -> reload -> 再次 401 的无限刷新循环；仅会话失效时才强制回登录态。
        const hadSession = token !== null;
        if (hadSession) {
          clearSession();
          if (typeof window !== "undefined") {
            window.location.reload();
          }
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
    return resp;
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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(url, init);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

/** 报告以 HTML 原文返回，需要保留原始标记而不是解析为 JSON。 */
async function requestText(url: string, init?: RequestInit): Promise<string> {
  const resp = await apiFetch(url, init);
  return resp.text();
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

  createTaskV3: (form: FormData) =>
    request<{ task_id: string }>("/api/v3/tasks", {
      method: "POST",
      body: form,
    }),

  listInventoryDevices: (query: { page?: number; page_size?: number; province?: string; operator?: string; quality_status?: string } = {}) => {
    const params = new URLSearchParams();
    if (query.page) params.set("page", String(query.page));
    if (query.page_size) params.set("page_size", String(query.page_size));
    if (query.province) params.set("province", query.province);
    if (query.operator) params.set("operator", query.operator);
    if (query.quality_status && query.quality_status !== "all") params.set("quality_status", query.quality_status);
    const qs = params.toString();
    return request<InventoryDeviceList>(`/api/v2/inventory/devices${qs ? `?${qs}` : ""}`);
  },

  getInventoryDevice: (deviceId: string) =>
    request<InventoryDevice>(`/api/v2/inventory/devices/${encodeURIComponent(deviceId)}`),

  deleteInventoryDevice: (deviceId: string) =>
    request<void>(`/api/v2/inventory/devices/${encodeURIComponent(deviceId)}`, {
      method: "DELETE",
    }),

  listInventoryObservations: (deviceId: string, query: { page?: number; page_size?: number; order?: "asc" | "desc"; site_key?: string } = {}) => {
    const params = new URLSearchParams();
    if (query.page) params.set("page", String(query.page));
    if (query.page_size) params.set("page_size", String(query.page_size));
    if (query.order) params.set("order", query.order);
    if (query.site_key) params.set("site_key", query.site_key);
    const qs = params.toString();
    return request<InventoryObservationList>(
      `/api/v2/inventory/devices/${encodeURIComponent(deviceId)}/observations${qs ? `?${qs}` : ""}`,
    );
  },

  getInventoryVersionHistory: (deviceId: string, query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    if (query.page) params.set("page", String(query.page));
    if (query.page_size) params.set("page_size", String(query.page_size));
    const qs = params.toString();
    return request<InventoryVersionHistory>(
      `/api/v2/inventory/devices/${encodeURIComponent(deviceId)}/version-history${qs ? `?${qs}` : ""}`,
    );
  },

  listInventoryQualityIssues: (query: { page?: number; page_size?: number; issue_type?: InventoryQualityIssueType; province?: string; operator?: string; task_id?: string; device_id?: string } = {}) => {
    const params = new URLSearchParams();
    if (query.page) params.set("page", String(query.page));
    if (query.page_size) params.set("page_size", String(query.page_size));
    if (query.issue_type) params.set("issue_type", query.issue_type);
    if (query.province) params.set("province", query.province);
    if (query.operator) params.set("operator", query.operator);
    if (query.task_id) params.set("task_id", query.task_id);
    if (query.device_id) params.set("device_id", query.device_id);
    const qs = params.toString();
    return request<InventoryQualityIssueList>(`/api/v2/inventory/quality-issues${qs ? `?${qs}` : ""}`);
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

  getMeasurementVersionCandidates: (
    taskId: string,
    ruleCode: string,
    unitId: string,
    metricId: string,
    query: { object_key: string; period_minutes: number | null },
  ) => {
    const params = new URLSearchParams({ object_key: query.object_key });
    params.set("period_minutes", query.period_minutes === null ? "none" : String(query.period_minutes));
    return request<MeasurementVersionCandidateList>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}` +
        `/measurement-units/${encodeURIComponent(unitId)}/metrics/${encodeURIComponent(metricId)}` +
        `/version-candidates?${params.toString()}`,
    );
  },

  getMeasurementVersionCompare: (
    taskId: string,
    ruleCode: string,
    unitId: string,
    metricId: string,
    query: { baseline_task_id: string; object_key: string; period_minutes: number | null },
  ) => {
    const params = new URLSearchParams({ object_key: query.object_key });
    params.set("baseline_task_id", query.baseline_task_id);
    params.set("period_minutes", query.period_minutes === null ? "none" : String(query.period_minutes));
    return request<MeasurementVersionComparison>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}` +
        `/measurement-units/${encodeURIComponent(unitId)}/metrics/${encodeURIComponent(metricId)}` +
        `/version-compare?${params.toString()}`,
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

  getKpiTaskSummaryV6: (taskId: string) =>
    request<KpiTaskSummaryV6>(
      v6Path(KPI_V6_PATHS.taskSummary, { task_id: taskId }),
    ),

  listKpiTeamFocusV6: (
    networkElementType: string,
    query: KpiTeamFocusQueryV6,
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiTeamFocusPageV6>(
      `${v6Path(KPI_V6_PATHS.teamFocus, { network_element_type: networkElementType })}${qs ? `?${qs}` : ""}`,
    );
  },

  patchKpiTeamFocusV6: (
    networkElementType: string,
    payload: KpiTeamFocusPatchRequestV6,
  ) =>
    request<KpiTeamFocusPatchResponseV6>(
      v6Path(KPI_V6_PATHS.teamFocus, { network_element_type: networkElementType }),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  listKpiRuleNetworkAssignmentsV6: (query: KpiRuleNetworkAssignmentQueryV6 = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiRuleNetworkAssignmentPageV6>(
      `${v6Path(KPI_V6_PATHS.ruleNetworkAssignments)}${qs ? `?${qs}` : ""}`,
    );
  },

  updateKpiRuleNetworkAssignmentV6: (
    ruleCode: string,
    payload: KpiRuleAssignmentPatchRequestV6,
  ) =>
    request<KpiRuleAssignmentWriteResultV6>(
      v6Path(KPI_V6_PATHS.ruleNetworkAssignment, { rule_code: ruleCode }),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  batchUpdateKpiRuleNetworkAssignmentsV6: (payload: KpiRuleAssignmentBatchRequestV6) =>
    request<KpiRuleAssignmentBatchResponseV6>(
      v6Path(KPI_V6_PATHS.ruleNetworkAssignmentBatch),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  listKpiTaskMetricsV6: (taskId: string, query: KpiTaskMetricQueryV6 = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiMetricResultPageV6>(
      `${v6Path(KPI_V6_PATHS.taskMetrics, { task_id: taskId })}${qs ? `?${qs}` : ""}`,
    );
  },

  getKpiMetricEvidenceV6: (
    taskId: string,
    measurementUnitId: string,
    metricResourceId: string,
  ) =>
    request<KpiMetricEvidenceV6>(
      v6Path(KPI_V6_PATHS.metricEvidence, {
        task_id: taskId,
        measurement_unit_id: measurementUnitId,
        metric_resource_id: metricResourceId,
      }),
    ),

  getKpiMetricTechnicalAnalysisV6: (
    taskId: string,
    measurementUnitId: string,
    metricResourceId: string,
  ) =>
    request<KpiTechnicalAnalysisV6>(
      v6Path(KPI_V6_PATHS.metricTechnicalAnalysis, {
        task_id: taskId,
        measurement_unit_id: measurementUnitId,
        metric_resource_id: metricResourceId,
      }),
    ),

  getKpiDailyHealthMetric: (
    taskId: string,
    ruleCode: string,
    measurementUnitId: string,
    metricResourceId: string,
  ) =>
    request<KpiDailyHealthMetricDetail>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}`
        + `/daily-health/${encodeURIComponent(measurementUnitId)}/${encodeURIComponent(metricResourceId)}`,
    ),

  listKpiMetricMaintenanceConfigs: (
    query: { measurement_unit_id?: string; metric_resource_id?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiMetricMaintenanceConfigList>(
      `${KPI_V5_BASE}/kpi/metric-maintenance-configs${qs ? `?${qs}` : ""}`,
    );
  },

  getKpiMetricMaintenanceConfig: (measurementUnitId: string, metricResourceId: string) =>
    request<KpiMetricMaintenanceConfig>(
      `${KPI_V5_BASE}/kpi/metric-maintenance-configs/${encodeURIComponent(measurementUnitId)}`
        + `/${encodeURIComponent(metricResourceId)}`,
    ),

  updateKpiMetricMaintenanceConfig: (
    measurementUnitId: string,
    metricResourceId: string,
    payload: KpiMetricMaintenanceConfigUpdateRequest,
  ) =>
    request<KpiMetricMaintenanceConfig>(
      `${KPI_V5_BASE}/kpi/metric-maintenance-configs/${encodeURIComponent(measurementUnitId)}`
        + `/${encodeURIComponent(metricResourceId)}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    ),

  listKpiMetricMaintenanceAudits: (
    measurementUnitId: string,
    metricResourceId: string,
    query: { page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiMetricMaintenanceAuditList>(
      `${KPI_V5_BASE}/kpi/metric-maintenance-configs/${encodeURIComponent(measurementUnitId)}`
        + `/${encodeURIComponent(metricResourceId)}/audits${qs ? `?${qs}` : ""}`,
    );
  },

  listKpiMeasurementDerived: (
    query: { measurement_unit_id?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiMeasurementDerivedList>(
      `${KPI_V5_BASE}/kpi/measurement-derived${qs ? `?${qs}` : ""}`,
    );
  },

  getKpiMeasurementDerived: (derivedId: number) =>
    request<KpiMeasurementDerived>(`${KPI_V5_BASE}/kpi/measurement-derived/${derivedId}`),

  updateKpiMeasurementDerived: (derivedId: number, payload: KpiMeasurementDerivedUpdateRequest) =>
    request<KpiMeasurementDerived>(`${KPI_V5_BASE}/kpi/measurement-derived/${derivedId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listKpiMeasurementUnitsV6: (query: KpiMeasurementUnitQueryV6) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request<KpiMeasurementUnitPageV6>(
      `${v6Path(KPI_V6_PATHS.measurementUnits)}?${params.toString()}`,
    );
  },

  getKpiMeasurementUnitV6: (networkElementType: string, measurementUnitId: string) =>
    request<KpiMeasurementUnitV6>(
      v6Path(KPI_V6_PATHS.measurementUnit, {
        network_element_type: networkElementType,
        measurement_unit_id: measurementUnitId,
      }),
    ),

  setKpiMeasurementInspectionEnabledV6: (
    networkElementType: string,
    measurementUnitId: string,
    payload: KpiMeasurementInspectionPatchV6,
  ) =>
    request<KpiMeasurementUnitV6>(
      v6Path(KPI_V6_PATHS.measurementUnit, {
        network_element_type: networkElementType,
        measurement_unit_id: measurementUnitId,
      }),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  listKpiMeasurementBindingsV6: (query: KpiMeasurementBindingQueryV6) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request<KpiMeasurementBindingPageV6>(
      `${v6Path(KPI_V6_PATHS.measurementBindings)}?${params.toString()}`,
    );
  },

  correctKpiMeasurementBindingV6: (
    networkElementType: string,
    bindingId: number,
    payload: KpiMeasurementBindingPatchV6,
  ) =>
    request<KpiMeasurementBindingV6>(
      v6Path(KPI_V6_PATHS.measurementBinding, {
        network_element_type: networkElementType,
        binding_id: bindingId,
      }),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  listKpiLegacyRecoveryAuditsV6: (query: KpiLegacyRecoveryAuditQueryV6 = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request<KpiLegacyRecoveryAuditPageV6>(
      `${v6Path(KPI_V6_PATHS.legacyRecoveryAudits)}?${params.toString()}`,
    );
  },

  retryKpiLegacyRecoveryV6: (payload: KpiLegacyRecoveryRetryRequestV6) =>
    request<KpiMaintenanceOperationAcceptedV6>(
      v6Path(KPI_V6_PATHS.legacyRecoveryRetry),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  listKpiPendingAttributionsV6: (query: KpiPendingAttributionQueryV6 = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request<KpiPendingAttributionPageV6>(
      `${v6Path(KPI_V6_PATHS.pendingAttributions)}?${params.toString()}`,
    );
  },

  resolveKpiPendingAttributionV6: (
    pendingId: number,
    payload: KpiPendingAttributionResolveRequestV6,
  ) =>
    request<KpiMaintenanceOperationAcceptedV6>(
      v6Path(KPI_V6_PATHS.pendingAttributionResolve, { pending_id: pendingId }),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  getKpiMaintenanceOperationV6: (operationId: string) =>
    request<KpiMaintenanceOperationV6>(
      v6Path(KPI_V6_PATHS.maintenanceOperation, { operation_id: operationId }),
    ),


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

  /** 读取巡检报告 HTML；现场已清理时抛出 410 scene_cleaned（FR-011）。 */
  getTaskReportHtml: (taskId: string) => requestText(reportUrl(taskId)),
};

export const reportUrl = (taskId: string) => `${BASE}/tasks/${encodeURIComponent(taskId)}/report`;
