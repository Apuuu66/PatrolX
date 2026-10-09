import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

import type { RuleFinding } from "../api/http";
import { FindingItem } from "./FindingItem";

function makeFinding(overrides: Partial<RuleFinding> = {}): RuleFinding {
  return {
    finding_id: "finding-1",
    title: "未清除且反复的告警：1051 / UMF核心服务",
    severity: "critical",
    source_file: "alarm/alarm_history_202609.csv",
    evidence: "出现 3 次（已清除 0 / 未清除 3）；最短复发间隔 600 秒",
    details: "判定为 未清除且反复",
    recommendation: "优先处置未清除且反复的告警",
    metrics: null,
    ...overrides,
  } as RuleFinding;
}

function renderItem(finding: RuleFinding) {
  return render(
    <App>
      <FindingItem finding={finding} />
    </App>,
  );
}

describe("FindingItem", () => {
  it("来源 / 证据 / 详情 / 建议分行渲染，证据按分号拆成键值分段并高亮数值", () => {
    const { container } = renderItem(makeFinding());

    expect(screen.getByTestId("finding-field-source").textContent).toContain(
      "alarm/alarm_history_202609.csv",
    );
    expect(screen.getByTestId("finding-field-details").textContent).toContain("未清除且反复");
    expect(screen.getByTestId("finding-field-recommendation").textContent).toContain("优先处置");

    const parts = container.querySelectorAll("[data-evidence-part]");
    expect(parts).toHaveLength(2);
    expect(parts[0]!.textContent).toBe("出现3 次（已清除 0 / 未清除 3）");
    expect(parts[1]!.textContent).toBe("最短复发间隔600 秒");

    const highlights = Array.from(container.querySelectorAll(".rule-finding-highlight")).map(
      (node) => node.textContent,
    );
    expect(highlights).toContain("3 次");
    expect(highlights).toContain("0");
    expect(highlights).toContain("3");
  });

  it("超过 4 行默认折叠，展开后可查看全部分段", async () => {
    const user = userEvent.setup();
    const evidence = Array.from({ length: 5 }, (_, index) => `分组 105${index}；出现 ${index} 次`).join(
      "；",
    );
    const { container } = renderItem(makeFinding({ evidence }));

    const collapsedCount = container.querySelectorAll("[data-evidence-part]").length;
    expect(collapsedCount).toBeGreaterThan(0);
    expect(collapsedCount).toBeLessThan(10);

    const toggle = screen.getByRole("button", { name: "展开其余证据" });

    await user.click(toggle);
    expect(container.querySelectorAll("[data-evidence-part]")).toHaveLength(10);
    await user.click(screen.getByRole("button", { name: "收起证据" }));
    expect(container.querySelectorAll("[data-evidence-part]").length).toBeLessThan(10);
  });

  it("未超过 4 行时不渲染折叠入口", () => {
    renderItem(makeFinding());
    expect(screen.queryByRole("button", { name: /展开其余证据|收起证据/ })).toBeNull();
  });

  it("无法识别键值时降级为自由文本分段，不丢信息", () => {
    const { container } = renderItem(
      makeFinding({ evidence: "结构未知的A段；结构未知的B段", details: null, recommendation: null }),
    );

    const parts = Array.from(container.querySelectorAll("[data-evidence-part]")).map(
      (node) => node.textContent,
    );
    expect(parts).toEqual(["结构未知的A段", "结构未知的B段"]);
    expect(container.querySelectorAll(".rule-finding-evidence-label")).toHaveLength(0);
  });

  it("空证据不渲染证据行；来源路径可复制", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    renderItem(makeFinding({ evidence: null, details: null, recommendation: null }));

    expect(screen.queryByTestId("finding-field-evidence")).toBeNull();

    const copyButton = screen.getByRole("button", { name: "复制来源路径" });
    await user.click(copyButton);

    expect(writeText).toHaveBeenCalledWith("alarm/alarm_history_202609.csv");
    expect(copyButton.dataset.copyState).toBe("copied");
    expect(screen.queryByTestId("copy-text-fallback")).toBeNull();
  });
});
