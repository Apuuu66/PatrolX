import test from "node:test";
import assert from "node:assert/strict";

import { api, ApiError } from "./http.ts";

Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
    clear: () => undefined,
    key: () => null,
    length: 0,
  },
  configurable: true,
});

type ConsoleRecord = { level: string; message: string; context?: unknown };

function captureConsole(): { records: ConsoleRecord[]; restore: () => void } {
  const records: ConsoleRecord[] = [];
  const originalInfo = console.info;
  const originalWarn = console.warn;
  const originalError = console.error;
  console.info = (message: unknown, context?: unknown) => {
    records.push({ level: "info", message: String(message), context });
  };
  console.warn = (message: unknown, context?: unknown) => {
    records.push({ level: "warn", message: String(message), context });
  };
  console.error = (message: unknown, context?: unknown) => {
    records.push({ level: "error", message: String(message), context });
  };
  return {
    records,
    restore: () => {
      console.info = originalInfo;
      console.warn = originalWarn;
      console.error = originalError;
    },
  };
}

test("API 请求成功时输出包含定位信息的诊断日志", async () => {
  const captured = captureConsole();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ total: 0 }), { status: 200 })) as typeof fetch;

  try {
    await api.getOverview();
  } finally {
    globalThis.fetch = originalFetch;
    captured.restore();
  }

  const record = captured.records.find((item) => item.message.includes("[api] API request succeeded"));
  assert.ok(record, "缺少成功请求日志");
  const context = record.context as { method: string; url: string; status: number; duration_ms: number };
  assert.equal(context.method, "GET");
  assert.equal(context.url, "/api/v2/overview");
  assert.equal(context.status, 200);
  assert.equal(typeof context.duration_ms, "number");
  assert.equal(context.duration_ms >= 0, true);
  assert.equal(JSON.stringify(record.context).includes("Bearer"), false);
});

test("API 请求失败时输出包含错误码和状态的可定位日志", async () => {
  const captured = captureConsole();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ code: "task_not_found", message: "任务不存在" }), {
      status: 404,
    })) as typeof fetch;

  try {
    await assert.rejects(api.getTask("missing"), ApiError);
  } finally {
    globalThis.fetch = originalFetch;
    captured.restore();
  }

  const record = captured.records.find((item) => item.message.includes("[api] API request failed"));
  assert.ok(record, "缺少失败请求日志");
  const context = record.context as {
    method: string;
    url: string;
    status: number;
    duration_ms: number;
    code: string;
  };
  assert.equal(context.method, "GET");
  assert.equal(context.url, "/api/v2/tasks/missing");
  assert.equal(context.status, 404);
  assert.equal(context.code, "task_not_found");
  assert.equal(typeof context.duration_ms, "number");
  assert.equal(context.duration_ms >= 0, true);
});
