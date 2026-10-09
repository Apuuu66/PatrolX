import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type TaskStats, type TaskSummary } from "../api/http";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
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
    window.localStorage.clear();
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

  it("默认紧凑密度，切换为舒适后写入偏好且不重置筛选与分页", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask()],
      total: 25,
      page: 2,
      page_size: 10,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });
    const table = document.querySelector(".task-table");
    expect(table?.classList.contains("density-compact")).toBe(true);

    // 先选中状态筛选，再切换密度：筛选条件不得被重置。
    const user = userEvent.setup();
    fireEvent.click(
      within(screen.getByLabelText("任务状态快捷筛选")).getByText("失败"),
    );
    await waitFor(() => {
      expect(api.listTasks).toHaveBeenLastCalledWith({ page: 1, page_size: 10, status: "failed" });
    });

    await user.click(screen.getByRole("button", { name: "舒适" }));

    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBe("comfortable");
    await waitFor(() => {
      expect(document.querySelector(".task-table")?.classList.contains("density-comfortable")).toBe(
        true,
      );
    });
    expect(api.listTasks).toHaveBeenLastCalledWith({ page: 1, page_size: 10, status: "failed" });
    expect(
      document.querySelector(".ant-segmented-item-selected")?.textContent,
    ).toBe("失败");
  });
});

async function openUploadModal() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /上传数据包/ }));
  await waitFor(() => {
    expect(screen.getByText("上传数据包（一个压缩包 = 一个任务）")).toBeDefined();
  });
  return user;
}

function selectUploadFile(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });
}

function okButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "提交巡检" }) as HTMLButtonElement;
}

});
