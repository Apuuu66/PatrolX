import type { components } from "./client";
import { clearSession, getToken } from "./auth.ts";

export type TaskStatus = components["schemas"]["TaskStatusV2"];
export type TaskSummary = components["schemas"]["TaskSummaryV2"];
export type TaskStats = components["schemas"]["TaskStatsV2"];
export type SystemInspection = components["schemas"]["SystemInspectionV2"];
export type RuleResult = components["schemas"]["RuleResultV2"];
export type RuleStatus = components["schemas"]["RuleStatusV2"];
export type Severity = components["schemas"]["SeverityV2"];
export type InspectorInfo = components["schemas"]["InspectorInfoV2"];
export type KpiRecordItem = components["schemas"]["KpiRecordItemV2"];
export type KpiRecordPage = components["schemas"]["KpiRecordPageV2"];
export type DataPreparation = components["schemas"]["DataPreparationV2"];
export type PreparationItem = components["schemas"]["PreparationItemV2"];
export type PreparationIssue = components["schemas"]["PreparationIssueV2"];
export type DictsResponse = components["schemas"]["DictsResponseV2"];
export type OverviewSummary = components["schemas"]["OverviewSummaryV2"];
export type DictItem = components["schemas"]["DictItemV2"];
export type LogEntry = components["schemas"]["LogEntryV2"];
export type KpiResourceDomain = components["schemas"]["KpiResourceDomainV3"];
export type KpiResourceMetric = components["schemas"]["KpiResourceMetricV3"];
export type KpiResourceMetricPage = components["schemas"]["KpiResourceMetricPageV3"];
export type KpiResourceClassificationResult = components["schemas"]["KpiResourceClassificationResultV3"];
export type KpiClassificationAudit = components["schemas"]["KpiClassificationAuditV3"];
export type KpiClassificationAuditPage = components["schemas"]["KpiClassificationAuditPageV3"];
export type KpiTaskCatalogSnapshot = components["schemas"]["KpiTaskCatalogSnapshotV3"];
export type KpiRegisteredDomainV4 = components["schemas"]["KpiRegisteredDomainV4"];
export type KpiSourceTypeV4 = components["schemas"]["KpiSourceTypeV4"];
export type KpiMetricTypeV4 = components["schemas"]["KpiMetricTypeV4"];
export type KpiSemanticGroupV4 = components["schemas"]["KpiSemanticGroupV4"];
export type KpiDisplayRoleV4 = components["schemas"]["KpiDisplayRoleV4"];
export type KpiAggregationKindV4 = components["schemas"]["KpiAggregationKindV4"];
export type KpiThresholdDirectionV4 = components["schemas"]["KpiThresholdDirectionV4"];
export type KpiCapacityStatusV4 = components["schemas"]["KpiCapacityStatusV4"];
export type KpiCapacitySemanticsV4 = components["schemas"]["KpiCapacitySemanticsV4"];
export type KpiConfigEntityTypeV4 = components["schemas"]["KpiConfigEntityTypeV4"];
export type KpiClueStatusV4 = components["schemas"]["KpiClueStatusV4"];
export type KpiMetricRuleRequestV4 = components["schemas"]["KpiMetricRuleRequestV4"];
export type KpiMetricRuleV4 = components["schemas"]["KpiMetricRuleV4"];
export type KpiMetricRulePageV4 = components["schemas"]["KpiMetricRulePageV4"];
export type KpiThresholdRequestV4 = components["schemas"]["KpiThresholdRequestV4"];
export type KpiThresholdV4 = components["schemas"]["KpiThresholdV4"];
export type KpiThresholdPageV4 = components["schemas"]["KpiThresholdPageV4"];
export type KpiCapacityRuleRequestV4 = components["schemas"]["KpiCapacityRuleRequestV4"];
export type KpiCapacityRuleV4 = components["schemas"]["KpiCapacityRuleV4"];
export type KpiCapacityRulePageV4 = components["schemas"]["KpiCapacityRulePageV4"];
export type KpiDisplayRuleRequestV4 = components["schemas"]["KpiDisplayRuleRequestV4"];
export type KpiDisplayRuleV4 = components["schemas"]["KpiDisplayRuleV4"];
export type KpiDisplayRulePageV4 = components["schemas"]["KpiDisplayRulePageV4"];
export type KpiCommonConfigRequestV4 = components["schemas"]["KpiCommonConfigRequestV4"];
export type KpiCommonConfigV4 = components["schemas"]["KpiCommonConfigV4"];
export type KpiConfigAuditV4 = components["schemas"]["KpiConfigAuditV4"];
export type KpiConfigAuditPageV4 = components["schemas"]["KpiConfigAuditPageV4"];
export type KpiClassificationClueV4 = components["schemas"]["KpiClassificationClueV4"];
export type KpiClassificationCluePageV4 = components["schemas"]["KpiClassificationCluePageV4"];
export type TaskDeleteError = TaskDeleteErrorDetail;
export type RebuildMode = components["schemas"]["RebuildModeV2"];
export type RebuildTriggerSource = components["schemas"]["RebuildRequestV2"]["trigger_source"];
export type RebuildRequestPayload = Omit<components["schemas"]["RebuildRequestV2"], "confirmed"> & {
  confirmed: true;
};

const BASE = "/api/v2";
const KPI_BASE = "/api/v3";
const KPI_V4_BASE = "/api/v4";

export type TaskDeleteErrorDetail = components["schemas"]["TaskDeleteErrorDetailV2"];

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

  listKpiRecords: (
    taskId: string,
    ruleCode: string,
    query: {
      metric_key?: string;
      source_file?: string;
      period_minutes?: 5 | 15 | 30 | 60;
      status?: components["schemas"]["KpiDisplayStatusV2"];
      page?: number;
      page_size?: number;
    } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiRecordPage>(
      `${BASE}/tasks/${encodeURIComponent(taskId)}/rules/${encodeURIComponent(ruleCode)}/kpi/records${qs ? `?${qs}` : ""}`,
    );
  },

  listInspectors: (category?: string, includeHidden = false) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (includeHidden) params.set("include_hidden", "true");
    const qs = params.toString();
    return request<InspectorInfo[]>(`${BASE}/inspectors${qs ? `?${qs}` : ""}`);
  },

  listDicts: () => request<DictsResponse>(`${BASE}/dicts`),

  listKpiResourceMetrics: (query: KpiResourceQuery = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiResourceMetricPage>(`${KPI_BASE}/kpi/resource-metrics${qs ? `?${qs}` : ""}`);
  },

  classifyKpiResourceMetrics: (payload: KpiResourceClassificationPayload) =>
    request<KpiResourceClassificationResult>(`${KPI_BASE}/kpi/resource-metrics/classification`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listKpiClassificationAudits: (query: KpiClassificationAuditQuery = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiClassificationAuditPage>(
      `${KPI_BASE}/kpi/resource-metrics/classification-audits${qs ? `?${qs}` : ""}`,
    );
  },

  getKpiCatalogSnapshot: (taskId: string) =>
    request<KpiTaskCatalogSnapshot>(`${KPI_BASE}/tasks/${encodeURIComponent(taskId)}/kpi/catalog-snapshot`),

  listKpiMetricRulesV4: (query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiMetricRulePageV4>(`${KPI_V4_BASE}/kpi/config/metric-rules${qs ? `?${qs}` : ""}`);
  },

  upsertKpiMetricRuleV4: (metricKey: string, payload: KpiMetricRuleRequestV4) =>
    request<KpiMetricRuleV4>(`${KPI_V4_BASE}/kpi/config/metric-rules/${encodeURIComponent(metricKey)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteKpiMetricRuleV4: (metricKey: string) =>
    request<components["schemas"]["KpiConfigDeleteResultV4"]>(
      `${KPI_V4_BASE}/kpi/config/metric-rules/${encodeURIComponent(metricKey)}`,
      { method: "DELETE" },
    ),

  listKpiThresholdsV4: (query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiThresholdPageV4>(`${KPI_V4_BASE}/kpi/config/thresholds${qs ? `?${qs}` : ""}`);
  },

  createKpiThresholdV4: (payload: KpiThresholdRequestV4) =>
    request<KpiThresholdV4>(`${KPI_V4_BASE}/kpi/config/thresholds`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateKpiThresholdV4: (id: number, payload: KpiThresholdRequestV4) =>
    request<KpiThresholdV4>(`${KPI_V4_BASE}/kpi/config/thresholds/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteKpiThresholdV4: (id: number) =>
    request<components["schemas"]["KpiConfigDeleteResultV4"]>(`${KPI_V4_BASE}/kpi/config/thresholds/${id}`, {
      method: "DELETE",
    }),

  listKpiCapacityRulesV4: (query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiCapacityRulePageV4>(`${KPI_V4_BASE}/kpi/config/capacity-rules${qs ? `?${qs}` : ""}`);
  },

  createKpiCapacityRuleV4: (payload: KpiCapacityRuleRequestV4) =>
    request<KpiCapacityRuleV4>(`${KPI_V4_BASE}/kpi/config/capacity-rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateKpiCapacityRuleV4: (id: number, payload: KpiCapacityRuleRequestV4) =>
    request<KpiCapacityRuleV4>(`${KPI_V4_BASE}/kpi/config/capacity-rules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteKpiCapacityRuleV4: (id: number) =>
    request<components["schemas"]["KpiConfigDeleteResultV4"]>(`${KPI_V4_BASE}/kpi/config/capacity-rules/${id}`, {
      method: "DELETE",
    }),

  listKpiDisplayRulesV4: (query: { page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiDisplayRulePageV4>(`${KPI_V4_BASE}/kpi/config/display-rules${qs ? `?${qs}` : ""}`);
  },

  createKpiDisplayRuleV4: (payload: KpiDisplayRuleRequestV4) =>
    request<KpiDisplayRuleV4>(`${KPI_V4_BASE}/kpi/config/display-rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateKpiDisplayRuleV4: (id: number, payload: KpiDisplayRuleRequestV4) =>
    request<KpiDisplayRuleV4>(`${KPI_V4_BASE}/kpi/config/display-rules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteKpiDisplayRuleV4: (id: number) =>
    request<components["schemas"]["KpiConfigDeleteResultV4"]>(`${KPI_V4_BASE}/kpi/config/display-rules/${id}`, {
      method: "DELETE",
    }),

  getKpiCommonConfigV4: () => request<KpiCommonConfigV4>(`${KPI_V4_BASE}/kpi/config/common`),

  updateKpiCommonConfigV4: (payload: KpiCommonConfigRequestV4) =>
    request<KpiCommonConfigV4>(`${KPI_V4_BASE}/kpi/config/common`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listKpiConfigAuditsV4: (
    query: { entity_type?: KpiConfigEntityTypeV4; operator?: string; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiConfigAuditPageV4>(`${KPI_V4_BASE}/kpi/config/audits${qs ? `?${qs}` : ""}`);
  },

  listKpiClassificationCluesV4: (
    taskId: string,
    query: { clue_status?: KpiClueStatusV4; search?: string; page?: number; page_size?: number } = {},
  ) => {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const qs = params.toString();
    return request<KpiClassificationCluePageV4>(
      `${KPI_V4_BASE}/tasks/${encodeURIComponent(taskId)}/kpi/classification-clues${qs ? `?${qs}` : ""}`,
    );
  },
};

export const reportUrl = (taskId: string) => `${BASE}/tasks/${encodeURIComponent(taskId)}/report`;

export interface KpiResourceQuery {
  search?: string;
  domain?: KpiResourceDomain;
  page?: number;
  page_size?: number;
}

export interface KpiResourceClassificationPayload {
  metric_keys: string[];
  domain: KpiResourceDomain;
  operator: string;
}

export interface KpiClassificationAuditQuery {
  metric_key?: string;
  operator?: string;
  domain?: KpiResourceDomain;
  page?: number;
  page_size?: number;
}
