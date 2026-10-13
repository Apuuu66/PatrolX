import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type DataPreparation, type TaskStats, type TaskSummary } from "../api/http";
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
    getTask: vi.fn(),
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

function makePreparation(): DataPreparation {
  return {
    status: "warn",
    total: 2,
    success_count: 1,
    warning_count: 1,
    failure_count: 0,
    skip_count: 0,
    items: [
      {
        code: "prepare.alarm",
        name: "告警提取",
        category: "alarm",
        status: "warn",
        summary: "提取 3/5",
        duration_ms: 120,
        extracted_count: 3,
        total_count: 5,
        issues: [
          {
            type: "skipped",
            source: "raw/alarm/2026-09-21.csv",
            target: "prepared/alarm/2026-09-21.csv",
            reason: "来源文件缺失",
            path_length: 118,
            path_limit: 100,
          },
        ],
      },
      {
        code: "prepare.logs",
        name: "日志提取",
        category: "logs",
        status: "pass",
        summary: "全部提取",
        duration_ms: 80,
        extracted_count: 2,
        total_count: 2,
        issues: [],
      },
    ],
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
    vi.mocked(api.getTask).mockRejectedValue(new ApiError("not_found", "任务不存在", 404));
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
  it("列表展示最近一次运行时间与任务时长", async () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [
        makeTask({
          task_id: "ran",
          last_run_at: twoHoursAgo,
          duration_ms: 95_000,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("ran")).toBeDefined();
    });
    const row = document.querySelector<HTMLTableRowElement>(".ant-table-tbody > tr.ant-table-row");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByTestId("task-last-run").textContent).toBe("2 小时前");
    expect(within(row as HTMLElement).getByTestId("task-duration").textContent).toBe("1 分 35 秒");
  });

  it("运行中任务只显示运行中，从不运行任务显示占位", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [
        makeTask({
          task_id: "running",
          status: "running",
          completed_at: null,
          last_run_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          duration_ms: null,
        }),
        makeTask({
          task_id: "never-run",
          status: "pending",
          completed_at: null,
          last_run_at: null,
          duration_ms: null,
        }),
      ],
      total: 2,
      page: 1,
      page_size: 10,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("running")).toBeDefined();
    });
    const rows = Array.from(
      document.querySelectorAll<HTMLTableRowElement>(".ant-table-tbody > tr.ant-table-row"),
    );
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByTestId("task-duration").textContent).toBe("运行中");
    expect(within(rows[0]).getByTestId("task-last-run").textContent).toBe("5 分钟前");
    expect(within(rows[1]).getByTestId("task-duration").textContent).toBe("-");
    expect(within(rows[1]).getByTestId("task-last-run").textContent).toBe("-");
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

function overwriteButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "覆盖并重建" }) as HTMLButtonElement;
}

function confirmDialog(): HTMLElement {
  return document.querySelector(".ant-modal-confirm") as HTMLElement;
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
    vi.mocked(api.getTask).mockRejectedValue(new ApiError("not_found", "任务不存在", 404));
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
    vi.mocked(api.getTask).mockRejectedValue(new ApiError("not_found", "任务不存在", 404));
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

  it("同名任务已在列表中时预览提示覆盖并保留查看已有任务入口", async () => {
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
    expect(hint?.textContent ?? "").toContain("覆盖原数据包并全量重建");
    expect(hint?.textContent ?? "").toContain("查看已有任务");
    // 已知同名任务时提交按钮直接变成覆盖入口。
    expect(overwriteButton().disabled).toBe(false);
  });

  it("checksum 冲突时给出覆盖重建与保留现场的动作", async () => {
    const conflict = await prepareConflict();

    expect(conflict.textContent ?? "").toContain("checksum");
    expect(within(conflict).getByRole("button", { name: /覆盖并全量重建/ })).toBeDefined();
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
    // antd 重页面在慢速 CI 上单例耗时可达 15s+，按 60s 留出余量（函数体仍即时校验）。
  }, 60000);

  it("冲突提示中的查看已有任务会跳到已有任务", async () => {
    const conflict = await prepareConflict();

    fireEvent.click(within(conflict).getByRole("button", { name: /查看已有任务/ }));

    await waitFor(() => {
      expect(screen.getByTestId("task-route")).toBeDefined();
    });
  }, 60000);

  it("同名任务提交时先确认覆盖，确认后清除旧现场并全量重建", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-sample_pkg", name: "sample-pkg" })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.deleteTask).mockResolvedValue(undefined);
    vi.mocked(api.createTaskV3).mockResolvedValue({ task_id: "task-sample_pkg" });
    renderPageWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("sample-pkg")).toBeDefined();
    });
    await openUploadModal();

    selectUploadFile(new File(["payload"], "sample-pkg.zip", { type: "application/zip" }));
    await waitFor(() => {
      expect(overwriteButton().disabled).toBe(false);
    });
    fireEvent.click(overwriteButton());

    // 未确认前不得删除旧现场，也不得重复创建任务。
    await waitFor(() => {
      expect(document.querySelector(".ant-modal-confirm")).not.toBeNull();
    });
    expect(document.body.textContent ?? "").toContain("覆盖同名任务并全量重建？");
    expect(api.deleteTask).not.toHaveBeenCalled();
    expect(api.createTaskV3).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(within(confirmDialog()).getByRole("button", { name: "覆盖并重建" }));

    await waitFor(() => {
      expect(api.createTaskV3).toHaveBeenCalled();
    });
    expect(api.deleteTask).toHaveBeenCalledWith("task-sample_pkg");
    // 覆盖顺序：先清空旧现场，再用当前数据包创建任务并从零执行。
    expect(vi.mocked(api.deleteTask).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.createTaskV3).mock.invocationCallOrder[0],
    );
    await waitFor(() => {
      expect(screen.getByTestId("task-route")).toBeDefined();
    });
    expect(document.body.textContent ?? "").toContain("已覆盖同名数据包，开始全量重建");
  }, 60000);

  it("同名任务不在当前列表时提交前探测命中并提示覆盖", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-other" })],
      total: 40,
      page: 1,
      page_size: 10,
    });
    vi.mocked(api.getTask).mockResolvedValue(makeTask({ task_id: "task-sample_pkg", name: "sample-pkg" }));
    vi.mocked(api.createTaskV3).mockResolvedValue({ task_id: "task-sample_pkg" });
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
      expect(document.querySelector(".ant-modal-confirm")).not.toBeNull();
    });
    expect(api.getTask).toHaveBeenCalledWith("task-sample_pkg");
    expect(api.createTaskV3).not.toHaveBeenCalled();
    // 探测命中后弹窗内同样提示覆盖，二次提交不再重复探测。
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="upload-existing-task-hint"]')?.textContent ?? "",
      ).toContain("覆盖原数据包并全量重建");
    });
  }, 60000);

  it("冲突提示中的覆盖入口确认后清除旧现场并重建", async () => {
    const conflict = await prepareConflict();
    vi.mocked(api.deleteTask).mockResolvedValue(undefined);
    vi.mocked(api.createTaskV3).mockResolvedValue({ task_id: "task-sample_pkg" });

    const user = userEvent.setup();
    await user.click(within(conflict).getByRole("button", { name: /覆盖并全量重建/ }));
    await waitFor(() => {
      expect(document.querySelector(".ant-modal-confirm")).not.toBeNull();
    });
    await user.click(within(confirmDialog()).getByRole("button", { name: "覆盖并重建" }));

    await waitFor(() => {
      expect(api.deleteTask).toHaveBeenCalledWith("task-sample_pkg");
    });
    await waitFor(() => {
      expect(screen.getByTestId("task-route")).toBeDefined();
    });
  }, 60000);
});

describe("TaskListPage 行内信息与操作", () => {
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
    vi.mocked(api.getTask).mockRejectedValue(new ApiError("not_found", "任务不存在", 404));
  });

  it("操作列去掉重跑且不再有行展开，重建收在更多菜单", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-001" })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });

    // 去掉收缩：行首不再渲染展开 / 收起箭头。
    expect(document.querySelector(".ant-table-row-expand-icon")).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    await waitFor(() => {
      expect(screen.getByText("重建")).toBeDefined();
    });
    expect(screen.queryByText("重跑")).toBeNull();
    expect(screen.queryByText("全量重建")).toBeNull();
  }, 60000);

  it("数据准备摘要就地可见，明细在列内弹层展开", async () => {
    vi.mocked(api.listTasks).mockResolvedValue({
      items: [makeTask({ task_id: "task-001", preparation: makePreparation() })],
      total: 1,
      page: 1,
      page_size: 10,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("task-001")).toBeDefined();
    });

    const summary = screen.getByTestId("task-preparation-summary");
    expect(summary.textContent ?? "").toContain("1 类异常");

    const user = userEvent.setup();
    await user.click(summary);
    await waitFor(() => {
      expect(document.querySelector(".ant-popover")).not.toBeNull();
    });
    const popover = document.querySelector(".ant-popover") as HTMLElement;
    expect(popover.textContent ?? "").toContain("告警 3/5");
    expect(popover.textContent ?? "").toContain("来源文件缺失");
  }, 60000);
});
