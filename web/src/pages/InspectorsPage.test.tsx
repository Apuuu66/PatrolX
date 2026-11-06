import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/client";
import { api } from "../api/http";
import { apiMe, setSession } from "../api/auth";
import { AuthProvider } from "../auth/AuthContext";
import { TABLE_DENSITY_STORAGE_KEY } from "../hooks/useTableDensity";
import { InspectorsPage } from "./InspectorsPage";

type RuleAssignment = components["schemas"]["KpiRuleNetworkAssignmentV6"];
type RuleAssignmentPage = components["schemas"]["KpiRuleNetworkAssignmentPageV6"];
type RuleAssignmentWrite = components["schemas"]["KpiRuleAssignmentWriteResultV6"];
type RuleAssignmentBatch = components["schemas"]["KpiRuleAssignmentBatchResponseV6"];

vi.mock("../api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/auth")>();
  return { ...actual, apiMe: vi.fn() };
});

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listDicts: vi.fn(),
    listKpiRuleNetworkAssignmentsV6: vi.fn(),
    updateKpiRuleNetworkAssignmentV6: vi.fn(),
    batchUpdateKpiRuleNetworkAssignmentsV6: vi.fn(),
  },
}));

const DICTS = {
  province: [],
  operator: [],
  product: [
    { code: "UMF", name: "统一消息功能" },
    { code: "CSP", name: "云业务平台" },
    { code: "IMS", name: "IMS 核心网" },
  ],
  version: [],
};

function makeAssignment(overrides: Partial<RuleAssignment> = {}): RuleAssignment {
  const networkElementTypes = overrides.network_element_types ?? ["UMF"];
  return {
    rule_code: "config.a",
    name: "配置一致性",
    category: "config",
    priority: 1,
    rule_version: "1.0.0",
    description: "检查配置一致性",
    recommendation: "核对配置差异",
    assignment_state: networkElementTypes.length > 0 ? "assigned" : "unassigned",
    network_element_types: networkElementTypes,
    revision: networkElementTypes.length > 0 ? 1 : 0,
    updated_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    updated_by: "maintainer",
    ...overrides,
  };
}

function makeAssignmentPage(
  items: RuleAssignment[],
  overrides: Partial<RuleAssignmentPage> = {},
): RuleAssignmentPage {
  return {
    global_revision: 7,
    page: 1,
    page_size: 10,
    total: items.length,
    can_write: true,
    items,
    ...overrides,
  };
}

function makeWriteResult(
  ruleCode: string,
  networkElementTypes: string[],
  revision = 4,
): RuleAssignmentWrite {
  return {
    rule_code: ruleCode,
    assignment_state: networkElementTypes.length > 0 ? "assigned" : "unassigned",
    network_element_types: networkElementTypes,
    revision,
    global_revision: 8,
    audit_id: `audit-${ruleCode}`,
    updated_at: new Date().toISOString(),
    snapshot_notice: "归属变更只影响后续启动或显式重建的任务。",
  };
}

function makeBatchResult(items: RuleAssignmentWrite[]): RuleAssignmentBatch {
  return {
    global_revision: 8,
    items,
    audit_ids: items.map((item) => `audit-${item.rule_code}`),
  };
}

function renderPage() {
  return render(
    <App>
      <AuthProvider>
        <InspectorsPage />
      </AuthProvider>
    </App>,
  );
}

async function findRow(ruleCode: string): Promise<HTMLElement> {
  const code = await screen.findByText(ruleCode);
  const row = code.closest("tr");
  expect(row).not.toBeNull();
  return row as HTMLElement;
}

async function findDialogByTitle(title: string): Promise<HTMLElement> {
  // rc-util 在测试环境会把所有弹窗的 aria-labelledby 固定为 test-id，
  // 因此从唯一标题定位弹窗，避免并行弹窗无法按可访问名称区分。
  const titleNode = await screen.findByText(title);
  const dialog = titleNode.closest('[role="dialog"]');
  expect(dialog).not.toBeNull();
  return dialog as HTMLElement;
}

async function chooseAssignmentFilter(label: string) {
  const user = userEvent.setup();
  const combobox = screen.getByRole("combobox", { name: "归属筛选" });
  const selector = combobox.closest(".ant-select")?.querySelector(".ant-select-selector");
  expect(selector).not.toBeNull();
  fireEvent.mouseDown(selector as Element);
  const optionLabel = await screen.findByTitle(label);
  const optionItem = optionLabel.closest(".ant-select-item-option");
  expect(optionItem).not.toBeNull();
  await user.click(optionItem as Element);
}

describe("InspectorsPage 规则网元归属", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setSession("token-for-test", { username: "admin", role: "admin" });
    vi.mocked(apiMe).mockResolvedValue({ username: "admin", role: "admin" });
    vi.mocked(api.listDicts).mockResolvedValue(DICTS);
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(makeAssignmentPage([]));
    vi.mocked(api.updateKpiRuleNetworkAssignmentV6).mockResolvedValue(
      makeWriteResult("config.a", ["UMF"]),
    );
    vi.mocked(api.batchUpdateKpiRuleNetworkAssignmentsV6).mockResolvedValue(makeBatchResult([]));
  });

  it("展示多归属标签和未归属待配置状态，不再提供规则级启停", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([
        makeAssignment({
          rule_code: "rule.multi",
          name: "多网元规则",
          network_element_types: ["UMF", "CSP"],
        }),
        makeAssignment({
          rule_code: "rule.unassigned",
          name: "待配置规则",
          network_element_types: [],
          revision: 0,
          updated_at: null,
          updated_by: null,
        }),
      ]),
    );

    renderPage();

    const multiRow = await findRow("rule.multi");
    expect(within(multiRow).getByText("UMF")).toBeDefined();
    expect(within(multiRow).getByText("CSP")).toBeDefined();

    const unassignedRow = await findRow("rule.unassigned");
    expect(within(unassignedRow).getByText("未归属")).toBeDefined();
    expect(within(unassignedRow).getByText("待配置 · 不执行")).toBeDefined();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByText(/无公共规则/)).toBeDefined();
  });

  it("按网元类型或未归属筛选，并分别使用互斥的服务端查询参数", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([makeAssignment()]),
    );

    renderPage();
    await findRow("config.a");

    await chooseAssignmentFilter("UMF");
    await waitFor(() =>
      expect(api.listKpiRuleNetworkAssignmentsV6).toHaveBeenLastCalledWith(
        expect.objectContaining({ network_element_type: "UMF", page: 1 }),
      ),
    );
    const networkQuery = vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mock.lastCall?.[0];
    expect(networkQuery?.assignment_state).toBeUndefined();

    await chooseAssignmentFilter("未归属");
    await waitFor(() =>
      expect(api.listKpiRuleNetworkAssignmentsV6).toHaveBeenLastCalledWith(
        expect.objectContaining({ assignment_state: "unassigned", page: 1 }),
      ),
    );
    const unassignedQuery = vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mock.lastCall?.[0];
    expect(unassignedQuery?.network_element_type).toBeUndefined();
  });

  it("单条设置支持动态网元类型多选并按当前 revision 提交", async () => {
    const current = makeAssignment({ revision: 3, network_element_types: ["UMF"] });
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([current]),
    );
    vi.mocked(api.updateKpiRuleNetworkAssignmentV6).mockResolvedValue(
      makeWriteResult("config.a", ["UMF", "CSP"], 4),
    );

    renderPage();
    const row = await findRow("config.a");
    const user = userEvent.setup();
    await user.click(within(row).getByRole("button", { name: "编辑归属" }));

    const dialog = await findDialogByTitle("编辑规则归属");
    expect((within(dialog).getByRole("checkbox", { name: "UMF" }) as HTMLInputElement).checked).toBe(true);
    expect((within(dialog).getByRole("checkbox", { name: "CSP" }) as HTMLInputElement).checked).toBe(false);
    expect((within(dialog).getByRole("checkbox", { name: "IMS" }) as HTMLInputElement).checked).toBe(false);

    await user.click(within(dialog).getByRole("checkbox", { name: "CSP" }));
    await user.click(within(dialog).getByRole("button", { name: "保存归属" }));

    await waitFor(() =>
      expect(api.updateKpiRuleNetworkAssignmentV6).toHaveBeenCalledWith("config.a", {
        expected_revision: 3,
        network_element_types: ["UMF", "CSP"],
        confirm_unassign: false,
      }),
    );
    await waitFor(() => {
      expect(within(row).getByText("CSP")).toBeDefined();
    });
  });

  it("清空最后归属必须二次确认，取消不提交，确认后进入未归属", async () => {
    const current = makeAssignment({ revision: 3, network_element_types: ["UMF"] });
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([current]),
    );
    vi.mocked(api.updateKpiRuleNetworkAssignmentV6).mockResolvedValue(
      makeWriteResult("config.a", [], 4),
    );

    renderPage();
    const row = await findRow("config.a");
    const user = userEvent.setup();
    await user.click(within(row).getByRole("button", { name: "编辑归属" }));

    const editDialog = await findDialogByTitle("编辑规则归属");
    const umfCheckbox = within(editDialog).getByRole("checkbox", { name: "UMF" }) as HTMLInputElement;
    await user.click(umfCheckbox);
    expect(umfCheckbox.checked).toBe(false);
    await user.click(within(editDialog).getByRole("button", { name: "保存归属" }));

    const firstConfirm = await findDialogByTitle("确认清空规则归属");
    expect(within(firstConfirm).getByText(/停止参与后续任务/)).toBeDefined();
    await user.click(within(firstConfirm).getByRole("button", { name: /取\s*消/ }));
    expect(api.updateKpiRuleNetworkAssignmentV6).not.toHaveBeenCalled();

    await user.click(within(editDialog).getByRole("button", { name: "保存归属" }));
    const secondConfirm = await findDialogByTitle("确认清空规则归属");
    await user.click(within(secondConfirm).getByRole("button", { name: "确认清空" }));

    await waitFor(() =>
      expect(api.updateKpiRuleNetworkAssignmentV6).toHaveBeenCalledWith("config.a", {
        expected_revision: 3,
        network_element_types: [],
        confirm_unassign: true,
      }),
    );
    await waitFor(() => {
      expect(within(row).getByText("未归属")).toBeDefined();
      expect(within(row).getByText("待配置 · 不执行")).toBeDefined();
    });
  });

  it("批量设置只提交归属发生变化的规则并保留各规则 revision", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([
        makeAssignment({
          rule_code: "rule.umf",
          name: "UMF 规则",
          network_element_types: ["UMF"],
          revision: 1,
        }),
        makeAssignment({
          rule_code: "rule.csp",
          name: "CSP 规则",
          network_element_types: ["CSP"],
          revision: 2,
        }),
        makeAssignment({
          rule_code: "rule.unassigned",
          name: "未归属规则",
          network_element_types: [],
          revision: 0,
        }),
      ]),
    );
    vi.mocked(api.batchUpdateKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeBatchResult([
        makeWriteResult("rule.umf", ["CSP"], 2),
        makeWriteResult("rule.unassigned", ["CSP"], 1),
      ]),
    );

    renderPage();
    const umfRow = await findRow("rule.umf");
    const cspRow = await findRow("rule.csp");
    const unassignedRow = await findRow("rule.unassigned");
    const user = userEvent.setup();

    await user.click(within(umfRow).getByRole("checkbox"));
    await user.click(within(unassignedRow).getByRole("checkbox"));
    await user.click(within(cspRow).getByRole("checkbox"));
    await user.click(within(cspRow).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /批量设置归属/ }));

    const dialog = await findDialogByTitle("批量设置规则归属");
    await user.click(within(dialog).getByRole("checkbox", { name: "CSP" }));
    await user.click(within(dialog).getByRole("button", { name: "保存批量归属" }));

    await waitFor(() =>
      expect(api.batchUpdateKpiRuleNetworkAssignmentsV6).toHaveBeenCalledWith({
        items: [
          {
            rule_code: "rule.umf",
            expected_revision: 1,
            network_element_types: ["CSP"],
            confirm_unassign: false,
          },
          {
            rule_code: "rule.unassigned",
            expected_revision: 0,
            network_element_types: ["CSP"],
            confirm_unassign: false,
          },
        ],
      }),
    );
    expect(await screen.findByText("已更新 2 条规则归属")).toBeDefined();
  });

  it("服务端 can_write=false 时隐藏全部编辑控件并展示只读说明", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([makeAssignment()], { can_write: false }),
    );

    renderPage();
    const row = await findRow("config.a");

    expect(within(row).queryByRole("button", { name: "编辑归属" })).toBeNull();
    expect(screen.queryByRole("button", { name: /批量设置归属/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("只读")).toBeDefined();
    expect(screen.getByText(/仅可查看/)).toBeDefined();
  });

  it("快速搜索时晚返回的旧请求不会覆盖新筛选结果", async () => {
    let resolveInitial: ((value: RuleAssignmentPage) => void) | undefined;
    const initialRequest = new Promise<RuleAssignmentPage>((resolve) => {
      resolveInitial = resolve;
    });
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6)
      .mockImplementationOnce(() => initialRequest)
      .mockResolvedValueOnce(
        makeAssignmentPage([
          makeAssignment({ rule_code: "kpi.measurement_units", name: "KPI 测量单元检查" }),
        ]),
      );

    renderPage();
    await waitFor(() => expect(api.listKpiRuleNetworkAssignmentsV6).toHaveBeenCalledTimes(1));

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("搜索编码 / 名称"), "kpi.measurement_units{Enter}");
    await waitFor(() =>
      expect(api.listKpiRuleNetworkAssignmentsV6).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "kpi.measurement_units" }),
      ),
    );
    await screen.findByText("kpi.measurement_units");

    expect(resolveInitial).toBeTypeOf("function");
    await act(async () => {
      resolveInitial?.(
        makeAssignmentPage([
          makeAssignment({ rule_code: "config.old" }),
          makeAssignment({ rule_code: "config.new" }),
        ]),
      );
      await Promise.resolve();
    });

    expect(screen.queryByText("config.old")).toBeNull();
    expect(screen.getByText("kpi.measurement_units")).toBeDefined();
  });

  it("更新时间使用相对时间并支持表头排序", async () => {
    const older = makeAssignment({
      rule_code: "config.old",
      updated_at: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    });
    const newer = makeAssignment({
      rule_code: "config.new",
      updated_at: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    });
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([older, newer]),
    );

    renderPage();

    const updatedAt = await screen.findAllByTestId("rule-assignment-updated-at");
    expect(updatedAt[0]?.textContent).toMatch(/天前|小时前/);
    expect(updatedAt[0]?.classList.contains("tabular-nums")).toBe(true);

    const header = screen.getByText("更新时间").closest("th");
    expect(header?.className).toContain("ant-table-column-has-sorters");
    const user = userEvent.setup();
    await user.click(header as HTMLElement);

    await waitFor(() => {
      const codes = screen.getAllByText(/^config\./).map((node) => node.textContent);
      expect(codes).toEqual(["config.old", "config.new"]);
    });
  });

  it("密度切换默认紧凑，切换到舒适后写入本地偏好且表体行高联动", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([makeAssignment()]),
    );

    renderPage();

    const table = (await screen.findByText("config.a")).closest("table");
    const tableWrapper = table?.closest(".inspectors-table");
    expect(tableWrapper?.classList.contains("density-compact")).toBe(true);
    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "舒适" }));

    expect(screen.getByRole("button", { name: "舒适" }).getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBe("comfortable");
    await waitFor(() => {
      expect(tableWrapper?.classList.contains("density-comfortable")).toBe(true);
    });
  });

  it("规则编码使用等宽字体并保留复制入口", async () => {
    vi.mocked(api.listKpiRuleNetworkAssignmentsV6).mockResolvedValue(
      makeAssignmentPage([makeAssignment()]),
    );

    renderPage();

    const code = await screen.findByText("config.a");
    expect(code.closest(".inspectors-code")).not.toBeNull();
    const row = code.closest("tr");
    expect(within(row as HTMLElement).getByRole("button", { name: /复制|copy/i })).toBeDefined();
  });
});
