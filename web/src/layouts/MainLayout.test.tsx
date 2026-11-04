import { render, screen, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiMe, setSession } from "../api/auth";
import { AuthProvider } from "../auth/AuthContext";
import { MainLayout, resolvePageTitle } from "./MainLayout";

vi.mock("../api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/auth")>();
  return { ...actual, apiMe: vi.fn() };
});

function renderLayout(path: string) {
  return render(
    <App>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            element={
              <AuthProvider>
                <MainLayout />
              </AuthProvider>
            }
          >
            <Route index element={<div>页面内容</div>} />
            <Route path="*" element={<div>页面内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </App>,
  );
}

describe("MainLayout", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(apiMe).mockResolvedValue({ username: "admin", role: "admin" });
  });

  it("按路由解析顶栏标题，不重复产品名", () => {
    expect(resolvePageTitle("/")).toBe("巡检任务");
    expect(resolvePageTitle("/tasks")).toBe("巡检任务");
    expect(resolvePageTitle("/tasks/task-a")).toBe("任务详情");
    expect(resolvePageTitle("/tasks/task-a/rules/log.filter")).toBe("规则详情");
    expect(resolvePageTitle("/tasks/task-a/report")).toBe("巡检报告");
    expect(resolvePageTitle("/inventory/devices/dev-1")).toBe("设备详情");
    expect(resolvePageTitle("/inspectors")).toBe("规则管理");
    expect(resolvePageTitle("/unknown")).toBe("巡检任务");
  });

  it("顶栏左侧展示当前页面标题，右侧保留用户区", () => {
    renderLayout("/inspectors");

    expect(screen.getByTestId("app-page-title").textContent).toBe("规则管理");
    expect(screen.queryByText("系统维护巡检平台")).toBeNull();
  });

  it("访客模式下登录按钮不是主按钮权重", () => {
    renderLayout("/");

    const login = screen.getByRole("button", { name: /登\s*录/ });
    expect(login.classList.contains("app-button")).toBe(true);
    expect(login.classList.contains("app-button--small")).toBe(true);
    expect(login.classList.contains("app-button--primary")).toBe(false);
  });

  it("侧边栏使用深色导航底，并保留可访问的当前菜单项", () => {
    setSession("token-for-test", { username: "admin", role: "admin" });
    const { container } = renderLayout("/inspectors");

    const sider = container.querySelector(".app-sider") as HTMLElement;
    expect(sider).not.toBeNull();
    expect(container.querySelector(".app-nav")).not.toBeNull();
    const item = within(sider).getByRole("link", { name: "规则管理" });
    expect(item.classList.contains("app-nav-link")).toBe(true);
    expect(item.classList.contains("is-selected")).toBe(true);
    expect(item.getAttribute("aria-current")).toBe("page");
  });
});
