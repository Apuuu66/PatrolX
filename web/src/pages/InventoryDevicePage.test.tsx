import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type InventoryDevice, type InventoryObservation, type InventoryVersionPoint } from "../api/http";
import { InventoryDevicePage } from "./InventoryDevicePage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    getInventoryDevice: vi.fn(),
    getInventoryVersionHistory: vi.fn(),
    listInventoryObservations: vi.fn(),
  },
}));

const device: InventoryDevice = {
  device_id: "gd-gz-core-01",
  province: "广东省",
  operator: "移动",
  site_key: "广东省|移动",
  device_name: "GD-GZ-Core-01",
  current_version: "V900R021C10SPC100",
  current_version_observed_at: "2026-09-27T10:20:31Z",
  current_version_task_id: "task-current",
  first_seen_at: "2026-09-25T10:20:31Z",
  last_seen_at: "2026-09-27T10:20:31Z",
  observation_count: 3,
  site_change_count: 1,
  has_site_conflict: true,
  quality_issue_types: ["site_ownership_change"],
};

const versionHistory: InventoryVersionPoint[] = [
  {
    observed_at: "2026-09-27T10:20:31Z",
    task_id: "task-current",
    version_status: "ok",
    raw_version: "V900R021C10SPC100",
    direction: "upgrade",
    has_gap: false,
  },
  {
    observed_at: "2026-09-26T10:20:31Z",
    task_id: "task-downgrade",
    version_status: "ok",
    raw_version: "V900R021C10SPC090",
    direction: "downgrade",
    has_gap: true,
  },
  {
    observed_at: "2026-09-25T10:20:31Z",
    task_id: "task-unchanged",
    version_status: "ok",
    raw_version: "V900R021C10SPC090",
    direction: "unchanged",
    has_gap: false,
  },
];

const observations: InventoryObservation[] = [
  {
    observation_id: "obs-001",
    task_id: "task-current",
    task_status: "completed",
    observed_at: "2026-09-27T10:20:31Z",
    province: "广东省",
    operator: "移动",
    site_key: "广东省|移动",
    device_name: "GD-GZ-Core-01",
    identity_status: "ok",
    version_status: "ok",
    raw_version: "V900R021C10SPC100",
    version_source_files: ["config/LST ME.txt"],
    conflicts: [],
    snapshot: {},
  },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/inventory/devices/gd-gz-core-01"]}>
      <Routes>
        <Route path="/inventory/devices/:deviceId" element={<InventoryDevicePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("InventoryDevicePage", () => {
  beforeEach(() => {
    vi.mocked(api.getInventoryDevice).mockResolvedValue(device);
    vi.mocked(api.getInventoryVersionHistory).mockResolvedValue({
      total: versionHistory.length,
      page: 1,
      page_size: 20,
      items: versionHistory,
    });
    vi.mocked(api.listInventoryObservations).mockResolvedValue({
      total: observations.length,
      page: 1,
      page_size: 20,
      items: observations,
    });
  });

  it("renders version direction, gap, current-version source and observation source", async () => {
    renderPage();

    expect(await screen.findByText("升级")).toBeTruthy();
    expect(screen.getByText("降级")).toBeTruthy();
    expect(screen.getByText("未变化")).toBeTruthy();
    expect(screen.getByText("有缺口")).toBeTruthy();
    expect(screen.getAllByText("V900R021C10SPC100").length).toBeGreaterThan(0);
    expect(screen.getByText("config/LST ME.txt")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "task-current" }).length).toBeGreaterThan(0);
    expect(api.getInventoryVersionHistory).toHaveBeenCalledWith("gd-gz-core-01", { page: 1, page_size: 20 });
    expect(api.listInventoryObservations).toHaveBeenCalledWith("gd-gz-core-01", {
      page: 1,
      page_size: 20,
      order: "desc",
    });
  });
});
