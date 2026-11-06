import { useCallback, useEffect, useRef, useState } from "react";

import {
  api,
  type KpiCurrentHealthStatus,
  type KpiDailyBucketV6,
  type KpiMetricEvidenceV6,
  type KpiMetricResultV6,
  type KpiTechnicalAnalysisV6,
  type KpiTrendHealthStatus,
} from "../../api/http";

const CURRENT_STATUS_LABELS: Record<KpiCurrentHealthStatus, string> = {
  normal: "正常",
  warn: "预警",
  fail: "失败",
  pending_config: "待配置",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};

const TREND_LABELS: Record<KpiTrendHealthStatus, string> = {
  improved: "改善",
  stable: "稳定",
  worsened: "恶化",
  observe: "关注",
  no_baseline: "无基线",
};

const BUCKET_STATUS_LABELS: Record<KpiDailyBucketV6["status"], string> = {
  ok: "有效",
  no_data: "无数据",
  zero_denominator: "分母为零",
  unreadable: "不可读",
  no_baseline: "无基线",
};

const AGGREGATION_LABELS: Record<KpiMetricEvidenceV6["metric"]["daily_aggregation"], string> = {
  latest: "取最新值",
  mean: "按有效点求均值",
  sum: "按有效点求和",
  max: "取最大值",
  min: "取最小值",
};

const DIRECTION_LABELS: Record<KpiMetricEvidenceV6["current_threshold"]["direction"], string> = {
  higher_better: "越高越好",
  lower_better: "越低越好",
  neutral: "中性",
};

const THRESHOLD_SOURCE_LABELS: Record<KpiMetricEvidenceV6["current_threshold"]["source"], string> = {
  custom: "维护配置",
  default: "系统默认",
  legacy_resource: "历史指标口径",
  missing: "未配置",
};

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 }).format(value);
}

function formatValue(value: number | null | undefined, percentage = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${formatNumber(value)}${percentage ? "%" : ""}`;
}

function formatChange(evidence: KpiMetricEvidenceV6): string {
  if (evidence.change_value === null || evidence.change_value === undefined) return "—";
  if (evidence.change_unit === "pp") return `${formatNumber(evidence.change_value)}pp`;
  if (evidence.change_unit === "relative") return `${formatNumber(evidence.change_value)}%`;
  if (evidence.change_unit === "absolute") return formatNumber(evidence.change_value);
  return "—";
}

function thresholdText(
  threshold: KpiMetricEvidenceV6["current_threshold"],
  percentage: boolean,
): string {
  const critical = formatValue(threshold.critical_threshold, percentage);
  const warning = formatValue(threshold.warning_threshold, percentage);
  if (critical === "—" && warning === "—") return "未配置阈值";
  const relation =
    threshold.direction === "higher_better" ? "不低于" : threshold.direction === "lower_better" ? "不高于" : "参考";
  const configured = critical !== "—" ? critical : warning;
  return `${relation} ${configured} · 来源：${THRESHOLD_SOURCE_LABELS[threshold.source]}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "证据读取失败，请稍后重试";
}

function BucketValue({ bucket, percentage }: { bucket: KpiDailyBucketV6 | null | undefined; percentage: boolean }) {
  if (!bucket) return <span className="kpi-evidence-muted">无记录</span>;
  return (
    <span className="kpi-evidence-bucket-value">
      <strong>{formatValue(bucket.value, percentage)}</strong>
      <span>{BUCKET_STATUS_LABELS[bucket.status]}</span>
    </span>
  );
}

export interface KpiEvidenceDrawerProps {
  metric: KpiMetricResultV6;
  onClose: () => void;
}

const INLINE_EVIDENCE_QUERY = "(min-width: 1440px)";

function useInlineEvidenceLayout(): boolean {
  const [inline, setInline] = useState(
    () => typeof window !== "undefined" && window.matchMedia(INLINE_EVIDENCE_QUERY).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(INLINE_EVIDENCE_QUERY);
    const handleChange = (event: MediaQueryListEvent) => setInline(event.matches);
    setInline(media.matches);
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  return inline;
}

export function KpiEvidenceDrawer({ metric, onClose }: KpiEvidenceDrawerProps) {
  const inline = useInlineEvidenceLayout();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const requestVersion = useRef(0);
  const [evidence, setEvidence] = useState<KpiMetricEvidenceV6 | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [technical, setTechnical] = useState<KpiTechnicalAnalysisV6 | null>(null);
  const [technicalLoading, setTechnicalLoading] = useState(false);
  const [technicalError, setTechnicalError] = useState<string | null>(null);

  const loadEvidence = useCallback(() => {
    const version = ++requestVersion.current;
    setLoading(true);
    setLoadError(null);
    api
      .getKpiMetricEvidenceV6(
        metric.task_id,
        metric.measurement_unit_id,
        metric.metric_resource_id,
      )
      .then((nextEvidence) => {
        if (version !== requestVersion.current) return;
        setEvidence(nextEvidence);
      })
      .catch((error: unknown) => {
        if (version !== requestVersion.current) return;
        setEvidence(null);
        setLoadError(errorMessage(error));
      })
      .finally(() => {
        if (version === requestVersion.current) setLoading(false);
      });
  }, [metric.measurement_unit_id, metric.metric_resource_id, metric.task_id]);

  const loadTechnical = useCallback(() => {
    setTechnicalLoading(true);
    setTechnicalError(null);
    api
      .getKpiMetricTechnicalAnalysisV6(
        metric.task_id,
        metric.measurement_unit_id,
        metric.metric_resource_id,
      )
      .then(setTechnical)
      .catch((error: unknown) => setTechnicalError(errorMessage(error)))
      .finally(() => setTechnicalLoading(false));
  }, [metric.measurement_unit_id, metric.metric_resource_id, metric.task_id]);

  useEffect(() => {
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
      restoreFocusRef.current?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    loadEvidence();
    return () => {
      requestVersion.current += 1;
    };
  }, [loadEvidence]);

  const toggleTechnical = () => {
    const nextOpen = !technicalOpen;
    setTechnicalOpen(nextOpen);
    if (nextOpen && !technical && !technicalLoading) loadTechnical();
  };

  const isDerived = evidence?.metric.role === "derived";
  const percentage = evidence?.metric.is_percentage ?? false;
  const reasonCodes = evidence?.reason_codes ?? [];
  const components = evidence?.components ?? [];

  return (
    <div
      className={`kpi-evidence-overlay ${inline ? "is-inline" : "is-overlay"}`}
      data-testid="kpi-evidence-overlay"
      data-layout={inline ? "inline" : "overlay"}
      role="presentation"
      onMouseDown={(event) => {
        if (!inline && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={drawerRef}
        className="kpi-evidence-drawer"
        role={inline ? "region" : "dialog"}
        aria-modal={inline ? undefined : true}
        aria-label={`${metric.metric_name}证据`}
      >
        <header className="kpi-evidence-header">
          <div>
            <span className="kpi-evidence-eyebrow">
              {metric.measurement_unit_name} · <code>{metric.metric_resource_id}</code>
            </span>
            <h2>{metric.metric_name}</h2>
            <p>单指标证据</p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="kpi-evidence-close"
            aria-label="关闭指标证据"
            onClick={onClose}
          >
            关闭
          </button>
        </header>

        <div className="kpi-evidence-content">
          {loading ? (
            <div className="kpi-evidence-loading" role="status">
              <span className="kpi-workbench-loading-bar" aria-hidden="true" />
              正在读取指标证据…
            </div>
          ) : loadError ? (
            <div className="kpi-evidence-error" role="alert">
              <strong>指标证据加载失败</strong>
              <p>{loadError}</p>
              <button type="button" className="kpi-workbench-button" onClick={loadEvidence}>
                重试加载证据
              </button>
            </div>
          ) : evidence ? (
            <>
              <section className="kpi-evidence-section" aria-labelledby="kpi-evidence-result-heading">
                <div className="kpi-evidence-section-title">
                  <div>
                    <h3 id="kpi-evidence-result-heading">当前结论与证据</h3>
                    <p>{evidence.reason || "服务端未提供判定原因。"}</p>
                  </div>
                  <span className={`kpi-evidence-role is-${evidence.metric.role}`}>
                    {evidence.metric.role === "base" ? "源包直出 · base" : "PatrolX 计算 · derived"}
                  </span>
                </div>

                <dl className="kpi-evidence-highlights">
                  <div>
                    <dt>当前判定</dt>
                    <dd>{CURRENT_STATUS_LABELS[evidence.metric.current_status]}</dd>
                  </div>
                  <div>
                    <dt>昨日趋势</dt>
                    <dd>{TREND_LABELS[evidence.metric.trend_status]}</dd>
                  </div>
                  <div>
                    <dt>今日</dt>
                    <dd><BucketValue bucket={evidence.current} percentage={percentage} /></dd>
                  </div>
                  <div>
                    <dt>昨日</dt>
                    <dd><BucketValue bucket={evidence.previous} percentage={percentage} /></dd>
                  </div>
                  <div>
                    <dt>变化</dt>
                    <dd className="kpi-evidence-numeric">{formatChange(evidence)}</dd>
                  </div>
                  <div>
                    <dt>有效点数</dt>
                    <dd className="kpi-evidence-numeric">{evidence.valid_count ?? evidence.current.valid_count}</dd>
                  </div>
                </dl>

                <dl className="kpi-evidence-facts">
                  <div>
                    <dt>判定方向</dt>
                    <dd>{DIRECTION_LABELS[evidence.current_threshold.direction]}</dd>
                  </div>
                  <div>
                    <dt>当前阈值</dt>
                    <dd>{thresholdText(evidence.current_threshold, percentage)}</dd>
                  </div>
                  <div>
                    <dt>日聚合方式</dt>
                    <dd>{AGGREGATION_LABELS[evidence.metric.daily_aggregation]}</dd>
                  </div>
                  <div>
                    <dt>判定原因码</dt>
                    <dd>{reasonCodes.length ? reasonCodes.join("、") : "—"}</dd>
                  </div>
                </dl>

                {isDerived ? (
                  <div className="kpi-evidence-derived">
                    <dl className="kpi-evidence-facts">
                      <div>
                        <dt>计算公式</dt>
                        <dd><code>{evidence.metric.formula || "未配置"}</code></dd>
                      </div>
                      <div>
                        <dt>分子</dt>
                        <dd>{formatValue(evidence.current.numerator)}</dd>
                      </div>
                      <div>
                        <dt>分母</dt>
                        <dd>{formatValue(evidence.current.denominator)}</dd>
                      </div>
                    </dl>
                    <h4>计算组件</h4>
                    {components.length ? (
                      <ul className="kpi-evidence-components">
                        {components.map((component) => (
                          <li key={`${component.role}-${component.metric_resource_id}`}>
                            <span>{component.name}</span>
                            <code>{component.metric_resource_id}</code>
                            <strong>{formatValue(component.value)}</strong>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="kpi-evidence-empty">未提供计算组件。</p>
                    )}
                  </div>
                ) : null}
              </section>

              <section className="kpi-evidence-section" aria-labelledby="kpi-evidence-source-heading">
                <div className="kpi-evidence-section-title">
                  <div>
                    <h3 id="kpi-evidence-source-heading">来源与源列名</h3>
                    <p>按本任务冻结的指标口径展示，不从相邻指标回填或重算。</p>
                  </div>
                </div>
                <ul className="kpi-evidence-sources">
                  {evidence.sources.map((source) => (
                    <li key={`${source.file}-${source.record_group ?? ""}`}>
                      <strong>{source.file}</strong>
                      {source.record_group ? <span>记录组：{source.record_group}</span> : null}
                      <ul>
                        {source.raw_source_names.map((name) => (
                          <li key={name}><code>{name}</code></li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="kpi-evidence-section" aria-labelledby="kpi-evidence-trend-heading">
                <div className="kpi-evidence-section-title">
                  <div>
                    <h3 id="kpi-evidence-trend-heading">7 日趋势</h3>
                    <p>仅展示已发布日结果，不使用分钟级结果均值替代。</p>
                  </div>
                </div>
                {evidence.seven_day_trend.length ? (
                  <div className="kpi-evidence-table-wrap">
                    <table className="kpi-evidence-table">
                      <thead>
                        <tr><th>日期</th><th>值</th><th>有效点</th><th>状态</th></tr>
                      </thead>
                      <tbody>
                        {evidence.seven_day_trend.map((bucket) => (
                          <tr key={`seven-day-${bucket.date}`}>
                            <td>{bucket.date}</td>
                            <td>{formatValue(bucket.value, percentage)}</td>
                            <td>{bucket.valid_count}</td>
                            <td>{BUCKET_STATUS_LABELS[bucket.status]}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="kpi-evidence-empty">暂无 7 日趋势。</p>
                )}
              </section>

              <section className="kpi-evidence-section" aria-labelledby="kpi-evidence-group-heading">
                <div className="kpi-evidence-section-title">
                  <div>
                    <h3 id="kpi-evidence-group-heading">对象与周期分组</h3>
                    <p>每行保留对象、周期、状态、原因与来源文件。</p>
                  </div>
                </div>
                {evidence.groups.length ? (
                  <div className="kpi-evidence-table-wrap">
                    <table className="kpi-evidence-table is-groups">
                      <thead>
                        <tr><th>对象 / 周期</th><th>今日</th><th>昨日</th><th>判定</th><th>原因 / 来源</th></tr>
                      </thead>
                      <tbody>
                        {evidence.groups.map((group) => (
                          <tr key={`${group.object_key}-${group.period_minutes ?? "unknown"}`}>
                            <td>
                              <strong>{group.object_key}</strong>
                              <span>{group.period_minutes === null ? "周期未知" : `${group.period_minutes} 分钟`}</span>
                            </td>
                            <td><BucketValue bucket={group.today} percentage={percentage} /></td>
                            <td><BucketValue bucket={group.yesterday} percentage={percentage} /></td>
                            <td>
                              <span>{CURRENT_STATUS_LABELS[group.current_status]}</span>
                              <span>趋势：{TREND_LABELS[group.trend_status]}</span>
                            </td>
                            <td>
                              <span>{group.reason || "—"}</span>
                              <span>{group.source_files.join("、") || "—"}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="kpi-evidence-empty">暂无对象与周期证据。</p>
                )}
              </section>

              <section className="kpi-evidence-section is-technical" aria-labelledby="kpi-evidence-technical-heading">
                <button
                  type="button"
                  className="kpi-evidence-technical-toggle"
                  aria-label={technicalOpen ? "收起技术分析" : "展开技术分析"}
                  aria-expanded={technicalOpen}
                  aria-controls="kpi-evidence-technical-content"
                  onClick={toggleTechnical}
                >
                  <span>
                    <strong id="kpi-evidence-technical-heading">技术分析</strong>
                    <small>跨任务历史与同设备版本对比按需读取</small>
                  </span>
                  <span aria-hidden="true">{technicalOpen ? "收起" : "展开技术分析"}</span>
                </button>
                {technicalOpen ? (
                  <div id="kpi-evidence-technical-content" className="kpi-evidence-technical-content">
                    {technicalLoading ? (
                      <div className="kpi-evidence-loading" role="status">正在读取技术分析…</div>
                    ) : technicalError ? (
                      <div className="kpi-evidence-error" role="alert">
                        <p>{technicalError}</p>
                        <button type="button" className="kpi-workbench-button" onClick={loadTechnical}>
                          重试加载技术分析
                        </button>
                      </div>
                    ) : technical ? (
                      <div data-testid="kpi-technical-analysis">
                        <div className="kpi-evidence-subheading">
                          <h4>跨任务历史</h4>
                          <span>{technical.cross_task_history.length} 条</span>
                        </div>
                        {technical.cross_task_history.length ? (
                          <div className="kpi-evidence-table-wrap">
                            <table className="kpi-evidence-table">
                              <thead>
                                <tr><th>任务</th><th>日期</th><th>值</th><th>状态</th></tr>
                              </thead>
                              <tbody>
                                {technical.cross_task_history.map((point) => (
                                  <tr key={`${point.task_id}-${point.data_date}`}>
                                    <td><code>{point.task_id}</code></td>
                                    <td>{point.data_date}</td>
                                    <td>{formatValue(point.value, percentage)}</td>
                                    <td>{point.status}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="kpi-evidence-empty">暂无同设备跨任务历史。</p>
                        )}

                        <div className="kpi-evidence-subheading">
                          <h4>同设备版本对比</h4>
                          <span>{technical.version_comparisons.length} 条</span>
                        </div>
                        {technical.version_comparisons.length ? (
                          <div className="kpi-evidence-table-wrap">
                            <table className="kpi-evidence-table">
                              <thead>
                                <tr><th>版本</th><th>日期</th><th>当前值</th><th>对比值</th><th>变化</th></tr>
                              </thead>
                              <tbody>
                                {technical.version_comparisons.map((comparison) => (
                                  <tr key={`${comparison.task_id}-${comparison.version}`}>
                                    <td>{comparison.version}</td>
                                    <td>{comparison.data_date}</td>
                                    <td>{formatValue(comparison.current_value, percentage)}</td>
                                    <td>{formatValue(comparison.comparison_value, percentage)}</td>
                                    <td>{formatValue(comparison.change_value)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="kpi-evidence-empty">暂无可比版本。</p>
                        )}
                      </div>
                    ) : (
                      <p className="kpi-evidence-empty">暂无技术分析。</p>
                    )}
                  </div>
                ) : null}
              </section>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
