import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type InspectorState } from "../api/http";
import { apiMe, setSession } from "../api/auth";
import { AuthProvider } from "../auth/AuthContext";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
import { InspectorsPage } from "./InspectorsPage";

vi.mock("../api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/auth")>();
  return { ...actual, apiMe: vi.fn() };
});

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listInspectorStates: vi.fn(),
    setInspectorStateEnabled: vi.fn(),
  },
}));

function makeInspector(overrides: Partial<InspectorState> = {}): InspectorState {
  return {
    code: "config.a",
    name: "配置一致性",
    category: "config",
    priority: 1,
    enabled: true,
    updated_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    ...overrides,
  } as InspectorState;
}

function renderPage() {
  return render(
    <App>
      <AuthProvider>
        <InspectorsPage />
      </AuthProvider>
    </App>,
  );
}

describe("InspectorsPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // 管理员会话：启停开关可交互（apiMe 校验保持管理员身份）。
    setSession("token-for-test", { username: "admin", role: "admin" });
    vi.mocked(apiMe).mockResolvedValue({ username: "admin", role: "admin" });
  });

  it("更新时间以相对时间呈现并保留完整时间 Tooltip", async () => {
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [makeInspector()],
      total: 1,
      page: 1,
      page_size: 10,
    });

    renderPage();

    const updatedAt = await screen.findByTestId("inspector-updated-at");
    expect(updatedAt.textContent).toMatch(/小时前/);
    expect(updatedAt.classList.contains("tabular-nums")).toBe(true);
  });

  it("更新时间列支持排序：点击表头按时间重排", async () => {
    const older = makeInspector({
      code: "config.old",
      updated_at: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    });
    const newer = makeInspector({
      code: "config.new",
      updated_at: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    });
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [older, newer],
      total: 2,
      page: 1,
      page_size: 10,
    });

    renderPage();

    const header = (await screen.findByText("更新时间")).closest("th");
    expect(header).not.toBeNull();
    expect(header?.className).toContain("ant-table-column-has-sorters");

    const user = userEvent.setup();
    await user.click(header as HTMLElement);

    // 点击表头按时间升序重排（接口默认顺序为旧 → 新）。
    await waitFor(() => {
      const codes = screen.getAllByText(/^config\./).map((node) => node.textContent);
      expect(codes).toEqual(["config.old", "config.new"]);
    });
  });

  it("密度切换默认紧凑，切换到舒适后写入本地偏好且表体行高联动", async () => {
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [makeInspector()],
      total: 1,
      page: 1,
      page_size: 10,
    });

    renderPage();

    const table = (await screen.findByText("config.a")).closest("table");
    const tableWrapper = table?.closest(".inspectors-table");
    expect(tableWrapper?.classList.contains("density-compact")).toBe(true);
    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "舒适" }));

    expect(screen.getByRole("button", { name: "舒适" }).getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBe("comfortable");
    await waitFor(() => {
      expect(tableWrapper?.classList.contains("density-comfortable")).toBe(true);
    });
  });

  it("启停失败时回滚到变更前状态并给出失败原因", async () => {
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [makeInspector()],
      total: 1,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.setInspectorStateEnabled).mockRejectedValue(new Error("规则状态更新被拒绝"));

    renderPage();

    const toggle = await screen.findByRole("switch", { name: "config.a 启停状态" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");

    const user = userEvent.setup();
    await user.click(toggle);

    await waitFor(() => {
      expect(api.setInspectorStateEnabled).toHaveBeenCalledWith("config.a", false);
    });
    await waitFor(() => {
      expect(document.querySelector(".ant-message")).not.toBeNull();
    });
    expect(document.body.textContent).toContain("规则状态更新被拒绝");
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("启停请求进行中禁用重复触发，成功后保持更新结果", async () => {
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [makeInspector()],
      total: 1,
      page: 1,
      page_size: 10,
    });
    let resolveUpdate: ((value: InspectorState) => void) | undefined;
    vi.mocked(api.setInspectorStateEnabled).mockImplementation(
      () =>
        new Promise<InspectorState>((resolve) => {
          resolveUpdate = resolve;
        }),
    );

    renderPage();

    const toggle = await screen.findByRole("switch", { name: "config.a 启停状态" });
    const user = userEvent.setup();
    await user.click(toggle);

    await waitFor(() => {
      expect(toggle.classList.contains("ant-switch-loading")).toBe(true);
    });
    expect(toggle.disabled).toBe(true);

    resolveUpdate?.(makeInspector({ enabled: false }));
    await waitFor(() => {
      expect(toggle.getAttribute("aria-checked")).toBe("false");
    });
    expect(toggle.disabled).toBe(false);
  });

  it("规则编码使用等宽字体并保留复制入口", async () => {
    vi.mocked(api.listInspectorStates).mockResolvedValue({
      items: [makeInspector()],
      total: 1,
      page: 1,
      page_size: 10,
    });

    renderPage();

    const code = await screen.findByText("config.a");
    expect(code.closest(".inspectors-code")).not.toBeNull();
    const row = code.closest("tr");
    expect(within(row as HTMLElement).getByRole("button", { name: /复制|copy/i })).toBeDefined();
  });
});
