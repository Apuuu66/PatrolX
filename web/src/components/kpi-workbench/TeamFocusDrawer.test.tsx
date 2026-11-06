import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  type KpiMetricResultPageV6,
  type KpiMetricResultV6,
  type KpiTeamFocusPageV6,
  type KpiTeamFocusPatchResponseV6,
} from "../../api/http";
import { TeamFocusDrawer } from "./TeamFocusDrawer";

vi.mock("../../api/http", () => ({
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
    listKpiTaskMetricsV6: vi.fn(),
    listKpiTeamFocusV6: vi.fn(),
    patchKpiTeamFocusV6: vi.fn(),
  },
}));

function makeMetric(
  measurementUnitId: string,
  measurementUnitName: string,
  metricResourceId: string,
  metricName: string,
  overrides: Partial<KpiMetricResultV6> = {},
): KpiMetricResultV6 {
  return {
    task_id: "task-umf",
    network_element_type: "UMF",
    measurement_unit_id: measurementUnitId,
    measurement_unit_name: measurementUnitName,
    metric_resource_id: metricResourceId,
    metric_name: metricName,
    role: "base",
    importance: "P1",
    importance_rank: 1,
    availability: "available",
    is_team_focus: false,
    current_status: "normal",
    yesterday_trend: "stable",
    needs_attention_group: null,
    special_state: null,
    today_value: 99.8,
    yesterday_value: 99.7,
    change_value: 0.1,
    change_unit: "pp",
    reason: "当前正常。",
    evidence_available: true,
    ...overrides,
  };
}

const METRICS = [
  makeMetric("MU_MEDIA", "媒体资源测量单元", "ME_MEDIA_CREATION_SUCCESS_RATE", "媒体资源创建成功率", {
    is_team_focus: true,
    current_status: "fail",
    yesterday_trend: "worsened",
    needs_attention_group: "failure",
  }),
  makeMetric("MU_MEDIA", "媒体资源测量单元", "ME_MEDIA_DELETION_REQUESTS", "媒体资源删除请求数"),
  makeMetric("MU_SIGNAL", "信令测量单元", "ME_S1_HANDOVER_SUCCESS_RATE", "S1 切换成功率"),
];

function makeMetricPage(): KpiMetricResultPageV6 {
  return {
    items: METRICS,
    total: METRICS.length,
    view_total: METRICS.length,
    page: 1,
    page_size: 200,
    empty_state: "none",
    applied_filters: {
      search: null,
      measurement_unit_id: null,
      current_status: null,
      yesterday_trend: null,
      needs_attention_group: null,
    },
  };
}

function makeFocusPage(overrides: Partial<KpiTeamFocusPageV6> = {}): KpiTeamFocusPageV6 {
  return {
    network_element_type: "UMF",
    revision: 4,
    page: 1,
    page_size: 200,
    total: 2,
    available_count: 1,
    unavailable_count: 1,
    can_write: true,
    items: [
      {
        network_element_type: "UMF",
        measurement_unit_id: "MU_MEDIA",
        measurement_unit_name: "媒体资源测量单元",
        metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE",
        metric_name: "媒体资源创建成功率",
        availability: "available",
        availability_reason: null,
        added_by: "maintainer",
        added_at: "2026-11-04T08:00:00Z",
      },
      {
        network_element_type: "UMF",
        measurement_unit_id: "MU_LEGACY",
        measurement_unit_name: "历史消息测量单元",
        metric_resource_id: "ME_LEGACY_MESSAGE_DELIVERY_RATE",
        metric_name: "历史消息投递成功率",
        availability: "unavailable",
        availability_reason: "not_in_task_scope",
        added_by: "maintainer",
        added_at: "2026-11-03T08:00:00Z",
      },
    ],
    ...overrides,
  };
}

const PATCH_RESPONSE: KpiTeamFocusPatchResponseV6 = {
  network_element_type: "UMF",
  revision: 5,
  added_count: 2,
  removed_count: 1,
  available_count: 2,
  unavailable_count: 1,
};

function renderDrawer({
  taskId = "task-umf",
  networkElementType = "UMF",
  onClose = vi.fn(),
  onSaved = vi.fn(),
}: {
  taskId?: string;
  networkElementType?: string;
  onClose?: () => void;
  onSaved?: () => void;
} = {}) {
  return render(
    <TeamFocusDrawer
      taskId={taskId}
      networkElementType={networkElementType}
      onClose={onClose}
      onSaved={onSaved}
    />,
  );
}

function DrawerTaskSwitchHarness({ onClose = vi.fn(), onSaved = vi.fn() }: {
  onClose?: () => void;
  onSaved?: () => void;
}) {
  const [taskId, setTaskId] = useState("task-umf");
  return (
    <>
      <button type="button" onClick={() => setTaskId("task-umf-next")}>切换任务</button>
      <TeamFocusDrawer
        taskId={taskId}
        networkElementType="UMF"
        onClose={onClose}
        onSaved={onSaved}
      />
    </>
  );
}

function DrawerHarness({ onClose = vi.fn(), onSaved = vi.fn() }: {
  onClose?: () => void;
  onSaved?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开团队关注</button>
      {open ? (
        <TeamFocusDrawer
          taskId="task-umf"
          networkElementType="UMF"
          onClose={() => {
            onClose();
            setOpen(false);
          }}
          onSaved={onSaved}
        />
      ) : null}
    </>
  );
}

describe("TeamFocusDrawer", () => {
  beforeEach(() => {
    vi.mocked(api.listKpiTaskMetricsV6).mockResolvedValue(makeMetricPage());
    vi.mocked(api.listKpiTeamFocusV6).mockResolvedValue(makeFocusPage());
    vi.mocked(api.patchKpiTeamFocusV6).mockResolvedValue(PATCH_RESPONSE);
  });

  it("复用全部指标目录并支持搜索和测量单元筛选", async () => {
    renderDrawer();

    expect(await screen.findByText("媒体资源创建成功率")).toBeDefined();
    expect(api.listKpiTaskMetricsV6).toHaveBeenCalledWith("task-umf", {
      view: "all",
      page: 1,
      page_size: 200,
    });
    expect(api.listKpiTeamFocusV6).toHaveBeenCalledWith("UMF", {
      task_id: "task-umf",
      page: 1,
      page_size: 200,
    });

    const search = screen.getByLabelText("搜索指标名称、指标 ID 或测量单元");
    await userEvent.type(search, "删除");
    expect(screen.getAllByTestId("team-focus-metric-row")).toHaveLength(1);
    expect(screen.getByText("媒体资源删除请求数")).toBeDefined();

    await userEvent.clear(search);
    await userEvent.selectOptions(screen.getByLabelText("按测量单元筛选"), "MU_SIGNAL");
    expect(screen.getAllByTestId("team-focus-metric-row")).toHaveLength(1);
    expect(screen.getByText("S1 切换成功率")).toBeDefined();
  });

  it("批量加入和移出只暂存在本地，保存时提交原子差异", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    renderDrawer({ onSaved, onClose });

    await screen.findByText("媒体资源创建成功率");
    await userEvent.click(screen.getByRole("button", { name: "全选当前结果" }));
    expect(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" })).toHaveProperty("checked", true);
    expect(screen.getByRole("checkbox", { name: "关注S1 切换成功率" })).toHaveProperty("checked", true);

    await userEvent.click(screen.getByRole("button", { name: "移出当前结果" }));
    expect(screen.getByRole("checkbox", { name: "关注媒体资源创建成功率" })).toHaveProperty("checked", false);

    await userEvent.click(screen.getByRole("button", { name: "全选当前结果" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源创建成功率" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "关注历史消息投递成功率" }));
    expect(await screen.findByText("2 项待加入 · 1 项待移出")).toBeDefined();
    expect(api.patchKpiTeamFocusV6).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "保存团队关注" }));

    await waitFor(() => {
      expect(api.patchKpiTeamFocusV6).toHaveBeenCalledWith("UMF", {
        task_id: "task-umf",
        expected_revision: 4,
        add: [
          { measurement_unit_id: "MU_MEDIA", metric_resource_id: "ME_MEDIA_DELETION_REQUESTS" },
          { measurement_unit_id: "MU_SIGNAL", metric_resource_id: "ME_S1_HANDOVER_SUCCESS_RATE" },
        ],
        remove: [
          { measurement_unit_id: "MU_MEDIA", metric_resource_id: "ME_MEDIA_CREATION_SUCCESS_RATE" },
        ],
      });
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("有未保存修改时关闭先确认，可继续编辑或放弃", async () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });
    await screen.findByText("媒体资源创建成功率");

    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }));
    await userEvent.click(screen.getByRole("button", { name: "关闭团队关注" }));

    const confirm = screen.getByRole("alertdialog", { name: "放弃未保存的修改？" });
    expect(within(confirm).getByText("关闭后，本次加入或移出不会保存。")).toBeDefined();
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.click(within(confirm).getByRole("button", { name: "继续编辑" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" })).toHaveProperty("checked", true);

    await userEvent.click(screen.getByRole("button", { name: "关闭团队关注" }));
    await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("revision 冲突时提示最新版本并保留本地暂存", async () => {
    vi.mocked(api.patchKpiTeamFocusV6).mockRejectedValue(
      new ApiError("team_focus_revision_conflict", "团队关注已被其他维护人员更新。", 409, {
        current_revision: 5,
      }),
    );
    const onSaved = vi.fn();
    const onClose = vi.fn();
    renderDrawer({ onSaved, onClose });
    await screen.findByText("媒体资源创建成功率");

    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }));
    await userEvent.click(screen.getByRole("button", { name: "保存团队关注" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("团队关注已被其他维护人员更新");
    expect(alert.textContent).toContain("当前共享版本 5");
    expect(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" })).toHaveProperty("checked", true);
    expect(screen.getByRole("button", { name: "保存团队关注" })).toBeDefined();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("冲突后可基于最新关注重放本地修改，且不覆盖其他人的新增", async () => {
    const latestFocusPage = makeFocusPage({
      revision: 5,
      total: 3,
      available_count: 2,
      items: [
        ...makeFocusPage().items,
        {
          network_element_type: "UMF",
          measurement_unit_id: "MU_SIGNAL",
          measurement_unit_name: "信令测量单元",
          metric_resource_id: "ME_S1_HANDOVER_SUCCESS_RATE",
          metric_name: "S1 切换成功率",
          availability: "available",
          availability_reason: null,
          added_by: "other-maintainer",
          added_at: "2026-11-05T08:30:00Z",
        },
      ],
    });
    vi.mocked(api.patchKpiTeamFocusV6)
      .mockRejectedValueOnce(
        new ApiError("team_focus_revision_conflict", "团队关注已被其他维护人员更新。", 409, {
          current_revision: 5,
        }),
      )
      .mockResolvedValueOnce(PATCH_RESPONSE);
    const onSaved = vi.fn();
    const onClose = vi.fn();
    renderDrawer({ onSaved, onClose });
    await screen.findByText("媒体资源创建成功率");

    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }));
    await userEvent.click(screen.getByRole("button", { name: "保存团队关注" }));
    await screen.findByText("当前共享版本 5，你的暂存选择已保留。");

    vi.mocked(api.listKpiTeamFocusV6).mockResolvedValueOnce(latestFocusPage);
    await userEvent.click(screen.getByRole("button", { name: "载入最新版本并保留修改" }));

    await waitFor(() => expect(api.listKpiTeamFocusV6).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("checkbox", { name: "关注S1 切换成功率" })).toHaveProperty("checked", true);
    expect(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" })).toHaveProperty("checked", true);
    expect(screen.getByText("1 项待加入 · 0 项待移出")).toBeDefined();

    await userEvent.click(screen.getByRole("button", { name: "保存团队关注" }));
    await waitFor(() => {
      expect(api.patchKpiTeamFocusV6).toHaveBeenLastCalledWith("UMF", {
        task_id: "task-umf",
        expected_revision: 5,
        add: [
          { measurement_unit_id: "MU_MEDIA", metric_resource_id: "ME_MEDIA_DELETION_REQUESTS" },
        ],
        remove: [],
      });
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("只读用户不能修改或提交关注", async () => {
    vi.mocked(api.listKpiTeamFocusV6).mockResolvedValue(makeFocusPage({ can_write: false }));
    renderDrawer();

    const checkbox = await screen.findByRole("checkbox", { name: "关注媒体资源创建成功率" });
    expect(checkbox).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: "保存团队关注" })).toBeNull();
    expect(screen.getByText("你当前为只读访问")).toBeDefined();
  });

  it("切换任务时清空筛选、选择与未保存差异", async () => {
    const onClose = vi.fn();
    render(<DrawerTaskSwitchHarness onClose={onClose} />);
    await screen.findByText("媒体资源创建成功率");

    await userEvent.type(screen.getByLabelText("搜索指标名称、指标 ID 或测量单元"), "删除");
    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }));
    expect(screen.getByText("1 项待加入 · 0 项待移出")).toBeDefined();

    vi.mocked(api.listKpiTaskMetricsV6).mockResolvedValueOnce(makeMetricPage());
    vi.mocked(api.listKpiTeamFocusV6).mockResolvedValueOnce(makeFocusPage());
    await userEvent.click(screen.getByRole("button", { name: "切换任务" }));

    await waitFor(() => {
      expect(api.listKpiTaskMetricsV6).toHaveBeenLastCalledWith("task-umf-next", {
        view: "all",
        page: 1,
        page_size: 200,
      });
    });
    expect(screen.getByLabelText("搜索指标名称、指标 ID 或测量单元")).toHaveProperty("value", "");
    await screen.findByText("S1 切换成功率");
    expect(screen.queryByText(/项待加入/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "关闭团队关注" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("Escape 关闭无修改的抽屉并恢复触发按钮焦点", async () => {
    const onClose = vi.fn();
    render(<DrawerHarness onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "打开团队关注" });

    await userEvent.click(trigger);
    const close = await screen.findByRole("button", { name: "关闭团队关注" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(document.activeElement).toBe(trigger);
  });

  it("Escape 遇到未保存修改时先确认并把焦点移入确认框", async () => {
    const onClose = vi.fn();
    render(<DrawerHarness onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "打开团队关注" }));
    await screen.findByText("媒体资源创建成功率");

    await userEvent.click(screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }));
    await userEvent.keyboard("{Escape}");

    const confirm = await screen.findByRole("alertdialog", { name: "放弃未保存的修改？" });
    expect(onClose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(within(confirm).getByRole("button", { name: "继续编辑" }));

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(document.activeElement).toBe(
      screen.getByRole("checkbox", { name: "关注媒体资源删除请求数" }),
    );
  });

  it("Tab 焦点限制在抽屉内循环", async () => {
    renderDrawer();
    await screen.findByText("媒体资源创建成功率");

    const dialog = screen.getByRole("dialog", { name: "管理团队关注" });
    const close = within(dialog).getByRole("button", { name: "关闭团队关注" });
    const checkboxes = within(dialog).getAllByRole("checkbox");
    const last = checkboxes[checkboxes.length - 1];
    last.focus();
    expect(document.activeElement).toBe(last);

    await userEvent.tab();

    expect(document.activeElement).toBe(close);
  });
});
