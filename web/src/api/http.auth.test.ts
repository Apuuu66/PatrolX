import test from "node:test";
import assert from "node:assert/strict";

import { api } from "./http.ts";
import { setSession } from "./auth.ts";

test("普通 API 请求自动携带登录 token", async () => {
  const localStorageMock = {
    getItem: (_key: string) => "session-token",
    setItem: (_key: string, _value: string) => undefined,
    removeItem: (_key: string) => undefined,
    clear: () => undefined,
    key: (_index: number) => null,
    length: 0,
  };
  Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, configurable: true });
  setSession("session-token", { username: "alice", role: "admin" });

  const calls: Array<RequestInit | undefined> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(init ?? {});
    return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 20 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  try {
    await api.listTasks();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.headers instanceof Headers ? calls[0].headers.get("Authorization") : undefined, "Bearer session-token");
});

test("401 响应自动清理会话并抛出业务错误", async () => {
  const cleared: string[] = [];
  const localStorageMock = {
    getItem: (_key: string) => "expired-token",
    setItem: (_key: string, _value: string) => undefined,
    removeItem: (key: string) => cleared.push(key),
    clear: () => undefined,
    key: (_index: number) => null,
    length: 0,
  };
  Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, configurable: true });
  setSession("expired-token", { username: "alice", role: "admin" });

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ code: "unauthorized", message: "会话已失效" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;

  try {
    await assert.rejects(api.listTasks(), (error: Error) => error.message === "会话已失效");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(cleared, ["patrolx_token", "patrolx_user"]);
});
