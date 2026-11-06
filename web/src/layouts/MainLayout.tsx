import { lazy, Suspense, useState } from "react";
import type { ReactNode } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const LoginModal = lazy(() => import("./LoginModal"));
const PageProviders = lazy(() => import("../providers/PageProviders"));

const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  viewer: "浏览者",
};

/**
 * 路由 → 顶栏标题映射（FR-020、R14）。
 * 顺序敏感：先匹配更具体的子路由，再匹配一级页面。
 */
const PAGE_TITLE_RULES: readonly { pattern: RegExp; title: string }[] = [
  { pattern: /^\/tasks\/[^/]+\/rules\/[^/]+$/, title: "规则详情" },
  { pattern: /^\/tasks\/[^/]+\/kpi$/, title: "KPI 巡检结果" },
  { pattern: /^\/tasks\/[^/]+\/report$/, title: "巡检报告" },
  { pattern: /^\/tasks\/[^/]+\/logs$/, title: "执行日志" },
  { pattern: /^\/tasks\/[^/]+$/, title: "任务详情" },
  { pattern: /^\/tasks?$/, title: "巡检任务" },
  { pattern: /^\/inventory\/devices\/[^/]+$/, title: "设备详情" },
  { pattern: /^\/inventory$/, title: "设备台账" },
  { pattern: /^\/measurement-units$/, title: "基础指标" },
  { pattern: /^\/inspectors$/, title: "规则管理" },
  { pattern: /^\/dicts$/, title: "数据字典" },
  { pattern: /^\/users$/, title: "用户管理" },
];

/** 顶栏标题：未知路径回退到默认落地页标题，避免出现空标题或产品名重复。 */
export function resolvePageTitle(pathname: string): string {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/") return "巡检任务";
  return PAGE_TITLE_RULES.find((rule) => rule.pattern.test(normalized))?.title ?? "巡检任务";
}

type ShellIconName = "brand" | "tasks" | "inventory" | "measurement" | "inspectors" | "dicts" | "users" | "logout";

function ShellIcon({ name }: { name: ShellIconName }) {
  const paths: Record<ShellIconName, ReactNode> = {
    brand: (
      <>
        <path d="M12 3 19 6v5c0 4.4-2.9 8.1-7 9.5C7.9 19.1 5 15.4 5 11V6l7-3Z" />
        <path d="m9.5 12 1.7 1.7 3.6-4" />
      </>
    ),
    tasks: (
      <>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v5h5M10 13h5M10 17h3" />
        <circle cx="8" cy="8" r="3" />
        <path d="m10.5 10.5 2 2" />
      </>
    ),
    inventory: (
      <>
        <path d="M4 21V4h10v17M14 9h6v12M8 8h2M8 12h2M8 16h2M17 13h1M17 17h1M2 21h20" />
      </>
    ),
    measurement: (
      <>
        <path d="M4 19V5M4 19h17" />
        <path d="m7 15 4-5 3 3 5-7" />
      </>
    ),
    inspectors: (
      <>
        <path d="M5 20V10h4v10M10 20V4h4v16M15 20v-7h4v7M3 20h18" />
      </>
    ),
    dicts: (
      <>
        <ellipse cx="12" cy="5" rx="7" ry="3" />
        <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </>
    ),
    users: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 21c.5-4 3.1-6 7-6s6.5 2 7 6" />
      </>
    ),
    logout: (
      <>
        <path d="M14 4h5v16h-5M10 8l-4 4 4 4M6 12h9" />
      </>
    ),
  };

  return (
    <svg
      aria-hidden="true"
      className="app-shell-icon"
      data-icon={name}
      fill="none"
      height="18"
      viewBox="0 0 24 24"
      width="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {paths[name]}
    </svg>
  );
}

export function MainLayout() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const [loginOpen, setLoginOpen] = useState(false);
  const selected =
    location.pathname === "/" || location.pathname.startsWith("/tasks")
      ? "/tasks"
      : location.pathname.startsWith("/inventory")
        ? "/inventory"
        : location.pathname.startsWith("/measurement-units")
          ? "/measurement-units"
          : location.pathname.startsWith("/inspectors")
            ? "/inspectors"
            : location.pathname.startsWith("/users")
              ? "/users"
              : "/dicts";

  const menuItems = [
    { key: "/tasks", icon: "tasks" as const, label: "巡检任务" },
    { key: "/inventory", icon: "inventory" as const, label: "设备台账" },
    { key: "/measurement-units", icon: "measurement" as const, label: "基础指标" },
    { key: "/inspectors", icon: "inspectors" as const, label: "规则管理" },
    { key: "/dicts", icon: "dicts" as const, label: "数据字典" },
    ...(user?.role === "admin"
      ? [{ key: "/users", icon: "users" as const, label: "用户管理" }]
      : []),
  ];

  return (
    <div className="app-layout">
      <aside className="app-sider">
        <div className="app-sider-brand">
          <ShellIcon name="brand" />
          PatrolX
        </div>
        <nav className="app-nav" aria-label="主导航">
          {menuItems.map((item) => (
            <Link
              key={item.key}
              to={item.key}
              className={`app-nav-link${selected === item.key ? " is-selected" : ""}`}
              aria-current={selected === item.key ? "page" : undefined}
            >
              <ShellIcon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="app-shell-inner app-shell-header">
            <h1 className="app-header-title" data-testid="app-page-title">
              {resolvePageTitle(location.pathname)}
            </h1>
            <div className="app-header-actions">
              {user ? (
                <>
                  <span className="app-user-name">{user.username}</span>
                  <span className={`app-role-badge${user.role === "admin" ? "" : " is-viewer"}`}>
                    {ROLE_LABELS[user.role] ?? user.role}
                  </span>
                  <button
                    type="button"
                    className="app-button app-button--small app-logout"
                    onClick={() => void logout()}
                  >
                    <ShellIcon name="logout" />
                    登出
                  </button>
                </>
              ) : (
                <>
                  <span className="app-visitor-label">访客模式</span>
                  {/* 访客模式登录降为默认按钮权重，不与页面主操作竞争（FR-020、R14） */}
                  <button
                    type="button"
                    className="app-button app-button--small"
                    onClick={() => setLoginOpen(true)}
                  >
                    登录
                  </button>
                </>
              )}
            </div>
          </div>
        </header>
        <main className="app-content">
          <div className="app-shell-inner">
            <Suspense
              fallback={
                <div className="page-route-fallback" role="status">
                  <span className="page-route-spinner" aria-hidden="true" />
                  正在加载页面…
                </div>
              }
            >
              <PageProviders>
                <Outlet />
              </PageProviders>
            </Suspense>
          </div>
        </main>
      </div>
      {loginOpen ? (
        <Suspense
          fallback={
            <div className="login-modal-loading" role="status">
              正在加载登录…
            </div>
          }
        >
          <PageProviders>
            <LoginModal open onClose={() => setLoginOpen(false)} />
          </PageProviders>
        </Suspense>
      ) : null}
    </div>
  );
}
