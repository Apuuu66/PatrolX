import { render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type RuleResult, type SystemInspection, type TaskStats, type TaskSummary } from "../api/http";
import { AuthProvider } from "../auth/AuthContext";
import { TaskDetailPage } from "./TaskDetailPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    getTask: vi.fn(),
    getSystem: vi.fn(),
    listInspectors: vi.fn(),
    getTaskLogs: vi.fn(),
    rerunTask: vi.fn(),
    updateTaskDeviceId: vi.fn(),
    rebuildTask: vi.fn(),
  },
}));

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1, ...overrides };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-001",
    name: "详情页样例任务",
    mode: "local",
    status: "completed",
    trigger: "ui",
    created_at: "2026-10-10T00:00:00Z",
    completed_at: "2026-10-10T00:01:00Z",
    stats: makeStats(),
    ...overrides,
  };
}

function makeRule(overrides: Partial<RuleResult> = {}): RuleResult {
  return {
    code: "config.a",
    name: "配置通过",
    category: "config",
    priority: 1,
    execution_order: 0,
    status: "pass",
    severity: "low",
    summary: "配置一致",
    ...overrides,
  } as RuleResult;
}

function makeSystem(overrides: Partial<SystemInspection> = {}): SystemInspection {
  return {
    package_file: "package.zip",
    status: "completed",
    summary: makeStats(),
    rules: [makeRule()],
    ...overrides,
  } as unknown as SystemInspection;
}

function renderPage(taskId = "task-001") {
  return render(
    <App>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/tasks/${taskId}`]}>
          <Routes>
            <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </App>,
  );
}

describe("TaskDetailPage", () => {
  beforeEach(() => {
    vi.mocked(api.listInspectors).mockResolvedValue([]);
    vi.mocked(api.getTaskLogs).mockResolvedValue({ task_id: "task-001", entries: [] });
  });

  it("全通过任务首屏只保留结论 Hero 与全部规则，不出现重点关注提示条", async () => {
    vi.mocked(api.getTask).mockResolvedValue(makeTask());
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem());

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("conclusion-hero")).toBeDefined();
    });
    expect(screen.getByText("全部通过")).toBeDefined();
    expect(screen.getByTestId("rule-browser")).toBeDefined();
    expect(screen.queryByTestId("attention-panel")).toBeNull();
    expect(screen.queryByText("巡检完成，未发现需要重点处理的规则")).toBeNull();
  });

  it("解压失败任务不渲染规则表格，失败阶段与日志入口只出现一次", async () => {
    vi.mocked(api.getTask).mockResolvedValue(
      makeTask({
        status: "failed",
        completed_at: null,
        stats: makeStats({ total: 0, pass: 0, systems: 0 }),
      }),
    );
    vi.mocked(api.getSystem).mockRejectedValue(new Error("系统结果不存在"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("conclusion-hero")).toBeDefined();
    });
    expect(screen.getByText("任务失败")).toBeDefined();
    expect(screen.getAllByText("失败阶段：任务执行")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /查看失败日志/ })).toBeDefined();
    expect(screen.queryByTestId("rule-browser")).toBeNull();
    expect(screen.queryByTestId("attention-panel")).toBeNull();
    expect(document.querySelector(".ant-table")).toBeNull();
  });

  it("存在关注项时重点关注与全部规则各出现一次，不叠加旧提示条", async () => {
    vi.mocked(api.getTask).mockResolvedValue(
      makeTask({ stats: makeStats({ total: 2, pass: 1, fail: 1 }) }),
    );
    vi.mocked(api.getSystem).mockResolvedValue(
      makeSystem({
        summary: makeStats({ total: 2, pass: 1, fail: 1 }),
        rules: [
          makeRule(),
          makeRule({ code: "log.b", name: "日志错误", category: "log", status: "fail", severity: "high" }),
        ],
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("attention-panel")).toBeDefined();
    });
    expect(screen.getAllByText("重点关注（1）")).toHaveLength(1);
    expect(screen.queryByText("重点关注 1 条规则")).toBeNull();
    expect(screen.queryByText(/其余 \d+ 条在全部规则中查看/)).toBeNull();
    expect(screen.getByTestId("rule-browser")).toBeDefined();
  });
});
