import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiLogin, apiLogout, apiMe, getStoredUser, setSession } from "../api/auth.ts";
import type { UserInfo } from "../api/auth.ts";
import { canWrite } from "./model.ts";

interface AuthContextValue {
  user: UserInfo | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  canWrite: boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(() => getStoredUser());

  useEffect(() => {
    if (!user) return;
    void apiMe()
      .then(setUser)
      .catch(() => setUser(null));
    // 只在登录会话初次挂载时校验一次；登录 / 登出会显式更新状态。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await apiLogin(username, password);
    const nextUser: UserInfo = { username: result.username, role: result.role };
    setSession(result.token, nextUser);
    setUser(nextUser);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, login, logout, canWrite: canWrite(user?.role) }),
    [user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return value;
}
