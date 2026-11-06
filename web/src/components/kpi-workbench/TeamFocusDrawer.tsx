import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  api,
  type KpiCurrentHealthStatus,
  type KpiMetricResultV6,
  type KpiTeamFocusItemV6,
  type KpiTeamFocusPageV6,
  type KpiTeamFocusPatchRequestV6,
} from "../../api/http";

const CURRENT_STATUS_LABELS: Record<KpiCurrentHealthStatus, string> = {
  normal: "正常",
  warn: "预警",
  fail: "失败",
  pending_config: "待配置",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};

const AVAILABILITY_REASON_LABELS: Record<
  NonNullable<KpiTeamFocusItemV6["availability_reason"]>,
  string
> = {
  not_in_task_scope: "不在当前任务指标范围",
  measurement_unit_disabled: "所属测量单元已停用",
};

interface FocusRow {
  key: string;
  measurement_unit_id: string;
  measurement_unit_name: string;
  metric_resource_id: string;
  metric_name: string;
  availability: "available" | "unavailable";
  availability_reason: KpiTeamFocusItemV6["availability_reason"];
  metric: KpiMetricResultV6 | null;
}

function focusKey(measurementUnitId: string, metricResourceId: string): string {
  return `${measurementUnitId}\u0000${metricResourceId}`;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function conflictRevision(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.code !== "team_focus_revision_conflict") {
    return null;
  }
  if (!error.detail || typeof error.detail !== "object") return null;
  const value = (error.detail as { current_revision?: unknown }).current_revision;
  return typeof value === "number" ? value : null;
}

function sameSet(left: Set<string>, right: Set<string>): boolean {
  if (left.size !== right.size) return false;
  for (const item of left) {
    if (!right.has(item)) return false;
  }
  return true;
}

function buildRows(
  metrics: KpiMetricResultV6[],
  focusItems: KpiTeamFocusItemV6[],
): FocusRow[] {
  const rows: FocusRow[] = metrics.map((metric) => ({
    key: focusKey(metric.measurement_unit_id, metric.metric_resource_id),
    measurement_unit_id: metric.measurement_unit_id,
    measurement_unit_name: metric.measurement_unit_name,
    metric_resource_id: metric.metric_resource_id,
    metric_name: metric.metric_name,
    availability: metric.availability,
    availability_reason: metric.availability_reason ?? null,
    metric,
  }));
  const known = new Set(rows.map((row) => row.key));
  focusItems.forEach((item) => {
    const key = focusKey(item.measurement_unit_id, item.metric_resource_id);
    if (known.has(key)) return;
    rows.push({
      key,
      measurement_unit_id: item.measurement_unit_id,
      measurement_unit_name: item.measurement_unit_name,
      metric_resource_id: item.metric_resource_id,
      metric_name: item.metric_name,
      availability: item.availability,
      availability_reason: item.availability_reason ?? null,
      metric: null,
    });
  });
  return rows;
}

function formatMetricValue(metric: KpiMetricResultV6 | null): string {
  if (!metric) return "—";
  if (metric.today_value === null || metric.today_value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(metric.today_value);
}

function rowStatus(row: FocusRow): string {
  if (!row.metric) {
    return row.availability_reason
      ? AVAILABILITY_REASON_LABELS[row.availability_reason]
      : "当前不可用";
  }
  if (row.metric.current_status) return CURRENT_STATUS_LABELS[row.metric.current_status];
  return "无法判定";
}

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function trapTabKey(event: KeyboardEvent, root: HTMLElement): void {
  const focusable = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.getAttribute("aria-hidden") !== "true",
  );
  if (focusable.length === 0) {
    event.preventDefault();
    root.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault();
    first.focus();
  }
}

export interface TeamFocusDrawerProps {
  taskId: string;
  networkElementType: string;
  onClose: () => void;
  onSaved: () => void;
}

export function TeamFocusDrawer({
  taskId,
  networkElementType,
  onClose,
  onSaved,
}: TeamFocusDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const discardConfirmRef = useRef<HTMLDivElement>(null);
  const continueButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const discardRestoreFocusRef = useRef<HTMLElement | null>(null);
  const requestVersion = useRef(0);
  const [metrics, setMetrics] = useState<KpiMetricResultV6[]>([]);
  const [focusPage, setFocusPage] = useState<KpiTeamFocusPageV6 | null>(null);
  const [stagedFocusKeys, setStagedFocusKeys] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [measurementUnitId, setMeasurementUnitId] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [rebasing, setRebasing] = useState(false);
  const [patchError, setPatchError] = useState<string | null>(null);
  const [conflictCurrentRevision, setConflictCurrentRevision] = useState<number | null>(null);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    const requestId = ++requestVersion.current;
    setLoading(true);
    setLoadError(null);
    setPatchError(null);
    setConflictCurrentRevision(null);
    setDiscardConfirmOpen(false);
    setSearch("");
    setMeasurementUnitId("");
    setMetrics([]);
    setFocusPage(null);
    setStagedFocusKeys(new Set());
    try {
      const [metricPage, nextFocusPage] = await Promise.all([
        api.listKpiTaskMetricsV6(taskId, { view: "all", page: 1, page_size: 200 }),
        api.listKpiTeamFocusV6(networkElementType, {
          task_id: taskId,
          page: 1,
          page_size: 200,
        }),
      ]);
      if (requestId !== requestVersion.current) return;
      setMetrics(metricPage.items);
      setFocusPage(nextFocusPage);
      setStagedFocusKeys(
        new Set(
          nextFocusPage.items.map((item) =>
            focusKey(item.measurement_unit_id, item.metric_resource_id),
          ),
        ),
      );
    } catch (error) {
      if (requestId !== requestVersion.current) return;
      setLoadError(errorText(error, "团队关注加载失败，请稍后重试"));
    } finally {
      if (requestId === requestVersion.current) setLoading(false);
    }
  }, [networkElementType, taskId]);

  useEffect(() => {
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      restoreFocusRef.current?.focus();
    };
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestVersion.current += 1;
    };
  }, [load]);

  const initialFocusKeys = useMemo(
    () =>
      new Set(
        (focusPage?.items ?? []).map((item) =>
          focusKey(item.measurement_unit_id, item.metric_resource_id),
        ),
      ),
    [focusPage],
  );
  const rows = useMemo(
    () => buildRows(metrics, focusPage?.items ?? []),
    [focusPage, metrics],
  );
  const canWrite = focusPage?.can_write ?? false;
  const dirty = !sameSet(stagedFocusKeys, initialFocusKeys);
  const addedKeys = [...stagedFocusKeys].filter((key) => !initialFocusKeys.has(key));
  const removedKeys = [...initialFocusKeys].filter((key) => !stagedFocusKeys.has(key));

  const measurementUnits = useMemo(() => {
    const seen = new Map<string, string>();
    rows.forEach((row) => {
      if (!seen.has(row.measurement_unit_id)) {
        seen.set(row.measurement_unit_id, row.measurement_unit_name);
      }
    });
    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }, [rows]);

  const visibleRows = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("zh-CN");
    return rows.filter((row) => {
      if (measurementUnitId && row.measurement_unit_id !== measurementUnitId) return false;
      if (!term) return true;
      return [row.metric_name, row.metric_resource_id, row.measurement_unit_name, row.measurement_unit_id]
        .some((value) => value.toLocaleLowerCase("zh-CN").includes(term));
    });
  }, [measurementUnitId, rows, search]);

  const groupedRows = useMemo(() => {
    const groups = new Map<string, { id: string; name: string; rows: FocusRow[] }>();
    visibleRows.forEach((row) => {
      const group = groups.get(row.measurement_unit_id) ?? {
        id: row.measurement_unit_id,
        name: row.measurement_unit_name,
        rows: [],
      };
      group.rows.push(row);
      groups.set(row.measurement_unit_id, group);
    });
    return [...groups.values()];
  }, [visibleRows]);

  const requestClose = useCallback(() => {
    if (saving) return;
    if (dirty) {
      setDiscardConfirmOpen(true);
      return;
    }
    onClose();
  }, [dirty, onClose, saving]);

  useEffect(() => {
    if (discardConfirmOpen) {
      discardRestoreFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      continueButtonRef.current?.focus();
      return;
    }
    const previous = discardRestoreFocusRef.current;
    if (previous) {
      discardRestoreFocusRef.current = null;
      previous.focus();
    }
  }, [discardConfirmOpen]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (discardConfirmOpen) setDiscardConfirmOpen(false);
        else requestClose();
        return;
      }
      if (event.key !== "Tab") return;
      const root = discardConfirmOpen ? discardConfirmRef.current : drawerRef.current;
      if (root) trapTabKey(event, root);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [discardConfirmOpen, requestClose]);

  const toggleFocus = (row: FocusRow) => {
    if (!canWrite) return;
    setPatchError(null);
    setConflictCurrentRevision(null);
    setStagedFocusKeys((current) => {
      const next = new Set(current);
      if (next.has(row.key)) next.delete(row.key);
      else if (row.availability === "available" || initialFocusKeys.has(row.key)) next.add(row.key);
      return next;
    });
  };

  const selectVisible = () => {
    if (!canWrite) return;
    setPatchError(null);
    setConflictCurrentRevision(null);
    setStagedFocusKeys((current) => {
      const next = new Set(current);
      visibleRows.forEach((row) => {
        if (row.availability === "available") next.add(row.key);
      });
      return next;
    });
  };

  const removeVisible = () => {
    if (!canWrite) return;
    setPatchError(null);
    setConflictCurrentRevision(null);
    setStagedFocusKeys((current) => {
      const next = new Set(current);
      visibleRows.forEach((row) => next.delete(row.key));
      return next;
    });
  };

  const identityFor = (key: string) => {
    const row = rows.find((candidate) => candidate.key === key);
    if (!row) throw new Error(`未找到关注指标：${key}`);
    return {
      measurement_unit_id: row.measurement_unit_id,
      metric_resource_id: row.metric_resource_id,
    };
  };

  const save = async () => {
    if (!focusPage || !canWrite || !dirty) return;
    const payload: KpiTeamFocusPatchRequestV6 = {
      task_id: taskId,
      expected_revision: focusPage.revision,
      add: addedKeys.map(identityFor),
      remove: removedKeys.map(identityFor),
    };
    setSaving(true);
    setPatchError(null);
    setConflictCurrentRevision(null);
    try {
      await api.patchKpiTeamFocusV6(networkElementType, payload);
      onSaved();
      onClose();
    } catch (error) {
      setPatchError(errorText(error, "团队关注保存失败，请稍后重试"));
      setConflictCurrentRevision(conflictRevision(error));
    } finally {
      setSaving(false);
    }
  };

  const rebaseLatest = async () => {
    if (!focusPage || !canWrite || rebasing) return;
    const baselineKeys = new Set(initialFocusKeys);
    const localKeys = new Set(stagedFocusKeys);
    const locallyAdded = new Set(
      [...localKeys].filter((key) => !baselineKeys.has(key)),
    );
    const locallyRemoved = new Set(
      [...baselineKeys].filter((key) => !localKeys.has(key)),
    );
    const requestId = ++requestVersion.current;
    setRebasing(true);
    setPatchError(null);
    try {
      const latestFocusPage = await api.listKpiTeamFocusV6(networkElementType, {
        task_id: taskId,
        page: 1,
        page_size: 200,
      });
      if (requestId !== requestVersion.current) return;
      const latestKeys = new Set(
        latestFocusPage.items.map((item) =>
          focusKey(item.measurement_unit_id, item.metric_resource_id),
        ),
      );
      locallyAdded.forEach((key) => latestKeys.add(key));
      locallyRemoved.forEach((key) => latestKeys.delete(key));
      setFocusPage(latestFocusPage);
      setStagedFocusKeys(latestKeys);
      setConflictCurrentRevision(null);
    } catch (error) {
      if (requestId !== requestVersion.current) return;
      setPatchError(errorText(error, "最新团队关注加载失败，请稍后重试"));
    } finally {
      if (requestId === requestVersion.current) setRebasing(false);
    }
  };

  return (
    <div
      className="kpi-focus-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <div
        ref={drawerRef}
        className="kpi-focus-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="管理团队关注"
      >
        <header className="kpi-focus-header">
          <div>
            <div className="kpi-focus-title-row">
              <h2>团队关注</h2>
              <span className="kpi-focus-shared-tag">{networkElementType} 内共享</span>
              {focusPage ? <span className="kpi-focus-count-tag">{focusPage.total} 项</span> : null}
            </div>
            <p>
              同一 <strong>{networkElementType} 网元类型</strong>下的维护人员共享此配置；
              其他网元类型独立维护，不读取或覆盖本列表。
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="kpi-focus-close"
            aria-label="关闭团队关注"
            onClick={requestClose}
          >
            关闭
          </button>
        </header>

        <div className="kpi-focus-content">
          {loading ? (
            <div className="kpi-focus-loading" role="status">
              <span className="kpi-workbench-loading-bar" aria-hidden="true" />
              正在读取全部指标与团队关注…
            </div>
          ) : loadError ? (
            <div className="kpi-focus-load-error" role="alert">
              <h3>团队关注加载失败</h3>
              <p>{loadError}</p>
              <button type="button" className="kpi-workbench-button" onClick={() => void load()}>
                重试
              </button>
            </div>
          ) : (
            <>
              <div className="kpi-focus-notice">
                <strong>关注只决定默认查看范围。</strong>
                不改变巡检执行、任务结果、报告内容或历史结果；未关注指标仍保留在“全部指标”。
              </div>

              {!canWrite ? (
                <div className="kpi-focus-readonly" role="status">
                  <strong>你当前为只读访问</strong>
                  可以查看共享关注，但不能修改或保存。
                </div>
              ) : null}

              <div className="kpi-focus-filters">
                <label>
                  <span>搜索</span>
                  <input
                    type="search"
                    aria-label="搜索指标名称、指标 ID 或测量单元"
                    placeholder="搜索指标名称、指标 ID 或测量单元"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <label>
                  <span>测量单元</span>
                  <select
                    aria-label="按测量单元筛选"
                    value={measurementUnitId}
                    onChange={(event) => setMeasurementUnitId(event.target.value)}
                  >
                    <option value="">全部测量单元</option>
                    {measurementUnits.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {unit.name} · {unit.id}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="kpi-focus-toolbar">
                <span>
                  <strong>{visibleRows.length}</strong> 项当前结果
                  <span aria-hidden="true"> · </span>
                  已关注 <strong>{stagedFocusKeys.size}</strong> 项
                </span>
                <div>
                  <button
                    type="button"
                    className="kpi-workbench-button"
                    disabled={!canWrite || !visibleRows.some((row) =>
                      row.availability === "available" && !stagedFocusKeys.has(row.key),
                    )}
                    onClick={selectVisible}
                  >
                    全选当前结果
                  </button>
                  <button
                    type="button"
                    className="kpi-workbench-button"
                    disabled={!canWrite || !visibleRows.some((row) => stagedFocusKeys.has(row.key))}
                    onClick={removeVisible}
                  >
                    移出当前结果
                  </button>
                </div>
              </div>

              {patchError ? (
                <div className="kpi-focus-save-error" role="alert">
                  <strong>团队关注保存失败</strong>
                  <p>{patchError}</p>
                  {conflictCurrentRevision !== null ? (
                    <>
                      <p>当前共享版本 {conflictCurrentRevision}，你的暂存选择已保留。</p>
                      <button
                        type="button"
                        className="kpi-workbench-button"
                        disabled={rebasing}
                        onClick={() => void rebaseLatest()}
                      >
                        {rebasing ? "正在载入最新版本…" : "载入最新版本并保留修改"}
                      </button>
                    </>
                  ) : null}
                </div>
              ) : null}

              <div className="kpi-focus-catalog">
                {groupedRows.length ? (
                  groupedRows.map((group) => (
                    <section key={group.id} className="kpi-focus-unit-group" aria-labelledby={`kpi-focus-unit-${group.id}`}>
                      <header>
                        <div>
                          <h3 id={`kpi-focus-unit-${group.id}`}>{group.name}</h3>
                          <code>{group.id}</code>
                        </div>
                        <span>
                          {group.rows.filter((row) => stagedFocusKeys.has(row.key)).length} / {group.rows.length} 已关注
                        </span>
                      </header>
                      <div className="kpi-focus-rows">
                        {group.rows.map((row) => {
                          const checked = stagedFocusKeys.has(row.key);
                          return (
                            <label
                              key={row.key}
                              className={`kpi-focus-row${checked ? " is-focused" : ""}${row.availability === "unavailable" ? " is-unavailable" : ""}`}
                              data-testid="team-focus-metric-row"
                              data-metric-key={row.key}
                            >
                              <input
                                type="checkbox"
                                aria-label={`关注${row.metric_name}`}
                                checked={checked}
                                disabled={!canWrite}
                                onChange={() => toggleFocus(row)}
                              />
                              <span className="kpi-focus-metric-copy">
                                <strong>{row.metric_name}</strong>
                                <code>{row.metric_resource_id}</code>
                              </span>
                              <span className={`kpi-focus-status${row.metric?.current_status ? ` is-${row.metric.current_status}` : " is-unavailable"}`}>
                                {rowStatus(row)}
                              </span>
                              <span className="kpi-focus-value">{formatMetricValue(row.metric)}</span>
                            </label>
                          );
                        })}
                      </div>
                    </section>
                  ))
                ) : (
                  <div className="kpi-focus-empty" role="status">
                    <strong>没有符合当前条件的指标</strong>
                    <span>清除搜索或测量单元筛选后重试。</span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <footer className="kpi-focus-footer">
          <span className={dirty ? "is-dirty" : undefined}>
            {dirty
              ? `${addedKeys.length} 项待加入 · ${removedKeys.length} 项待移出`
              : "暂无未保存修改"}
          </span>
          {canWrite ? (
            <button
              type="button"
              className="kpi-workbench-button is-primary"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              {saving ? "正在保存…" : "保存团队关注"}
            </button>
          ) : null}
        </footer>
      </div>

      {discardConfirmOpen ? (
        <div className="kpi-focus-confirm-overlay" role="presentation">
          <div
            ref={discardConfirmRef}
            className="kpi-focus-confirm"
            role="alertdialog"
            aria-modal="true"
            aria-label="放弃未保存的修改？"
            tabIndex={-1}
          >
            <h3>放弃未保存的修改？</h3>
            <p>关闭后，本次加入或移出不会保存。</p>
            <div>
              <button
                ref={continueButtonRef}
                type="button"
                className="kpi-workbench-button"
                onClick={() => setDiscardConfirmOpen(false)}
              >
                继续编辑
              </button>
              <button type="button" className="kpi-workbench-button is-primary" onClick={onClose}>
                放弃修改
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
