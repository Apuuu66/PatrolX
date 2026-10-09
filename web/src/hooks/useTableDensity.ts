import { useCallback, useState } from "react";

/** 表格密度（FR-016、data-model §4、R11）。 */
export type TableDensity = "compact" | "comfortable";

export const TABLE_DENSITY_STORAGE_KEY = "patrolx.tableDensity";
export const DEFAULT_TABLE_DENSITY: TableDensity = "compact";

export const TABLE_DENSITY_LABELS: Record<TableDensity, string> = {
  compact: "紧凑",
  comfortable: "舒适",
};

const DENSITIES: readonly TableDensity[] = ["compact", "comfortable"];

function isDensity(value: unknown): value is TableDensity {
  return typeof value === "string" && (DENSITIES as readonly string[]).includes(value);
}

function safeStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

/** 读取本地偏好；非法值、读取失败或隐私模式静默回退默认紧凑（data-model §4）。 */
export function readTableDensity(storage: Storage | null = safeStorage()): TableDensity {
  if (!storage) return DEFAULT_TABLE_DENSITY;
  try {
    const raw = storage.getItem(TABLE_DENSITY_STORAGE_KEY);
    return isDensity(raw) ? raw : DEFAULT_TABLE_DENSITY;
  } catch {
    return DEFAULT_TABLE_DENSITY;
  }
}

/** 写入本地偏好；失败不抛错（配额 / 隐私模式）。 */
export function writeTableDensity(value: TableDensity, storage: Storage | null = safeStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(TABLE_DENSITY_STORAGE_KEY, value);
  } catch {
    // 偏好写入失败不影响当前会话的展示
  }
}

export interface TableDensityState {
  density: TableDensity;
  /** AntD Table size 映射：紧凑 = small，舒适 = middle。 */
  tableSize: "small" | "middle";
  setDensity: (value: TableDensity) => void;
}

export function useTableDensity(): TableDensityState {
  const [density, setDensityState] = useState<TableDensity>(() => readTableDensity());

  const setDensity = useCallback((value: TableDensity) => {
    setDensityState(value);
    writeTableDensity(value);
  }, []);

  return { density, tableSize: density === "compact" ? "small" : "middle", setDensity };
}
