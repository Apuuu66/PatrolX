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

    // AntD 会在两字中文按钮中插入空格，名称为"登 录"。
    const login = screen.getByRole("button", { name: /登\s*录/ });
    expect(login.classList.contains("ant-btn-primary")).toBe(false);
    expect(login.classList.contains("ant-btn-default")).toBe(true);
  });

  it("侧边栏使用浅色底与选中态指示，并保留键盘可达的菜单项", () => {
    setSession("token-for-test", { username: "admin", role: "admin" });
    const { container } = renderLayout("/inspectors");

    const sider = container.querySelector(".app-sider") as HTMLElement;
    expect(sider).not.toBeNull();
    const item = within(sider).getByText("规则管理").closest("li") as HTMLElement;
    expect(item.classList.contains("ant-menu-item-selected")).toBe(true);
    expect(item.getAttribute("tabindex")).not.toBeNull();
    // 选中态由淡色底 + 左侧指示条 + 品牌深色文字表达，不使用实心主色块。
    expect(item.getAttribute("style") ?? "").not.toContain("22, 119, 255");
  });
});
