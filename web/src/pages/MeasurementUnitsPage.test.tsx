import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type MeasurementBinding } from "../api/http";
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
  },
}));

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

  it("管理员仍可读取指标资源治理信息", async () => {
    authState.user = { username: "admin", role: "admin" };

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "绑定关系" }));

    await waitFor(() => expect(api.listMeasurementResources).toHaveBeenCalled());
  });
});
