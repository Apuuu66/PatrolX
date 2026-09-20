import type { components } from "./client";

export type LoginResponse = components["schemas"]["LoginResponseV1"];
export type UserInfo = components["schemas"]["UserInfoV1"];

const TOKEN_KEY = "patrolx_token";
const USER_KEY = "patrolx_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as UserInfo) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: UserInfo): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function apiLogin(username: string, password: string): Promise<LoginResponse> {
  const resp = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => null)) as { message?: string } | null;
    throw new Error(body?.message ?? "登录失败");
  }
  return (await resp.json()) as LoginResponse;
}

export async function apiLogout(): Promise<void> {
  const token = getToken();
  if (!token) return;
  await fetch("/api/v1/auth/logout", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined);
  clearSession();
}

export async function apiMe(): Promise<UserInfo> {
  const token = getToken();
  if (!token) throw new Error("未登录");
  const resp = await fetch("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    clearSession();
    throw new Error("会话已失效");
  }
  return (await resp.json()) as UserInfo;
}
