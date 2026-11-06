import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";

import {
  api,
  type KpiMeasurementBindingV6,
  type KpiMeasurementUnitV6,
  type KpiLegacyRecoveryAuditV6,
  type KpiPendingAttributionV6,
  type TaskSummary,
} from "../api/http";
import { MeasurementUnitsPage } from "./MeasurementUnitsPage";

const authState = vi.hoisted(() => ({
  user: null as { username: string; role: string } | null,
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: authState.user,
    login: vi.fn(),
    logout: vi.fn(),
    canWrite: authState.user?.role === "admin",
  }),
}));

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listMeasurementUnits: vi.fn(),
    importMeasurementUnits: vi.fn(),
    setMeasurementUnitEnabled: vi.fn(),
    listTasks: vi.fn(),
    listMeasurementBindings: vi.fn(),
    listMeasurementResources: vi.fn(),
    setMeasurementBindingStatus: vi.fn(),
    batchConfirmMeasurementBindings: vi.fn(),
    registerMeasurementMetric: vi.fn(),
    updateMeasurementResource: vi.fn(),
    createMeasurementDerived: vi.fn(),
    listKpiMetricMaintenanceConfigs: vi.fn(),
    listKpiMeasurementDerived: vi.fn(),
    listKpiMetricMaintenanceAudits: vi.fn(),
    updateKpiMetricMaintenanceConfig: vi.fn(),
    updateKpiMeasurementDerived: vi.fn(),
    listKpiMeasurementUnitsV6: vi.fn(),
    setKpiMeasurementInspectionEnabledV6: vi.fn(),
    listKpiMeasurementBindingsV6: vi.fn(),
    correctKpiMeasurementBindingV6: vi.fn(),
    listKpiLegacyRecoveryAuditsV6: vi.fn(),
    retryKpiLegacyRecoveryV6: vi.fn(),
    listKpiPendingAttributionsV6: vi.fn(),
    resolveKpiPendingAttributionV6: vi.fn(),
    getKpiMaintenanceOperationV6: vi.fn(),
  },
}));

const umfUnit: KpiMeasurementUnitV6 = {
  network_element_type: "UMF",
  measurement_unit_id: "MU_MEDIA",
  name_zh: "媒体资源测量单元",
  name_en: "Media Resource Measurement Unit",
  inspection_enabled: true,
  revision: 3,
  base_metric_count: 20,
  derived_metric_count: 2,
  confirmed_binding_count: 20,
  candidate_binding_count: 0,
  configuration_state: "ready" as const,
  recovery_state: "completed" as const,
  source: "discovered" as const,
  updated_at: "2026-11-05T03:08:00Z",
};

const cspUnit: KpiMeasurementUnitV6 = {
  ...umfUnit,
  network_element_type: "CSP",
  measurement_unit_id: "MU_CSP_MEDIA",
  name_zh: "CSP 媒体资源测量单元",
  revision: 1,
};

const completedTask = {
  task_id: "task-kpi",
  name: "KPI 巡检任务",
  status: "completed",
} as TaskSummary;

const candidateBinding: KpiMeasurementBindingV6 = {
  id: 41,
  network_element_type: "UMF",
  measurement_unit_id: "MU_MEDIA",
  measurement_unit_name: "媒体资源测量单元",
  raw_source_name: "待确认来源列",
  base_source_name: "媒体资源创建成功率",
  metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
  metric_resource_name: "媒体资源创建成功率",
  display_unit: "%",
  status: "candidate",
  source_file: "scope.csv",
  origin_task_id: "task-kpi",
  revision: 3,
  updated_at: "2026-11-05T03:08:00Z",
  diagnostic: "绑定待人工确认",
};

const failedRecoveryAudit: KpiLegacyRecoveryAuditV6 = {
  audit_id: 91,
  source_table: "kpi_measurement_resources",
  source_record_id: "12",
  source_key: "metric:UMF:MU_MEDIA:ME_MEDIA_CREATION_SUCCESS_RATE",
  network_element_type: "UMF",
  measurement_unit_id: "MU_MEDIA",
  metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
  object_kind: "metric",
  before_snapshot: { enabled: false },
  result: "failed",
  error_code: "migration_row_error",
  error_message: "恢复时源记录缺失",
  attempt_count: 1,
  actor: null,
  source: "migration",
  created_at: "2026-11-05T03:08:00Z",
  updated_at: "2026-11-05T03:08:00Z",
};

const pendingAttribution: KpiPendingAttributionV6 = {
  pending_id: 44,
  source_table: "kpi_measurement_resources",
  source_record_id: "9",
  source_key: "metric:unknown:ME_PENDING_MEDIA",
  source_payload: { resource_id: "ME_PENDING_MEDIA", product: "media" },
  candidate_network_element_types: ["UMF", "CSP"],
  reason: "ambiguous_product",
  resolution_state: "pending",
  assigned_network_element_type: null,
  attempt_count: 0,
  last_error: null,
  idempotency_key: "pending-attribution-key",
  created_at: "2026-11-05T03:08:00Z",
  updated_at: "2026-11-05T03:08:00Z",
};

function KpiRouteProbe() {
  const { taskId } = useParams();
  return <div data-testid="kpi-route">{taskId}</div>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/measurement-units"]}>
      <App>
        <Routes>
          <Route path="/measurement-units" element={<MeasurementUnitsPage />} />
          <Route path="/tasks/:taskId/kpi" element={<KpiRouteProbe />} />
        </Routes>
      </App>
    </MemoryRouter>,
  );
}

function mockUnitPage(
  itemsByScope: Partial<Record<"UMF" | "CSP", KpiMeasurementUnitV6[]>> = {
    UMF: [umfUnit],
    CSP: [cspUnit],
  },
) {
  vi.mocked(api.listKpiMeasurementUnitsV6).mockImplementation(async (query) => {
    const items = itemsByScope[query.network_element_type] ?? [];
    return { total: items.length, page: 1, page_size: 20, items };
  });
}

describe("MeasurementUnitsPage 测量单元巡检范围", () => {
  beforeEach(() => {
    authState.user = { username: "admin", role: "admin" };
    vi.clearAllMocks();
    vi.mocked(api.listTasks).mockResolvedValue({ total: 1, items: [completedTask] });
    vi.mocked(api.listMeasurementUnits).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(api.listMeasurementBindings).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(api.listMeasurementResources).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(api.listKpiLegacyRecoveryAuditsV6).mockResolvedValue({ total: 0, page: 1, page_size: 20, items: [] });
    vi.mocked(api.listKpiPendingAttributionsV6).mockResolvedValue({ total: 0, page: 1, page_size: 20, items: [] });
    vi.mocked(api.listKpiMeasurementBindingsV6).mockResolvedValue({ total: 0, page: 1, page_size: 20, items: [] });
    mockUnitPage();
  });

  it("默认读取 UMF，并展示测量单元级基础与派生计数", async () => {
    renderPage();

    await waitFor(() =>
      expect(api.listKpiMeasurementUnitsV6).toHaveBeenCalledWith({
        network_element_type: "UMF",
        page: 1,
        page_size: 20,
      }),
    );
    expect(await screen.findByText("媒体资源测量单元")).toBeDefined();
    expect(screen.getByText("20 基础")).toBeDefined();
    expect(screen.getByText("2 派生")).toBeDefined();
    expect(screen.getByText("唯一启停粒度")).toBeDefined();
  });

  it("切换 CSP 时按网元类型重新读取，不混用 UMF 数据", async () => {
    renderPage();
    await screen.findByText("媒体资源测量单元");

    await userEvent.click(screen.getByRole("radio", { name: "CSP" }), { pointerEventsCheck: 0 });

    await waitFor(() =>
      expect(api.listKpiMeasurementUnitsV6).toHaveBeenLastCalledWith({
        network_element_type: "CSP",
        page: 1,
        page_size: 20,
      }),
    );
    expect(await screen.findByText("CSP 媒体资源测量单元")).toBeDefined();
    expect(screen.queryByText("媒体资源测量单元")).toBeNull();
  });

  it("只在测量单元层启停，并携带当前 revision", async () => {
    vi.mocked(api.setKpiMeasurementInspectionEnabledV6).mockResolvedValue({
      ...umfUnit,
      inspection_enabled: false,
      revision: 4,
      notice: "只影响后续巡检，现有配置、团队关注和历史结果保留",
    });
    renderPage();

    await userEvent.click(await screen.findByRole("switch", { name: "停用 媒体资源测量单元" }));

    await waitFor(() =>
      expect(api.setKpiMeasurementInspectionEnabledV6).toHaveBeenCalledWith(
        "UMF",
        "MU_MEDIA",
        { expected_revision: 3, inspection_enabled: false },
      ),
    );
    expect(await screen.findByText("只影响后续巡检，现有配置、团队关注和历史结果保留")).toBeDefined();
    expect(screen.getByText("已停用 · 配置保留")).toBeDefined();
  });

  it("浏览者只读，不展示测量单元开关", async () => {
    authState.user = { username: "viewer", role: "viewer" };
    renderPage();

    expect(await screen.findByText("媒体资源测量单元")).toBeDefined();
    expect(screen.queryByRole("switch", { name: /媒体资源测量单元/ })).toBeNull();
  });

  it("不提供指标级巡检开关或批量确认绑定", async () => {
    renderPage();
    await screen.findByText("媒体资源测量单元");

    expect(screen.queryByRole("tab", { name: "关注指标" })).toBeNull();
    expect(screen.queryByText("只巡检你关注的 KPI")).toBeNull();
    expect(screen.queryByRole("button", { name: /批量确认/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(api.updateMeasurementResource).not.toHaveBeenCalled();
    expect(api.batchConfirmMeasurementBindings).not.toHaveBeenCalled();
  });

  it("历史 enabled=false 的已确认绑定仍可作为派生公式候选", async () => {
    vi.mocked(api.listMeasurementUnits).mockResolvedValue({
      total: 1,
      items: [{
        resource_id: "MU_MEDIA",
        name_zh: "媒体资源测量单元",
        name_en: "Media Resource Measurement Unit",
        filename_fragment: "media",
        enabled: false,
        metric_count: 1,
        unit_count: 1,
        confirmed_binding_count: 1,
        candidate_binding_count: 0,
        derived_count: 1,
      }],
    });
    vi.mocked(api.listMeasurementBindings).mockResolvedValue({
      total: 1,
      items: [{
        id: 8,
        raw_source_name: "历史停用媒体指标",
        base_source_name: "历史停用媒体指标",
        metric_resource_id: "ME_LEGACY_DISABLED",
        metric_resource_name_zh: "历史停用媒体指标",
        measurement_unit_id: "MU_MEDIA",
        measurement_unit_name_zh: "媒体资源测量单元",
        status: "confirmed",
        enabled: false,
        metric_is_manual: false,
        task_id: "task-kpi",
        source_file: "scope.csv",
        display_unit: "次",
      }],
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "派生指标" }));
    await screen.findByText("支持成功率和反向成功率模板");
    await userEvent.click(screen.getByRole("button", { name: /新建派生指标/ }));

    const dialog = await screen.findByRole("dialog", { name: "派生指标" });
    await userEvent.click(within(dialog).getByLabelText("测量单元"));
    await userEvent.click(await screen.findByText("媒体资源测量单元 / MU_MEDIA"));
    await waitFor(() => expect(api.listMeasurementBindings).toHaveBeenCalledWith({
      measurement_unit_id: "MU_MEDIA",
      status: "confirmed",
      search: undefined,
    }));

    await userEvent.click(within(dialog).getByLabelText("分子指标"));
    expect(await screen.findByText("历史停用媒体指标 / ME_LEGACY_DISABLED")).toBeDefined();
  });

  it("绑定关系页只读取 v6 诊断，不提供批量确认、勾选框或指标级开关", async () => {
    vi.mocked(api.listMeasurementBindings).mockResolvedValue({
      total: 1,
      items: [{
        id: 7,
        raw_source_name: "旧接口列",
        base_source_name: "旧接口列",
        metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
        metric_resource_name_zh: "媒体资源创建成功率",
        measurement_unit_id: "MU_MEDIA",
        measurement_unit_name_zh: "媒体资源测量单元",
        status: "candidate",
        enabled: true,
        metric_is_manual: false,
        task_id: "task-kpi",
        source_file: "scope.csv",
      }],
    });
    vi.mocked(api.listKpiMeasurementBindingsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [candidateBinding],
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));

    expect(await screen.findByText("待确认来源列")).toBeDefined();
    await waitFor(() => expect(api.listKpiMeasurementBindingsV6).toHaveBeenCalledWith({
      network_element_type: "UMF",
      page: 1,
      page_size: 10,
    }));
    expect(api.listMeasurementBindings).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /批量确认/ })).toBeNull();
    expect(screen.queryByText("启用状态")).toBeNull();
  });

  it("人工修正单条绑定携带当前 revision，并提交裁剪后的原因", async () => {
    vi.mocked(api.listKpiMeasurementBindingsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [candidateBinding],
    });
    vi.mocked(api.correctKpiMeasurementBindingV6).mockResolvedValue({
      ...candidateBinding,
      status: "confirmed",
      revision: 4,
      diagnostic: null,
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));
    await userEvent.click(await screen.findByRole("button", { name: "人工修正" }));
    const dialog = await screen.findByRole("dialog", { name: "单条修正绑定异常" });
    await userEvent.type(
      within(dialog).getByPlaceholderText("例如：人工核对源列后确认归属"),
      "  人工核对源列后确认归属  ",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "确认修正" }));

    await waitFor(() => expect(api.correctKpiMeasurementBindingV6).toHaveBeenCalledWith(
      "UMF",
      41,
      {
        expected_revision: 3,
        status: "confirmed",
        reason: "人工核对源列后确认归属",
      },
    ));
    expect(await screen.findByText("绑定异常已确认为有效")).toBeDefined();
    await waitFor(() => expect(api.listKpiMeasurementBindingsV6).toHaveBeenCalledTimes(2));
  });

  it("浏览者不能人工修正绑定异常", async () => {
    authState.user = { username: "viewer", role: "viewer" };
    vi.mocked(api.listKpiMeasurementBindingsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [candidateBinding],
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));

    expect(await screen.findByText("待确认来源列")).toBeDefined();
    expect(screen.queryByRole("button", { name: "人工修正" })).toBeNull();
    expect(screen.getAllByText("只读").length).toBeGreaterThan(0);
  });

  it("切换 CSP 后绑定关系只读取 CSP，不混入 UMF", async () => {
    const cspBinding = {
      ...candidateBinding,
      id: 42,
      network_element_type: "CSP" as const,
      measurement_unit_id: "MU_CSP_MEDIA",
      measurement_unit_name: "CSP 媒体资源测量单元",
      raw_source_name: "CSP 待确认来源列",
      revision: 1,
    };
    vi.mocked(api.listKpiMeasurementBindingsV6).mockImplementation(async (query) => ({
      total: 1,
      page: 1,
      page_size: 10,
      items: [query.network_element_type === "CSP" ? cspBinding : candidateBinding],
    }));

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));
    expect(await screen.findByText("待确认来源列")).toBeDefined();

    await userEvent.click(screen.getByRole("radio", { name: "CSP" }), { pointerEventsCheck: 0 });

    expect(await screen.findByText("CSP 待确认来源列")).toBeDefined();
    expect(screen.queryByText("待确认来源列")).toBeNull();
    await waitFor(() => expect(api.listKpiMeasurementBindingsV6).toHaveBeenLastCalledWith({
      network_element_type: "CSP",
      page: 1,
      page_size: 10,
    }));
  });

  it("绑定修正失败后刷新列表并保留当前绑定页上下文", async () => {
    vi.mocked(api.listKpiMeasurementBindingsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [candidateBinding],
    });
    vi.mocked(api.correctKpiMeasurementBindingV6).mockRejectedValue(new Error("版本冲突，请刷新后重试"));

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));
    await userEvent.click(await screen.findByRole("button", { name: "人工修正" }));
    const dialog = await screen.findByRole("dialog", { name: "单条修正绑定异常" });
    await userEvent.type(
      within(dialog).getByPlaceholderText("例如：人工核对源列后确认归属"),
      "人工核对",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "确认修正" }));

    expect(await screen.findByText("版本冲突，请刷新后重试")).toBeDefined();
    await waitFor(() => expect(api.listKpiMeasurementBindingsV6).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("tab", { name: "绑定关系" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("待确认来源列")).toBeDefined();
  });

  it("展示历史恢复逐对象审计和失败原因，并提供失败项重试入口", async () => {
    vi.mocked(api.listKpiLegacyRecoveryAuditsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 20,
      items: [failedRecoveryAudit],
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "恢复与归属" }));

    expect(await screen.findByText("ME_MEDIA_CREATION_SUCCESS_RATE")).toBeDefined();
    expect(screen.getByText("恢复失败")).toBeDefined();
    expect(screen.getByText("恢复时源记录缺失")).toBeDefined();
    expect(screen.getByRole("button", { name: "重试失败恢复项（1）" })).toBeDefined();
  });

  it("浏览者查看恢复与归属时只能查看，不显示重试或指定归属操作", async () => {
    authState.user = { username: "viewer", role: "viewer" };
    vi.mocked(api.listKpiLegacyRecoveryAuditsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 20,
      items: [failedRecoveryAudit],
    });
    vi.mocked(api.listKpiPendingAttributionsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 20,
      items: [pendingAttribution],
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "恢复与归属" }));

    expect(await screen.findByText("恢复时源记录缺失")).toBeDefined();
    expect(screen.queryByRole("button", { name: /重试失败恢复项/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "指定网元类型" })).toBeNull();
    expect(api.retryKpiLegacyRecoveryV6).not.toHaveBeenCalled();
    expect(api.resolveKpiPendingAttributionV6).not.toHaveBeenCalled();
  });

  it("重试失败恢复项后轮询操作，并以部分成功展示逐项结果", async () => {
    const secondAudit = {
      ...failedRecoveryAudit,
      audit_id: 92,
      source_key: "metric:UMF:MU_MEDIA:ME_MEDIA_MODIFICATION_SUCCESS_RATE",
      metric_resource_id: "ME_MEDIA_MODIFICATION_SUCCESS_RATE",
    };
    vi.mocked(api.listKpiLegacyRecoveryAuditsV6).mockResolvedValue({
      total: 2,
      page: 1,
      page_size: 20,
      items: [failedRecoveryAudit, secondAudit],
    });
    vi.mocked(api.retryKpiLegacyRecoveryV6).mockResolvedValue({
      operation_id: "op-recovery-1",
      status: "running",
    });
    vi.mocked(api.getKpiMaintenanceOperationV6).mockResolvedValue({
      operation_id: "op-recovery-1",
      operation_type: "legacy_recovery_retry",
      status: "partial_success",
      idempotency_key: "retry-operation-key",
      total_count: 2,
      succeeded_count: 1,
      failed_count: 1,
      pending_count: 0,
      items: [
        { target_id: "91", result: "succeeded" },
        { target_id: "92", result: "failed", error_code: "migration_row_error", error_message: "目标记录仍缺失" },
      ],
      created_at: "2026-11-05T03:08:00Z",
      completed_at: "2026-11-05T03:08:02Z",
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "恢复与归属" }));
    const retryButton = await screen.findByRole("button", { name: "重试失败恢复项（2）" });
    await userEvent.click(retryButton);

    await waitFor(() => expect(api.retryKpiLegacyRecoveryV6).toHaveBeenCalledTimes(1));
    const request = vi.mocked(api.retryKpiLegacyRecoveryV6).mock.calls[0][0];
    expect(request.audit_ids).toEqual([91, 92]);
    expect(request.idempotency_key.length).toBeGreaterThanOrEqual(8);
    expect(api.getKpiMaintenanceOperationV6).toHaveBeenCalledWith("op-recovery-1");

    expect(await screen.findByText("部分成功")).toBeDefined();
    expect(screen.getByText("成功 1")).toBeDefined();
    expect(screen.getByText("失败 1")).toBeDefined();
    expect(screen.getByText(/目标记录仍缺失/)).toBeDefined();
    await waitFor(() => expect(api.listKpiLegacyRecoveryAuditsV6).toHaveBeenCalledTimes(2));
  });

  it("待归属配置必须显式选择网元类型，不能默认猜测", async () => {
    vi.mocked(api.listKpiPendingAttributionsV6).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 20,
      items: [pendingAttribution],
    });
    vi.mocked(api.resolveKpiPendingAttributionV6).mockResolvedValue({
      operation_id: "op-pending-1",
      status: "queued",
    });
    vi.mocked(api.getKpiMaintenanceOperationV6).mockResolvedValue({
      operation_id: "op-pending-1",
      operation_type: "pending_attribution_resolve",
      status: "succeeded",
      idempotency_key: "pending-resolve-operation-key",
      total_count: 1,
      succeeded_count: 1,
      failed_count: 0,
      pending_count: 0,
      items: [{ target_id: "44", result: "succeeded" }],
      created_at: "2026-11-05T03:08:00Z",
      completed_at: "2026-11-05T03:08:01Z",
    });

    renderPage();
    await screen.findByText("媒体资源测量单元");
    await userEvent.click(screen.getByRole("tab", { name: "恢复与归属" }));

    expect(await screen.findByText("metric:unknown:ME_PENDING_MEDIA")).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "指定网元类型" }));
    const dialog = await screen.findByRole("dialog", { name: "指定待归属配置" });
    await userEvent.click(within(dialog).getByRole("button", { name: "确认归属" }));
    expect(await within(dialog).findByText("请选择网元类型")).toBeDefined();
    expect(api.resolveKpiPendingAttributionV6).not.toHaveBeenCalled();

    const typeSelect = within(dialog).getByRole("combobox", { name: "选择网元类型" });
    const selector = typeSelect.closest(".ant-select")?.querySelector(".ant-select-selector");
    expect(selector).not.toBeNull();
    fireEvent.mouseDown(selector as Element);
    const umfOption = document.querySelector<HTMLElement>('.ant-select-item-option[title="UMF"]');
    expect(umfOption).not.toBeNull();
    await userEvent.click(umfOption as HTMLElement);
    await waitFor(() => expect(typeSelect.closest(".ant-select")?.textContent).toContain("UMF"));
    await userEvent.click(within(dialog).getByRole("button", { name: "确认归属" }));

    await waitFor(() => expect(api.resolveKpiPendingAttributionV6).toHaveBeenCalledTimes(1));
    const [pendingId, request] = vi.mocked(api.resolveKpiPendingAttributionV6).mock.calls[0];
    expect(pendingId).toBe(44);
    expect(request.network_element_type).toBe("UMF");
    expect(request.idempotency_key.length).toBeGreaterThanOrEqual(8);
    expect(await screen.findByText("待归属配置已完成归属")).toBeDefined();
    await waitFor(() => expect(api.listKpiPendingAttributionsV6).toHaveBeenCalledTimes(2));
  });

  it("从已完成任务进入唯一的团队关注查看入口", async () => {
    renderPage();
    await waitFor(() => expect(api.listTasks).toHaveBeenCalledWith({ status: "completed", page_size: 20 }));

    await userEvent.click(screen.getByRole("combobox", { name: "查看团队关注" }));
    await userEvent.click(await screen.findByText("KPI 巡检任务 · task-kpi"));

    expect((await screen.findByTestId("kpi-route")).textContent).toBe("task-kpi");
    expect(api.updateMeasurementResource).not.toHaveBeenCalled();
  });
});
