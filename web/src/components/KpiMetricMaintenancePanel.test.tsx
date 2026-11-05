import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type KpiMeasurementDerived, type KpiMetricMaintenanceConfig } from "../api/http";
import { KpiMetricMaintenancePanel } from "./KpiMetricMaintenancePanel";

const authState = vi.hoisted(() => ({
  role: "viewer" as "viewer" | "admin",
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { username: "tester", role: authState.role }, canWrite: authState.role === "admin" }),
}));

const config: KpiMetricMaintenanceConfig = {
  measurement_unit_id: "MU_CALL",
  metric_resource_id: "ME_RATE",
  name_zh: "呼叫成功率",
  role: "derived",
  direction: "higher_better",
  warning_threshold: 99,
  critical_threshold: 98,
  daily_aggregation: "latest",
  daily_change_threshold: 0.2,
  daily_change_threshold_unit: "pp",
  is_percentage: true,
  zero_semantics: "unknown",
  consistency_tolerance: 0.2,
  object_match_mode: "exact",
  enabled: true,
  config_source: "legacy_resource",
  updated_at: "2026-11-05T02:00:00Z",
};

const derived: KpiMeasurementDerived = {
  id: 8,
  measurement_unit_id: "MU_CALL",
  metric_resource_id: "ME_RATE",
  numerator_metric_id: "ME_SUCCESS",
  denominator_metric_id: "ME_TOTAL",
  template: "success_rate",
  enabled: true,
  metric_resource_name_zh: "呼叫成功率",
  numerator_metric_name_zh: "成功次数",
  denominator_metric_name_zh: "请求次数",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-05T02:00:00Z",
};

function baseConfig(metricResourceId: string, nameZh: string): KpiMetricMaintenanceConfig {
  return {
    ...config,
    metric_resource_id: metricResourceId,
    name_zh: nameZh,
    role: "base",
    daily_aggregation: "sum",
    daily_change_threshold: null,
    daily_change_threshold_unit: "auto",
    config_source: "custom",
  };
}

function renderPanel() {
  return render(
    <App>
      <KpiMetricMaintenancePanel />
    </App>,
  );
}

describe("KpiMetricMaintenancePanel", () => {
  beforeEach(() => {
    authState.role = "viewer";
    vi.spyOn(api, "listKpiMetricMaintenanceConfigs").mockResolvedValue({ total: 1, items: [config], page: 1, page_size: 20 });
    vi.spyOn(api, "listKpiMeasurementDerived").mockResolvedValue({ total: 1, items: [derived], page: 1, page_size: 20 });
    vi.spyOn(api, "listKpiMetricMaintenanceAudits").mockResolvedValue({ total: 0, items: [], page: 1, page_size: 20 });
    vi.spyOn(api, "updateKpiMetricMaintenanceConfig").mockResolvedValue(config);
    vi.spyOn(api, "updateKpiMeasurementDerived").mockResolvedValue(derived);
  });

  afterEach(() => {
    vi.mocked(api.listKpiMetricMaintenanceConfigs).mockRestore();
    vi.mocked(api.listKpiMeasurementDerived).mockRestore();
    vi.mocked(api.listKpiMetricMaintenanceAudits).mockRestore();
    vi.mocked(api.updateKpiMetricMaintenanceConfig).mockRestore();
    vi.mocked(api.updateKpiMeasurementDerived).mockRestore();
  });

  it("浏览者可查看维护配置与聚合公式但不能编辑", async () => {
    renderPanel();

    const configTable = await screen.findByRole("table", { name: "指标维护配置" });
    expect(within(configTable).getByText("呼叫成功率")).toBeDefined();
    expect(within(configTable).getByText("聚合指标")).toBeDefined();
    expect(screen.getByText("基础与聚合指标配置")).toBeDefined();
    const derivedTable = screen.getByRole("table", { name: "聚合指标配置" });
    expect(screen.getByText("聚合指标公式")).toBeDefined();
    expect(within(derivedTable).getByText("成功次数 / 请求次数 × 100")).toBeDefined();
    expect(screen.queryByRole("button", { name: "编辑维护配置" })).toBeNull();
    expect(screen.queryByRole("button", { name: "编辑聚合配置" })).toBeNull();
  });

  it("管理员更新维护配置并刷新审计", async () => {
    authState.role = "admin";
    vi.mocked(api.listKpiMetricMaintenanceAudits).mockResolvedValue({ total: 0, items: [], page: 1, page_size: 20 });
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "编辑维护配置" }));
    const dialog = screen.getByRole("dialog");
    const warningInput = within(dialog).getByLabelText("预警阈值");
    await userEvent.clear(warningInput);
    await userEvent.type(warningInput, "98.5");
    await userEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => expect(api.updateKpiMetricMaintenanceConfig).toHaveBeenCalledWith(
      "MU_CALL",
      "ME_RATE",
      expect.objectContaining({ warning_threshold: 98.5 }),
    ));
  });

  it("管理员更新聚合公式并保留独立指标标识", async () => {
    authState.role = "admin";
    vi.mocked(api.listKpiMetricMaintenanceConfigs).mockResolvedValue({
      total: 3,
      items: [
        config,
        baseConfig("ME_SUCCESS", "成功次数"),
        baseConfig("ME_TOTAL", "请求次数"),
      ],
      page: 1,
      page_size: 20,
    });
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "编辑聚合配置" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText("分子指标"));
    await userEvent.click(await screen.findByRole("option", { name: /成功次数/ }));
    await userEvent.click(within(dialog).getByLabelText("分母指标"));
    await userEvent.click(await screen.findByRole("option", { name: /请求次数/ }));
    await userEvent.click(within(dialog).getByLabelText("反向成功率"));
    await userEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => expect(api.updateKpiMeasurementDerived).toHaveBeenCalledWith(
      8,
      expect.objectContaining({
        numerator_metric_id: "ME_SUCCESS",
        denominator_metric_id: "ME_TOTAL",
        template: "reverse_success_rate",
      }),
    ));
  });
});
