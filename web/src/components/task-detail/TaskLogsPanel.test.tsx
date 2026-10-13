import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SCENE_CLEANED_ADVICE } from "../../utils/sceneError";
import { TaskLogsPanel } from "./TaskLogsPanel";

describe("TaskLogsPanel", () => {
  it("现场已清理时展示服务端消息与后续建议，且不展示空白日志或重试", () => {
    render(
      <TaskLogsPanel
        logs={[]}
        error={{
          message: "执行日志不入库，已随磁盘现场清理，不可查看",
          code: "scene_cleaned",
          statusCode: 410,
        }}
        onRetry={vi.fn()}
        retrying={false}
      />,
    );

    expect(screen.getByText("执行日志不入库，已随磁盘现场清理，不可查看")).toBeTruthy();
    expect(screen.getByText(SCENE_CLEANED_ADVICE)).toBeTruthy();
    expect(screen.queryByText("暂无日志")).toBeNull();
    expect(screen.queryByRole("button", { name: /重试/ })).toBeNull();
  });

  it("其他错误保持可重试的错误态", () => {
    render(
      <TaskLogsPanel
        logs={[]}
        error={{ message: "日志加载失败" }}
        onRetry={vi.fn()}
        retrying={false}
      />,
    );

    expect(screen.getByText("日志加载失败")).toBeTruthy();
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
  });

  it("无错误时照常展示日志", () => {
    render(
      <TaskLogsPanel
        logs={[{ ts: 1, level: "info", message: "任务开始" } as never]}
        error={null}
        onRetry={vi.fn()}
        retrying={false}
      />,
    );

    expect(screen.getByText("任务开始")).toBeTruthy();
  });
});
