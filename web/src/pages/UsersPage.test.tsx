import { render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/http";
import { UsersPage } from "./UsersPage";

// 用可变状态模拟不同登录身份；vi.hoisted 保证 mock 工厂可以安全引用。
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
    listUsers: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <App>
      <UsersPage />
    </App>,
  );
}

describe("UsersPage", () => {
  beforeEach(() => {
    authState.user = null;
    vi.mocked(api.listUsers).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 });
  });

  it("访客不请求用户列表，仅提示需要管理员", () => {
    renderPage();

    expect(screen.getByText("仅管理员可以使用用户管理")).toBeTruthy();
    expect(api.listUsers).not.toHaveBeenCalled();
  });

  it("浏览者不请求用户列表，仅提示需要管理员", () => {
    authState.user = { username: "viewer", role: "viewer" };

    renderPage();

    expect(screen.getByText("仅管理员可以使用用户管理")).toBeTruthy();
    expect(api.listUsers).not.toHaveBeenCalled();
  });

  it("管理员正常加载用户列表", async () => {
    authState.user = { username: "admin", role: "admin" };

    renderPage();

    expect(screen.getByText("用户管理")).toBeTruthy();
    await waitFor(() => expect(api.listUsers).toHaveBeenCalledTimes(1));
  });
});
