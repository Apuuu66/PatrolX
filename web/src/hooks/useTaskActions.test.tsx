import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const rerunTask = vi.hoisted(() => vi.fn());
const rebuildTask = vi.hoisted(() => vi.fn());
const updateTaskDeviceId = vi.hoisted(() => vi.fn());

vi.mock("../api/http", () => ({
  api: { rerunTask, rebuildTask, updateTaskDeviceId },
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

const { ApiError } = await import("../api/http");
const { useTaskActions } = await import("./useTaskActions");

const wrapper = ({ children }: { children: ReactNode }) => <App>{children}</App>;

describe("useTaskActions", () => {
  beforeEach(() => {
    rerunTask.mockReset();
    rebuildTask.mockReset();
    updateTaskDeviceId.mockReset();
  });

  it("重跑遇现场已清理时给出恢复建议，而不是静默失败", async () => {
    rerunTask.mockRejectedValue(
      new ApiError("scene_cleaned", "磁盘现场已清理，无法重跑", 410),
    );
    const reload = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskActions("task-1", reload), { wrapper });

    await act(async () => {
      await result.current.rerunAll();
    });

    await waitFor(() => expect(screen.getByText(/磁盘现场已清理，无法重跑/)).toBeTruthy());
    expect(screen.getByText(/重新上传同名数据包/)).toBeTruthy();
    expect(screen.getByText(/核心数据仍可在界面查询/)).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });

  it("增量重建遇现场已清理时同样给出恢复建议", async () => {
    rebuildTask.mockRejectedValue(
      new ApiError("scene_cleaned", "磁盘现场已清理，无法重建", 410),
    );
    const reload = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskActions("task-1", reload), { wrapper });

    act(() => {
      result.current.rebuild.setRuleCodes(["log.error_density"]);
    });
    await act(async () => {
      await result.current.rebuild.rebuild();
    });

    await waitFor(() => expect(screen.getByText(/磁盘现场已清理，无法重建/)).toBeTruthy());
    expect(screen.getByText(/重新上传同名数据包/)).toBeTruthy();
  });

  it("其他错误仍以轻量提示反馈", async () => {
    rerunTask.mockRejectedValue(new ApiError("conflict", "任务正在执行中", 409));
    const reload = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskActions("task-1", reload), { wrapper });

    await act(async () => {
      await result.current.rerunAll();
    });

    await waitFor(() => expect(screen.getByText("任务正在执行中")).toBeTruthy());
    expect(screen.queryByText(/重新上传同名数据包/)).toBeNull();
  });
  it("设备 ID 不在台账时保留服务端拒绝消息且不刷新任务数据", async () => {
    updateTaskDeviceId.mockRejectedValue(
      new ApiError("device_not_found", "设备 ID 不存在于设备台账", 400),
    );
    const reload = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskActions("task-1", reload), { wrapper });

    act(() => {
      result.current.device.openModal("device-old");
    });
    await act(async () => {
      await result.current.device.save();
    });

    expect(result.current.device.error).toBe("设备 ID 不存在于设备台账");
    expect(result.current.device.open).toBe(true);
    expect(result.current.device.value).toBe("device-old");
    expect(reload).not.toHaveBeenCalled();
  });

  it("设备 ID 保存成功后关闭弹窗并刷新任务数据", async () => {
    updateTaskDeviceId.mockResolvedValue({});
    const reload = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useTaskActions("task-1", reload), { wrapper });

    act(() => {
      result.current.device.openModal("device-in-ledger");
    });
    await act(async () => {
      await result.current.device.save();
    });

    expect(updateTaskDeviceId).toHaveBeenCalledWith("task-1", "device-in-ledger");
    expect(result.current.device.open).toBe(false);
    expect(result.current.device.error).toBeNull();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
