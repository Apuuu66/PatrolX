import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  type DataPreparation,
  type KpiTaskSummaryV6,
  type PreparationItem,
  type RuleResult,
  type SystemInspection,
  type TaskStats,
  type TaskSummary,
} from "../api/http";
import { AuthProvider } from "../auth/AuthContext";
import { apiMe, setSession } from "../api/auth";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
import { TaskDetailPage } from "./TaskDetailPage";

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
    getTask: vi.fn(),
    getSystem: vi.fn(),
    listInspectors: vi.fn(),
    getTaskLogs: vi.fn(),
    rerunTask: vi.fn(),
    updateTaskDeviceId: vi.fn(),
    rebuildTask: vi.fn(),
    getKpiTaskSummaryV6: vi.fn(),
  },
}));

vi.mock("../api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/auth")>();
  return { ...actual, apiMe: vi.fn() };
});

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

function makeKpiSummary(overrides: Partial<KpiTaskSummaryV6> = {}): KpiTaskSummaryV6 {
  return {
    task_id: "task-001",
    network_element_type: "UMF",
    result_contract_version: "v6",
    data_date: "2026-10-10",
    previous_date: "2026-10-09",
    latest_measured_at: "2026-10-10T00:00:00Z",
    counts: {
      enabled_measurement_unit_count: 2,
      all_metric_count: 20,
      team_focus_count: 10,
      needs_attention_count: 3,
      no_action_count: 7,
      unavailable_focus_count: 0,
    },
    needs_attention_groups: [],
    rule_scope: {
      business_rule_count: 1,
      has_executable_rules: true,
      notice: null,
    },
    ...overrides,
  };
}

function renderPage(taskId = "task-001") {
  return render(
    <App>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/tasks/${taskId}`]}>
          <Routes>
            <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
            <Route path="/tasks/:taskId/kpi" element={<div data-testid="kpi-route">KPI 工作台</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </App>,
  );
}

describe("TaskDetailPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(apiMe).mockResolvedValue({ username: "admin", role: "admin" });
    vi.mocked(api.listInspectors).mockResolvedValue([]);
    vi.mocked(api.getTaskLogs).mockResolvedValue({ task_id: "task-001", entries: [] });
    vi.mocked(api.getKpiTaskSummaryV6).mockResolvedValue(makeKpiSummary());
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

  it("已有 v6 KPI 结果时提供唯一工作台入口，不展示健康分、风险排序或旧关注页签", async () => {
    vi.mocked(api.getTask).mockResolvedValue(makeTask());
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem());
    setSession("task-detail-test-token", { username: "admin", role: "admin" });

    renderPage();

    const entry = await screen.findByTestId("task-kpi-entry");
    await waitFor(() => expect(api.getKpiTaskSummaryV6).toHaveBeenCalledWith("task-001"));
    expect(entry.textContent ?? "").toContain("需要处理 3");
    expect(entry.textContent ?? "").toContain("团队关注 10");
    expect(screen.queryByText("健康分")).toBeNull();
    expect(screen.queryByText("风险排序")).toBeNull();
    expect(screen.queryByRole("tab", { name: "关注指标" })).toBeNull();

    const user = userEvent.setup();
    await user.click(within(entry).getByRole("button", { name: "查看 KPI 巡检结果" }));

    expect(await screen.findByTestId("kpi-route")).toBeDefined();
  });

  it("访客查看任务详情时不请求需要登录的 KPI 汇总", async () => {
    vi.mocked(api.getTask).mockResolvedValue(makeTask());
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem());

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("conclusion-hero")).toBeDefined();
    });
    expect(api.getKpiTaskSummaryV6).not.toHaveBeenCalled();
  });

  it("旧任务没有 v6 快照时只展示全量重建动作，不渲染 KPI 降级入口", async () => {
    vi.mocked(api.getTask).mockResolvedValue(makeTask());
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem());
    setSession("task-detail-test-token", { username: "admin", role: "admin" });
    vi.mocked(api.getKpiTaskSummaryV6).mockRejectedValue(
      new ApiError("task_result_requires_rebuild", "任务结果需要重建", 409),
    );
    vi.mocked(api.rebuildTask).mockResolvedValue({ task_id: "task-001" });

    renderPage();

    const rebuildRequired = await screen.findByTestId("task-kpi-rebuild-required");
    expect(rebuildRequired.textContent ?? "").toContain("task_result_requires_rebuild");
    expect(rebuildRequired.textContent ?? "").toContain("任务结果需要重建");
    expect(screen.queryByTestId("task-kpi-entry")).toBeNull();
    expect(screen.queryByRole("button", { name: "查看 KPI 巡检结果" })).toBeNull();

    const user = userEvent.setup();
    await user.click(within(rebuildRequired).getByRole("button", { name: "重建任务" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeDefined());
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^重\s*建$/ }));

    await waitFor(() => {
      expect(api.rebuildTask).toHaveBeenCalledWith("task-001", {
        mode: "full",
        confirmed: true,
        trigger_source: "ui",
      });
    });
  });

  it("日志补充包未选择规则适用网元类型时明确提示，不给出全绿结论", async () => {
    vi.mocked(api.getTask).mockResolvedValue(
      makeTask({ stats: makeStats({ total: 0, pass: 0, systems: 1 }) }),
    );
    vi.mocked(api.getSystem).mockResolvedValue(makeSystem({ rules: [], summary: makeStats({ total: 0, pass: 0 }) }));
    vi.mocked(api.getKpiTaskSummaryV6).mockResolvedValue(
      makeKpiSummary({
        network_element_type: null,
        counts: {
          enabled_measurement_unit_count: 0,
          all_metric_count: 0,
          team_focus_count: 0,
          needs_attention_count: 0,
          no_action_count: 0,
          unavailable_focus_count: 0,
        },
        rule_scope: {
          business_rule_count: 0,
          has_executable_rules: false,
          notice: "当前网元类型未配置可执行业务规则",
        },
      }),
    );
    setSession("task-detail-test-token", { username: "admin", role: "admin" });

    renderPage();

    const entry = await screen.findByTestId("task-kpi-entry");
    expect(entry.textContent ?? "").toContain("未选择规则适用网元类型");
    expect(screen.queryByText("全部通过")).toBeNull();
  });
});
