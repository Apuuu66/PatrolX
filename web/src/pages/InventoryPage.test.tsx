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
    deleteInventoryDevice: vi.fn(),
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
      page_size: 10,
      items: devices,
    });
    vi.mocked(api.listInventoryQualityIssues).mockResolvedValue({
      total: issues.length,
      page: 1,
      page_size: 10,
      items: issues,
    });
  });

  it("filters quality issues by type and province and exposes traceability links", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "质量问题" }));
    expect(await screen.findByText("版本值冲突")).toBeTruthy();
    expect(api.listInventoryQualityIssues).toHaveBeenCalledWith({ page: 1, page_size: 10 });

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
    // 设备台账默认分页 10 条（contracts/ui-baseline §4.4、T039）。
    expect(api.listInventoryDevices).toHaveBeenCalledWith({
      page: 1,
      page_size: 10,
      province: undefined,
      operator: undefined,
      quality_status: "all",
    });
    fireEvent.click(screen.getByText("GD-GZ-Core-01"));
    expect(await screen.findByText("设备详情测试")).toBeTruthy();
  });

  it("最近观测列标注时间来源口径，避免把兜底时间当成设备执行时间", async () => {
    renderPage();

    // 列表接口不返回逐行时间来源，按契约在列上标注口径，悬停给出说明（FR-010、SC-004）。
    const header = await screen.findByRole("columnheader", { name: /最近观测/ });
    const marker = within(header).getByTestId("inventory-last-seen-source");
    expect(marker.textContent).toContain("执行时间口径");

    fireEvent.mouseEnter(marker);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain("优先取包内 LST ME 设备执行时间，解析不到时回退任务完成时间");
  });

  it("管理员可从设备列表直接物理删除台账", async () => {
    vi.mocked(api.deleteInventoryDevice).mockResolvedValue(undefined);
    renderPage();

    const row = (await screen.findByText("GD-GZ-Core-01")).closest("tr");
    expect(row).toBeTruthy();
    if (!row) throw new Error("device row is missing");

    const reloadCountBefore = vi.mocked(api.listInventoryDevices).mock.calls.length;
    fireEvent.click(within(row).getByRole("button", { name: /^删\s*除$/ }));

    const confirmText = await screen.findByText("确认删除该设备台账？");
    const popover = confirmText.closest(".ant-popover");
    expect(popover).toBeTruthy();
    if (!popover) throw new Error("delete popover is missing");
    expect(within(popover as HTMLElement).getByText("将物理删除设备、全部观测记录和版本历史。")).toBeTruthy();

    fireEvent.click(within(popover as HTMLElement).getByRole("button", { name: /^删\s*除$/ }));
    await waitFor(() => {
      expect(api.deleteInventoryDevice).toHaveBeenCalledWith("gd-gz-core-01");
    });
    await waitFor(() => {
      expect(vi.mocked(api.listInventoryDevices).mock.calls.length).toBeGreaterThan(reloadCountBefore);
    });
  });

});
