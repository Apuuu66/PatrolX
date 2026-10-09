import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type TaskStats, type TaskSummary } from "../api/http";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
import { TaskListPage } from "./TaskListPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {
    code: string;
    status: number;
    detail?: unknown;

    constructor(code: string, message: string, status = 400, detail?: unknown) {
      super(message);
      this.code = code;
      this.status = status;
      this.detail = detail;
    }
  },
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

describe("TaskListPage 上传预检", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask()],
      total: 1,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.getOverview).mockResolvedValue({
      task_count: 1,
      registered_rule_count: 0,
      rule_result_count: 0,
      finding_count: 0,
      status_counts: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0 },
    });
    vi.mocked(api.listDicts).mockResolvedValue({
      province: [],
      operator: [],
      product: [],
      version: [],
    });
  });

  it("选择合法文件后立即展示任务 ID 预览、文件大小与校验结论", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File([new Uint8Array(2048)], "ZZapp01BCN_app_Problem_scene_333.zip"));

    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-precheck"]')).not.toBeNull();
    });
    expect(
      document.querySelector('[data-testid="upload-task-id-preview"]')?.textContent ?? "",
    ).toContain("task-zzapp01bcn_app_problem_scene_333");
    expect(document.querySelector('[data-testid="upload-file-size"]')?.textContent ?? "").toContain(
      "2 KB",
    );
    const precheck = document.querySelector('[data-testid="upload-precheck"]');
    expect(precheck?.getAttribute("data-precheck-valid")).toBe("true");
    expect(precheck?.textContent ?? "").toContain("校验通过");
    expect(okButton().disabled).toBe(false);
  });

  it("非法文件禁用提交并显示具体原因", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File(["not a package"], "sample.rar", { type: "application/octet-stream" }));

    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-precheck"]')).not.toBeNull();
    });
    const precheck = document.querySelector('[data-testid="upload-precheck"]');
    expect(precheck?.getAttribute("data-precheck-valid")).toBe("false");
    expect(precheck?.textContent ?? "").toMatch(/仅支持 zip/);
    expect(okButton().disabled).toBe(true);
  });

  it("空文件被拦截并提示重新导出", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File([], "empty.zip", { type: "application/zip" }));

    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-precheck"]')?.textContent ?? "").toContain(
        "数据包为空",
      );
    });
    expect(okButton().disabled).toBe(true);
  });
});

function renderPageWithRoutes() {
  return render(
    <App>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<TaskListPage />} />
          <Route path="/tasks/:taskId" element={<div data-testid="task-route">任务详情占位</div>} />
        </Routes>
      </MemoryRouter>
    </App>,
  );
}

describe("TaskListPage 同名冲突", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(api.getOverview).mockResolvedValue({
      task_count: 1,
      registered_rule_count: 0,
      rule_result_count: 0,
      finding_count: 0,
      status_counts: { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0 },
    });
    vi.mocked(api.listDicts).mockResolvedValue({
      province: [],
      operator: [],
      product: [],
      version: [],
    });
  });

  async function prepareConflict() {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-other" })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.createTaskV3).mockRejectedValue(
      new ApiError("package_checksum_conflict", "同名任务已存在，但数据包 checksum 不同", 409),
    );
    renderPageWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("task-other")).toBeDefined();
    });
    await openUploadModal();
    selectUploadFile(new File(["payload"], "sample-pkg.zip", { type: "application/zip" }));
    await waitFor(() => {
      expect(okButton().disabled).toBe(false);
    });
    fireEvent.click(okButton());
    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-conflict"]')).not.toBeNull();
    });
    return document.querySelector('[data-testid="upload-conflict"]') as HTMLElement;
  }

  it("同名任务已在列表中时预览给出查看已有任务入口", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-sample_pkg", name: "sample-pkg" })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    renderPageWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("sample-pkg")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File(["payload"], "sample-pkg.zip", { type: "application/zip" }));

    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-task-id-preview"]')?.textContent).toContain(
        "task-sample_pkg",
      );
    });
    const hint = document.querySelector('[data-testid="upload-existing-task-hint"]');
    expect(hint?.textContent ?? "").toContain("同名任务已存在");
    expect(hint?.textContent ?? "").toContain("打开已有任务");
  });

  it("checksum 冲突时给出修改文件名与查看已有任务两个动作", async () => {
    const conflict = await prepareConflict();

    expect(conflict.textContent ?? "").toContain("checksum");
    fireEvent.click(within(conflict).getByRole("button", { name: /修改文件名/ }));

    await waitFor(() => {
      expect(document.querySelector('[data-testid="upload-conflict"]')).toBeNull();
    });
    expect(document.querySelector('[data-testid="upload-precheck"]')).toBeNull();
    expect(okButton().disabled).toBe(true);

    // 重新选择另一个文件名后冲突提示不再残留。
    selectUploadFile(new File(["payload"], "sample-pkg-v2.zip", { type: "application/zip" }));
    await waitFor(() => {
      expect(okButton().disabled).toBe(false);
    });
    expect(document.querySelector('[data-testid="upload-conflict"]')).toBeNull();
  }, 15000);

  it("冲突提示中的查看已有任务会跳到已有任务", async () => {
    const conflict = await prepareConflict();

    fireEvent.click(within(conflict).getByRole("button", { name: /查看已有任务/ }));

    await waitFor(() => {
      expect(screen.getByTestId("task-route")).toBeDefined();
    });
  }, 15000);

  it("checksum 相同则提示将打开已有任务并进入该任务", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-sample_pkg", name: "sample-pkg" })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.createTaskV3).mockResolvedValue({ task_id: "task-sample_pkg" });
    renderPageWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("sample-pkg")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File(["payload"], "sample-pkg.zip", { type: "application/zip" }));
    await waitFor(() => {
      expect(okButton().disabled).toBe(false);
    });
    fireEvent.click(okButton());

    await waitFor(() => {
      expect(screen.getByTestId("task-route")).toBeDefined();
    });
    expect(document.body.textContent ?? "").toContain("将打开已有任务");
  }, 15000);
});
