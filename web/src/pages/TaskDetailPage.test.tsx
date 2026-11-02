import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  type DataPreparation,
  type PreparationItem,
  type RuleResult,
  type SystemInspection,
  type TaskStats,
  type TaskSummary,
} from "../api/http";
import { AuthProvider } from "../auth/AuthContext";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
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

function makePreparationItem(
  code: string,
  category: string,
  status: PreparationItem["status"],
  summary: string,
  issues: PreparationItem["issues"] = [],
): PreparationItem {
  return {
    code,
    name: code,
    category,
    status,
    summary,
    extracted_count: status === "error" ? 0 : 1,
    total_count: 1,
    issues,
  };
}

function makePreparation(items: PreparationItem[]): DataPreparation {
  return {
    status: items.some((item) => item.status === "error") ? "error" : "warn",
    items,
    total: items.length,
    success_count: items.filter((item) => item.status === "pass").length,
    warning_count: items.filter((item) => item.status === "warn").length,
    failure_count: items.filter((item) => ["fail", "error"].includes(item.status)).length,
    skip_count: items.filter((item) => item.status === "skip").length,
  };
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
    window.localStorage.clear();
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

  it("重点关注表默认紧凑，切换舒适后写入偏好且不改变既有状态筛选", async () => {
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
    const table = document.querySelector(".task-detail-attention-table");
    expect(table?.classList.contains("density-compact")).toBe(true);

    const user = userEvent.setup();
    const densityControl = screen
      .getAllByRole("group", { name: "表格密度" })
      .find((node) => node.closest('[data-testid="attention-panel"]') !== null);
    expect(densityControl).toBeDefined();
    await user.click(
      Array.from(densityControl?.querySelectorAll("button") ?? []).find(
        (node) => node.textContent === "舒适",
      ) as HTMLElement,
    );

    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBe("comfortable");
    await waitFor(() => {
      expect(document.querySelector(".task-detail-attention-table")?.classList.contains("density-comfortable")).toBe(
        true,
      );
    });
    expect(screen.getByTestId("attention-panel")).toBeDefined();
  });

  it("准备信息只展示两个隐藏解压单元及分类审计详情", async () => {
    vi.mocked(api.getTask).mockResolvedValue(
      makeTask({
        preparation: makePreparation([
          makePreparationItem("pkg.extract.main", "main", "pass", "主包解压 120 个原始文件"),
          makePreparationItem(
            "pkg.extract.classification",
            "classification",
            "warn",
            "落位 98 · 忽略 7 · 失败 2",
            [
              {
                type: "failed",
                source: "Alarm_Data/broken.zip",
                reason: "archive_corrupt: 告警归档损坏",
              },
            ],
          ),
          makePreparationItem("pkg.extract.logs", "logs", "error", "旧日志分类"),
          makePreparationItem("pkg.extract.kpi", "kpi", "fail", "旧 KPI 分类"),
        ]),
      }),
    );
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem());

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("conclusion-hero")).toBeDefined();
    });
    const user = userEvent.setup();
    await user.click(screen.getByText("执行与技术信息"));

    expect(screen.getByTestId("preparation-units")).toBeDefined();
    expect(screen.getByTestId("preparation-pkg.extract.main")).toBeDefined();
    expect(screen.getByTestId("preparation-pkg.extract.classification")).toBeDefined();
    expect(screen.queryByTestId("preparation-pkg.extract.logs")).toBeNull();
    expect(screen.queryByTestId("preparation-pkg.extract.kpi")).toBeNull();
    expect(screen.getByText("落位 98 · 忽略 7 · 失败 2")).toBeDefined();
    expect(screen.getByText(/archive_corrupt/)).toBeDefined();
  });
});
