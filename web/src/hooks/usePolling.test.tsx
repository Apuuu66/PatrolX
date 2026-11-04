import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "./usePolling";

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not overlap polls while the previous request is still pending", async () => {
    let finishFirst: (() => void) | undefined;
    const callback = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishFirst = resolve;
        }),
    );

    renderHook(() => usePolling(callback, 2000, true));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishFirst?.();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(callback).toHaveBeenCalledTimes(2);
  });
});
