import { render, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type TaskStats, type TaskSummary } from "../api/http";
import { TaskListPage } from "./TaskListPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listTasks: vi.fn(),
    getOverview: vi.fn(),
    listDicts: vi.fn(),
    createTaskV3: vi.fn(),
    deleteTask: vi.fn(),
    rerunTask: vi.fn(),
    rebuildTask: vi.fn(),
  },
}));

function makeStats(overrides: Partial<TaskStats> = {}): TaskStats {
  return { total: 1, pass: 1, warn: 0, fail: 0, error: 0, skip: 0, systems: 1, ...overrides };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "task-001",
    name: "样例任务",
    mode: "local",
    status: "completed",
    trigger: "api",
    created_at: "2026-10-10T00:00:00Z",
    completed_at: "2026-10-10T00:01:00Z",
    stats: makeStats(),
    ...overrides,
  };
}

function renderPage() {
  return render(
    <App>
      <MemoryRouter>
        <TaskListPage />
      </MemoryRouter>
    </App>,
  );
}

describe("TaskListPage", () => {
  beforeEach(() => {
    vi.mocked(api.getOverview).mockResolvedValue({
      task_count: 4,
      registered_rule_count: 12,
      rule_result_count: 9,
      finding_count: 2,
      status_counts: { total: 9, pass: 8, warn: 1, fail: 0, error: 0, skip: 0 },
    });
    vi.mocked(api.listDicts).mockResolvedValue({
      province: [],
      operator: [],
      product: [],
      version: [],
    });
  });

  it("默认按每页 10 条请求任务列表", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask()],
      total: 1,
      page: 1,
      page_size: 10,
    });

    renderPage();

    await waitFor(() => {
      expect(api.listTasks).toHaveBeenCalledWith({ page: 1, page_size: 10, status: undefined });
    });
  });

  it("异常任务置顶且行内只展示非零状态", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [
        makeTask({ task_id: "clean", created_at: "2026-10-10T00:00:00Z" }),
        makeTask({
          task_id: "abnormal",
          status: "failed",
          created_at: "2026-10-09T00:00:00Z",
          stats: makeStats({ pass: 0, error: 1 }),
        }),
      ],
      total: 2,
      page: 1,
      page_size: 10,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("abnormal")).toBeDefined();
    });
    const bodyRows = Array.from(
      document.querySelectorAll<HTMLTableRowElement>(".ant-table-tbody > tr.ant-table-row"),
    );
    expect(bodyRows).toHaveLength(2);
    expect(within(bodyRows[0]).getByText("abnormal")).toBeDefined();
    expect(within(bodyRows[0]).getByText("异常 1")).toBeDefined();
    expect(within(bodyRows[0]).queryByText("通过 0")).toBeNull();
  });
});
