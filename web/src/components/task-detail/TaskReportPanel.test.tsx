import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const getTaskReportHtml = vi.hoisted(() => vi.fn());

vi.mock("../../api/http", () => ({
  reportUrl: (taskId: string) => `/api/v2/tasks/${taskId}/report`,
  api: { getTaskReportHtml },
  ApiError: class ApiError extends Error {
    code: string;
    status: number;
    constructor(code: string, message: string, status: number) {
      super(message);
      this.code = code;
      this.status = status;
    }
  },
}));

const { TaskReportPanel } = await import("./TaskReportPanel");
const { ApiError } = await import("../../api/http");

describe("TaskReportPanel", () => {
  it("现场已清理时展示服务端消息与恢复建议，不再渲染空白报告框", async () => {
    getTaskReportHtml.mockRejectedValue(
      new ApiError("scene_cleaned", "报告已随磁盘现场清理，不可查看", 410),
    );

    render(<TaskReportPanel taskId="task-1" />);

    expect(await screen.findByText("报告已随磁盘现场清理，不可查看")).toBeTruthy();
    expect(screen.getByText(/核心数据仍可在界面查询/)).toBeTruthy();
    expect(screen.queryByTitle("巡检报告")).toBeNull();
  });

  it("报告可读时渲染报告内容", async () => {
    getTaskReportHtml.mockResolvedValue("<!doctype html><html><body>报告正文</body></html>");

    render(<TaskReportPanel taskId="task-1" />);

    await waitFor(() => expect(screen.getByTitle("巡检报告")).toBeTruthy());
    expect(screen.getByTitle("巡检报告").getAttribute("srcdoc")).toContain("报告正文");
  });

  it("报告未生成等其他错误展示可重试错误态", async () => {
    getTaskReportHtml.mockRejectedValue(new ApiError("not_found", "报告未生成", 404));

    render(<TaskReportPanel taskId="task-1" />);

    expect(await screen.findByText("报告未生成")).toBeTruthy();
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
  });
});
