import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type MeasurementBinding, type MeasurementResource } from "../api/http";
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
  },
}));

const focusMetric: MeasurementResource = {
  resource_id: "ME_FOCUS_E2E",
  kind: "me",
  name_zh: "关注功能测试指标",
  name_en: "Focus E2E Metric",
  enabled: true,
  is_manual: false,
  display_order: 10,
  metric_group: "测试分组",
  direction: "neutral",
  importance: "normal",
  warning_threshold: null,
  critical_threshold: null,
  source: "preset",
  origin_task_id: null,
  origin_file: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const binding: MeasurementBinding = {
  id: 1,
  metric_resource_id: "me-001",
  metric_resource_name_zh: "成功率",
  measurement_unit_id: "mu-001",
  measurement_unit_name_zh: "测量单元A",
  raw_source_name: "raw",
  base_source_name: "base",
  display_unit: null,
  status: "confirmed",
  enabled: true,
  task_id: "task-001",
  source_file: "a.csv",
  metric_is_manual: false,
};

function renderPage() {
  return render(
    <App>
      <MeasurementUnitsPage />
    </App>,
  );
}

describe("MeasurementUnitsPage 权限边界", () => {
  beforeEach(() => {
    authState.user = null;
    vi.mocked(api.listMeasurementUnits).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(api.listMeasurementBindings).mockResolvedValue({ total: 1, items: [binding] });
    vi.mocked(api.listMeasurementResources).mockResolvedValue({ total: 0, items: [] });
  });

  it("浏览者查看绑定关系时不请求管理员专属的指标资源", async () => {
    authState.user = { username: "viewer", role: "viewer" };

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));

    await waitFor(() => expect(api.listMeasurementBindings).toHaveBeenCalled());
    await screen.findByText("base");
    expect(api.listMeasurementResources).not.toHaveBeenCalled();
  });

  it("浏览者不展示新建派生指标入口", async () => {
    authState.user = { username: "viewer", role: "viewer" };

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "派生指标" }));

    expect(screen.queryByRole("button", { name: /新建派生指标/ })).toBeNull();
  });

  it("管理员可在关注指标页取消关注并看到状态收敛", async () => {
    authState.user = { username: "admin", role: "admin" };
    let enabled = true;
    vi.mocked(api.listMeasurementResources).mockImplementation(async (query) => {
      if (query.kind === "me" && query.search === "关注功能测试指标") {
        return { total: 1, items: [{ ...focusMetric, enabled }] };
      }
      return { total: 0, items: [] };
    });
    vi.mocked(api.updateMeasurementResource).mockImplementation(async (_resourceId, payload) => {
      enabled = payload.enabled ?? enabled;
      return { ...focusMetric, enabled };
    });

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "关注指标" }));
    await userEvent.type(screen.getByPlaceholderText("搜索指标 ID / 中文名 / 英文名"), "关注功能测试指标{enter}");
    await screen.findByText("关注功能测试指标");

    const metricRow = screen.getByText("关注功能测试指标").closest("tr");
    expect(metricRow).not.toBeNull();
    await userEvent.click(within(metricRow as HTMLElement).getByRole("button", { name: "取消关注" }));

    await waitFor(() =>
      expect(api.updateMeasurementResource).toHaveBeenCalledWith("ME_FOCUS_E2E", { enabled: false }),
    );
    await waitFor(() =>
      expect(within(metricRow as HTMLElement).getByRole("button", { name: "关注" })).toBeTruthy(),
    );
  });

  it("关注指标搜索只触发一次列表请求", async () => {
    authState.user = { username: "admin", role: "admin" };
    vi.mocked(api.listMeasurementResources).mockResolvedValue({ total: 0, items: [] });

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "关注指标" }));
    await waitFor(() => expect(api.listMeasurementResources).toHaveBeenCalledTimes(1));
    vi.mocked(api.listMeasurementResources).mockClear();

    await userEvent.type(screen.getByPlaceholderText("搜索指标 ID / 中文名 / 英文名"), "关注功能测试指标{enter}");

    await waitFor(() => expect(api.listMeasurementResources).toHaveBeenCalledTimes(1));
    expect(api.listMeasurementResources).toHaveBeenCalledWith(expect.objectContaining({
      kind: "me",
      search: "关注功能测试指标",
      page: 1,
      page_size: 20,
    }));
  });

  it("管理员仍可读取指标资源治理信息", async () => {
    authState.user = { username: "admin", role: "admin" };

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));

    await waitFor(() => expect(api.listMeasurementResources).toHaveBeenCalled());
  });

  it("浏览者可打开维护配置页签查看指标配置", async () => {
    authState.user = { username: "viewer", role: "viewer" };
    vi.mocked(api.listKpiMetricMaintenanceConfigs).mockResolvedValue({ total: 0, items: [], page: 1, page_size: 20 });
    vi.mocked(api.listKpiMeasurementDerived).mockResolvedValue({ total: 0, items: [], page: 1, page_size: 20 });

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "维护配置" }));

    expect(await screen.findByRole("heading", { name: "指标维护配置" })).toBeDefined();
    await waitFor(() => expect(api.listKpiMetricMaintenanceConfigs).toHaveBeenCalledWith({ page: 1, page_size: 200 }));
    expect(api.listKpiMeasurementDerived).toHaveBeenCalledWith({ page: 1, page_size: 200 });
  });
});
