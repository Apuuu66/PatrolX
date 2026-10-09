import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_TABLE_DENSITY,
  TABLE_DENSITY_STORAGE_KEY,
  readTableDensity,
  useTableDensity,
} from "./useTableDensity";

describe("useTableDensity", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("默认使用紧凑密度", () => {
    const { result } = renderHook(() => useTableDensity());

    expect(result.current.density).toBe(DEFAULT_TABLE_DENSITY);
    expect(result.current.density).toBe("compact");
    expect(result.current.tableSize).toBe("small");
  });

  it("读取已保存的舒适密度并映射到 AntD 尺寸", () => {
    window.localStorage.setItem(TABLE_DENSITY_STORAGE_KEY, "comfortable");
    const { result } = renderHook(() => useTableDensity());

    expect(result.current.density).toBe("comfortable");
    expect(result.current.tableSize).toBe("middle");
  });

  it("切换后写入本地存储且可再次读取", () => {
    const { result } = renderHook(() => useTableDensity());

    act(() => {
      result.current.setDensity("comfortable");
    });

    expect(result.current.density).toBe("comfortable");
    expect(window.localStorage.getItem(TABLE_DENSITY_STORAGE_KEY)).toBe("comfortable");
  });

  it("非法值与读取失败静默回退默认", () => {
    window.localStorage.setItem(TABLE_DENSITY_STORAGE_KEY, "huge");
    expect(readTableDensity()).toBe("compact");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(readTableDensity()).toBe("compact");
  });

  it("写入失败不抛错", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const { result } = renderHook(() => useTableDensity());

    expect(() => {
      act(() => {
        result.current.setDensity("comfortable");
      });
    }).not.toThrow();
    expect(result.current.density).toBe("comfortable");
  });
});
