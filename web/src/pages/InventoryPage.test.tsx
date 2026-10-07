import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  type InventoryDevice,
  type InventoryQualityIssue,
} from "../api/http";
import { InventoryPage } from "./InventoryPage";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { username: "admin", role: "admin" },
    login: vi.fn(),
    logout: vi.fn(),
    canWrite: true,
  }),
}));

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listInventoryDevices: vi.fn(),
    listInventoryQualityIssues: vi.fn(),
    createInventoryDevice: vi.fn(),
  },
}));

const devices: InventoryDevice[] = [
  {
    device_id: "gd-gz-core-01",
    province: "广东省",
    operator: "移动",
    site_key: "广东省|移动",
    device_name: "GD-GZ-Core-01",
    current_version: null,
    current_version_observed_at: null,
    current_version_task_id: null,
    first_seen_at: "2026-09-25T10:20:31Z",
    last_seen_at: "2026-09-27T10:20:31Z",
    observation_count: 1,
    site_change_count: 0,
    has_site_conflict: false,
    quality_issue_types: ["missing_version"],
  },
];

const issues: InventoryQualityIssue[] = [
  {
    issue_id: "issue-001",
    issue_type: "version_conflict",
    message: "版本值冲突",
    task_id: "task-conflict",
    device_id: "gd-gz-core-01",
    province: "广东省",
    operator: "移动",
    detected_at: "2026-09-27T10:20:31Z",
    detail: {},
  },
];

function renderPage() {
  return render(
    <App>
      <MemoryRouter initialEntries={["/inventory"]}>
        <Routes>
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/inventory/devices/:deviceId" element={<div>设备详情测试</div>} />
        </Routes>
      </MemoryRouter>
    </App>,
  );
}

describe("InventoryPage", () => {
  beforeEach(() => {
    vi.mocked(api.listInventoryDevices).mockResolvedValue({
      total: devices.length,
      page: 1,
      page_size: 20,
      items: devices,
    });
    vi.mocked(api.listInventoryQualityIssues).mockResolvedValue({
      total: issues.length,
      page: 1,
      page_size: 20,
      items: issues,
    });
  });

  it("filters quality issues by type and province and exposes traceability links", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "质量问题" }));
    expect(await screen.findByText("版本值冲突")).toBeTruthy();
    expect(api.listInventoryQualityIssues).toHaveBeenCalledWith({ page: 1, page_size: 20 });

    const qualityPanel = await screen.findByRole("tabpanel", { name: "质量问题" });
    const typeSelect = (await within(qualityPanel).findByText("按类型筛选")).closest(".ant-select");
    expect(typeSelect).toBeTruthy();
    if (!typeSelect) throw new Error("quality type select is missing");
    const typeSelectSelector = typeSelect.querySelector(".ant-select-selector");
    expect(typeSelectSelector).toBeTruthy();
    if (!typeSelectSelector) throw new Error("quality type select selector is missing");
    fireEvent.mouseDown(typeSelectSelector);
    const versionMissingOption = (await screen.findByTitle("版本缺失")).closest(".ant-select-item-option");
    expect(versionMissingOption).toBeTruthy();
    if (!versionMissingOption) throw new Error("quality type option is missing");
    fireEvent.click(versionMissingOption);
    await waitFor(() => {
      expect(api.listInventoryQualityIssues).toHaveBeenLastCalledWith(
        expect.objectContaining({ issue_type: "missing_version" }),
      );
    });

    fireEvent.change(within(qualityPanel).getByPlaceholderText("按省份筛选"), { target: { value: "广东省" } });
    await waitFor(() => {
      expect(api.listInventoryQualityIssues).toHaveBeenLastCalledWith(
        expect.objectContaining({ issue_type: "missing_version", province: "广东省" }),
      );
    });
    expect(screen.getByRole("link", { name: "任务" }).getAttribute("href")).toBe("/tasks/task-conflict");
    expect(screen.getByRole("link", { name: "设备" }).getAttribute("href")).toBe("/inventory/devices/gd-gz-core-01");
  });

  it("opens device detail from the device table", async () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "设备台账" })).toBeTruthy();
    expect(await screen.findByText("GD-GZ-Core-01")).toBeTruthy();
    fireEvent.click(screen.getByText("GD-GZ-Core-01"));
    expect(await screen.findByText("设备详情测试")).toBeTruthy();
  });

  it("creates a manual device from the ledger form", async () => {
    vi.mocked(api.createInventoryDevice).mockResolvedValue({ ...devices[0], device_id: "manual-001", device_name: "JS-NJ-Manual-01" });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /新增设备/ }));
    fireEvent.change(screen.getByLabelText("省份"), { target: { value: "江苏省" } });
    fireEvent.change(screen.getByLabelText("运营商"), { target: { value: "移动" } });
    fireEvent.change(screen.getByLabelText("设备名称"), { target: { value: "JS-NJ-Manual-01" } });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "手工登记" } });
    fireEvent.click(screen.getByRole("button", { name: /^创\s*建$/ }));

    await waitFor(() => {
      expect(api.createInventoryDevice).toHaveBeenCalledWith({
        province: "江苏省",
        operator: "移动",
        device_name: "JS-NJ-Manual-01",
        remark: "手工登记",
      });
    });
    expect(await screen.findByText("设备已创建")).toBeTruthy();
  });
});
