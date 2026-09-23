import { Alert, Button, Descriptions, Empty, Modal, Select, Spin, Tabs, Typography } from "antd";
import type { ECharts } from "echarts/core";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  MeasurementHistoryTrend,
  MeasurementMetadataMetric,
  MeasurementTrendPoint,
  MeasurementVersionCandidateList,
  MeasurementVersionComparison,
} from "../api/http";
import { api } from "../api/http";
import echarts from "../lib/echarts";
import {
  analyzeTrendComparison,
  buildDailyTrendChartOption,
  buildTrendChartOption,
  type TrendComparison,
} from "../utils/measurementTrend";
import {
  buildVersionCompareChartOption,
  formatVersionDateTime,
  versionCandidateLabel,
  versionCandidateOption,
  versionSummaryMessage,
} from "../utils/measurementVersionCompare";
import {
  buildHistoryTrendChartOption,
  buildTrendSelectionOptions,
  defaultTrendSelection,
  historyMatchAlert,
  type TrendSelection,
} from "../utils/measurementHistory";

function MetricDisplayName(metric: { metric_resource_id: string; metric_resource_name_zh?: string | null; base_source_name?: string }) {
  return metric.metric_resource_name_zh || metric.base_source_name || metric.metric_resource_id;
}

function MiniTrend({ points }: { points: MeasurementTrendPoint[] }) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 96;
      const y = 28 - ((point.value - min) / range) * 24;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg width="104" height="32" role="img" aria-label="任务内迷你趋势">
      <path d={path} fill="none" stroke="#1677ff" strokeWidth={2} />
    </svg>
  );
}

function formatValue(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${value}${unit ? ` ${unit}` : ""}`;
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function TrendComparisonSummary({ comparison, unit }: { comparison: TrendComparison; unit?: string | null }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <Alert
        type={comparison.mode === "insufficient" ? "warning" : "info"}
        showIcon
        message={comparison.message}
      />
      {comparison.mode !== "insufficient" && (
        <Descriptions size="small" column={4} style={{ marginTop: 8 }}>
          <Descriptions.Item label="最新值">{formatValue(comparison.latestValue, unit)}</Descriptions.Item>
          <Descriptions.Item label="基线值">{formatValue(comparison.baselineValue, unit)}</Descriptions.Item>
          <Descriptions.Item label="偏差">{formatValue(comparison.deviation, unit)}</Descriptions.Item>
          <Descriptions.Item label="偏差比例">{formatPercent(comparison.deviationRatio)}</Descriptions.Item>
        </Descriptions>
      )}
    </div>
  );
}

function DailyTrendChart({
  metricName,
  points,
  unit,
}: {
  metricName: string;
  points: MeasurementTrendPoint[];
  unit?: string | null;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const option = buildDailyTrendChartOption(points, metricName, unit);

  useEffect(() => {
    const element = chartRef.current;
    if (!element || !option) return;

    const chart: ECharts = echarts.init(element);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [metricName, option, points, unit]);

  if (!option) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 8, fontWeight: 600 }}>按日对齐对比</div>
      <div ref={chartRef} style={{ height: 360 }} />
    </div>
  );
}

function TrendChart({ metricName, points, unit }: { metricName: string; points: MeasurementTrendPoint[]; unit?: string | null }) {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = chartRef.current;
    const option = buildTrendChartOption(points, metricName, unit);
    if (!element || !option) return;

    const chart = echarts.init(element);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [metricName, points, unit]);

  if (points.length < 2) {
    return <Empty description="趋势点不足" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return <div ref={chartRef} style={{ height: 380 }} />;
}

function HistoryTrendChart({
  history,
  unit,
}: {
  history: MeasurementHistoryTrend;
  unit?: string | null;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const option = useMemo(() => buildHistoryTrendChartOption(history, unit), [history, unit]);

  useEffect(() => {
    const element = chartRef.current;
    if (!element || !option) return;

    const chart = echarts.init(element);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);

  if (!option) return <Empty description="历史趋势点不足" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  return <div ref={chartRef} style={{ height: 380 }} />;
}

function VersionCompareChart({
  comparison,
  unit,
}: {
  comparison: MeasurementVersionComparison;
  unit?: string | null;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const option = useMemo(() => buildVersionCompareChartOption(comparison, unit), [comparison, unit]);

  useEffect(() => {
    const element = chartRef.current;
    if (!element || !option) return;
    const chart = echarts.init(element);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);

  if (!option) return <Empty description="版本对比点不足" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  return <div ref={chartRef} style={{ height: 380 }} />;
}

function VersionComparePanel({
  metric,
  taskId,
  ruleCode,
  unitId,
  unit,
}: {
  metric: MetricTrendCellMetric;
  taskId?: string;
  ruleCode?: string;
  unitId?: string;
  unit?: string | null;
}) {
  const trends = metric.trends ?? [];
  const options = useMemo(() => buildTrendSelectionOptions(trends), [trends]);
  const [selection, setSelection] = useState<TrendSelection>(() => defaultTrendSelection(trends));
  const [candidates, setCandidates] = useState<MeasurementVersionCandidateList | null>(null);
  const [baselineTaskId, setBaselineTaskId] = useState<string | null>(null);
  const [comparison, setComparison] = useState<MeasurementVersionComparison | null>(null);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!taskId || !ruleCode || !unitId) return;
    const seq = ++requestSeq.current;
    setLoadingCandidates(true);
    setError(null);
    setCandidates(null);
    setBaselineTaskId(null);
    setComparison(null);
    const periodMinutes = selection.periodKey === "none" ? null : Number(selection.periodKey);
    api
      .getMeasurementVersionCandidates(taskId, ruleCode, unitId, metric.metric_resource_id, {
        object_key: selection.objectKey,
        period_minutes: Number.isFinite(periodMinutes) ? periodMinutes : null,
      })
      .then((data) => {
        if (seq === requestSeq.current) setCandidates(data);
      })
      .catch((cause: unknown) => {
        if (seq !== requestSeq.current) return;
        setError(cause instanceof Error ? cause.message : "版本候选加载失败");
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoadingCandidates(false);
      });
  }, [metric.metric_resource_id, reloadNonce, ruleCode, selection.objectKey, selection.periodKey, taskId, unitId]);

  useEffect(() => {
    if (!taskId || !ruleCode || !unitId || !baselineTaskId) return;
    const seq = ++requestSeq.current;
    setLoadingComparison(true);
    setError(null);
    setComparison(null);
    const periodMinutes = selection.periodKey === "none" ? null : Number(selection.periodKey);
    api
      .getMeasurementVersionCompare(taskId, ruleCode, unitId, metric.metric_resource_id, {
        baseline_task_id: baselineTaskId,
        object_key: selection.objectKey,
        period_minutes: Number.isFinite(periodMinutes) ? periodMinutes : null,
      })
      .then((data) => {
        if (seq === requestSeq.current) setComparison(data);
      })
      .catch((cause: unknown) => {
        if (seq !== requestSeq.current) return;
        setError(cause instanceof Error ? cause.message : "版本对比加载失败");
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoadingComparison(false);
      });
  }, [baselineTaskId, metric.metric_resource_id, ruleCode, selection.objectKey, selection.periodKey, taskId, unitId]);

  useEffect(() => {
    if (!options.objectOptions.length || !options.periodOptions.length) return;
    const objectAvailable = options.objectOptions.some((option) => option.value === selection.objectKey);
    const periodAvailable = options.periodOptions.some((option) => option.value === selection.periodKey);
    if (objectAvailable && periodAvailable) return;
    setSelection(defaultTrendSelection(metric.trends));
  }, [metric.trends, options.objectOptions, options.periodOptions, selection.objectKey, selection.periodKey]);

  const canRequest = Boolean(taskId && ruleCode && unitId);
  const candidateOptions = useMemo(
    () => (candidates ? candidates.items.map((item) => versionCandidateOption(item, candidates.current_version)) : []),
    [candidates],
  );
  const loading = loadingCandidates || loadingComparison;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <Select
          aria-label="版本对比行对象"
          options={options.objectOptions}
          style={{ width: 180 }}
          value={selection.objectKey}
          onChange={(value) => setSelection((current) => ({ ...current, objectKey: value }))}
        />
        <Select
          aria-label="版本对比周期"
          options={options.periodOptions}
          style={{ width: 150 }}
          value={selection.periodKey}
          onChange={(value) => setSelection((current) => ({ ...current, periodKey: value }))}
        />
        <Select
          aria-label="基线版本"
          allowClear
          placeholder="选择基线版本"
          style={{ width: 260 }}
          options={candidateOptions}
          value={baselineTaskId}
          onChange={(value) => setBaselineTaskId(value ?? null)}
        />
        <Typography.Text type="secondary">设备 {candidates?.device_id || "未填写"}</Typography.Text>
      </div>

      {!canRequest ? (
        <Alert type="info" showIcon message="版本对比不可用" description="缺少任务或规则上下文，无法请求版本对比。" />
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message="版本对比加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => setReloadNonce((value) => value + 1)}>
              重试
            </Button>
          }
        />
      ) : loading ? (
        <div style={{ padding: 48, textAlign: "center" }}>
          <Spin />
        </div>
      ) : candidates && !candidates.items.length ? (
        <Alert
          type={candidates.device_id ? "info" : "warning"}
          showIcon
          message="暂无版本候选"
          description={
            candidates.device_id
              ? "没有同设备的其他已完成任务。"
              : "当前任务设备 ID 缺失，无法匹配同设备版本候选。"
          }
        />
      ) : comparison ? (
        <>
          <Alert
            type={comparison.match.status === "matched" ? "info" : "warning"}
            showIcon
            message={comparison.match.status === "matched" ? "版本对比完成" : "版本对比降级"}
            description={
              comparison.match.message ||
              (comparison.match.status === "matched" ? "已按同设备任务对比当前指标。" : "版本对比不可用。")
            }
            style={{ marginBottom: 12 }}
          />
          <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="当前版本">{versionCandidateLabel({ version: comparison.current_version, version_known: comparison.current_version !== null })}</Descriptions.Item>
            <Descriptions.Item label="基线版本">{versionCandidateLabel({ version: comparison.baseline_version, version_known: comparison.baseline_version !== null })}</Descriptions.Item>
            <Descriptions.Item label="基线任务">{comparison.baseline_task?.task_id ?? "未选择"}</Descriptions.Item>
            <Descriptions.Item label="完成时间">{formatVersionDateTime(comparison.baseline_task?.completed_at)}</Descriptions.Item>
          </Descriptions>
          {comparison.match.status === "matched" ? (
            <Typography.Paragraph>{versionSummaryMessage(comparison.summary)}</Typography.Paragraph>
          ) : null}
          {comparison.current_points.length || comparison.baseline_points.length ? (
            <VersionCompareChart comparison={comparison} unit={unit} />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function HistoryTrendPanel({
  metric,
  taskId,
  ruleCode,
  unitId,
  unit,
}: {
  metric: MetricTrendCellMetric;
  taskId?: string;
  ruleCode?: string;
  unitId?: string;
  unit?: string | null;
}) {
  const trends = metric.trends ?? [];
  const options = useMemo(() => buildTrendSelectionOptions(trends), [trends]);
  const [selection, setSelection] = useState<TrendSelection>(() => defaultTrendSelection(trends));
  const [history, setHistory] = useState<MeasurementHistoryTrend | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!taskId || !ruleCode || !unitId) return;
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    setHistory(null);
    const periodMinutes = selection.periodKey === "none" ? null : Number(selection.periodKey);
    api
      .getMeasurementHistoryTrend(taskId, ruleCode, unitId, metric.metric_resource_id, {
        object_key: selection.objectKey,
        period_minutes: Number.isFinite(periodMinutes) ? periodMinutes : null,
      })
      .then((data) => {
        if (seq === requestSeq.current) setHistory(data);
      })
      .catch((cause: unknown) => {
        if (seq !== requestSeq.current) return;
        setError(cause instanceof Error ? cause.message : "历史趋势加载失败");
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoading(false);
      });
  }, [metric.metric_resource_id, reloadNonce, ruleCode, selection.objectKey, selection.periodKey, taskId, unitId]);

  useEffect(() => {
    if (!options.objectOptions.length || !options.periodOptions.length) return;
    const objectAvailable = options.objectOptions.some((option) => option.value === selection.objectKey);
    const periodAvailable = options.periodOptions.some((option) => option.value === selection.periodKey);
    if (objectAvailable && periodAvailable) return;
    setSelection(defaultTrendSelection(metric.trends));
  }, [metric.trends, options.objectOptions, options.periodOptions, selection.objectKey, selection.periodKey]);

  const matchAlert = history ? historyMatchAlert(history.match) : null;
  const canRequest = Boolean(taskId && ruleCode && unitId);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <Select
          aria-label="历史行对象"
          options={options.objectOptions}
          style={{ width: 180 }}
          value={selection.objectKey}
          onChange={(value) => setSelection((current) => ({ ...current, objectKey: value }))}
        />
        <Select
          aria-label="历史周期"
          options={options.periodOptions}
          style={{ width: 150 }}
          value={selection.periodKey}
          onChange={(value) => setSelection((current) => ({ ...current, periodKey: value }))}
        />
        <Typography.Text type="secondary">
          设备 {history?.device_id || "未填写"} · 历史 {history?.coverage.history_date_count ?? 0} 天 · 样本{" "}
          {history?.coverage.history_point_count ?? 0}
        </Typography.Text>
      </div>
      {!canRequest ? (
        <Alert type="info" showIcon message="历史对比不可用" description="缺少任务或规则上下文，无法请求历史趋势。" />
      ) : loading ? (
        <div style={{ padding: 48, textAlign: "center" }}>
          <Spin />
        </div>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message="历史趋势加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => setReloadNonce((value) => value + 1)}>
              重试
            </Button>
          }
        />
      ) : history && matchAlert ? (
        <>
          <Alert type={matchAlert.type} showIcon message={matchAlert.title} description={matchAlert.description} style={{ marginBottom: 12 }} />
          {history.baseline_points.some((point) => point.significance === "insufficient") ? (
            <Typography.Paragraph type="secondary">部分同时刻历史样本不足 3 个，基线标记为样本不足。</Typography.Paragraph>
          ) : null}
          {history.history_series.length ? (
            <HistoryTrendChart history={history} unit={unit} />
          ) : (
            <Empty description="没有历史曲线数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </>
      ) : null}
    </div>
  );
}

type MetricTrendCellMetric = Pick<
  MeasurementMetadataMetric,
  "base_source_name" | "display_unit" | "metric_resource_id" | "metric_resource_name_zh" | "trend_points" | "trends"
>;

export function MetricTrendCell({
  metric,
  taskId,
  ruleCode,
  unitId,
}: {
  metric: MetricTrendCellMetric;
  taskId?: string;
  ruleCode?: string;
  unitId?: string;
}) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [detailMetric, setDetailMetric] = useState<MeasurementMetadataMetric | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const allPoints = metric.trend_points ?? [];
  const metricName = MetricDisplayName(metric);
  const comparison = analyzeTrendComparison(allPoints);

  useEffect(() => {
    if (!isModalOpen || detailMetric || detailError) return;
    if (!taskId || !ruleCode || !unitId) return;
    let cancelled = false;
    api
      .getMeasurementMetricDetail(taskId, ruleCode, unitId, metric.metric_resource_id)
      .then((detail) => {
        if (!cancelled) setDetailMetric(detail.metric as unknown as MeasurementMetadataMetric);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setDetailError(cause instanceof Error ? cause.message : "指标明细加载失败");
      })
    return () => {
      cancelled = true;
    };
  }, [detailError, detailMetric, isModalOpen, metric.metric_resource_id, ruleCode, taskId, unitId]);

  const displayMetric = detailMetric ?? metric;

  if (allPoints.length < 2) {
    return <span style={{ color: "rgba(0, 0, 0, 0.45)" }}>趋势点不足</span>;
  }

  return (
    <>
      <Button
        type="text"
        style={{ height: "auto", padding: 0 }}
        title="查看完整趋势"
        aria-label={`查看${metricName}完整趋势`}
        onClick={() => setIsModalOpen(true)}
      >
        <MiniTrend points={allPoints} />
      </Button>
      <Modal
        destroyOnHidden
        footer={null}
        open={isModalOpen}
        title={metricName}
        width={960}
        onCancel={() => setIsModalOpen(false)}
      >
        <Tabs
          defaultActiveKey="single"
          items={[
            {
              key: "single",
              label: "单任务",
              children: (
                <>
                  <TrendComparisonSummary comparison={comparison} unit={metric.display_unit} />
                  <TrendChart metricName={metricName} points={allPoints} unit={metric.display_unit} />
                  {comparison.mode === "multi_day" && (
                    <DailyTrendChart metricName={metricName} points={allPoints} unit={metric.display_unit} />
                  )}
                </>
              ),
            },
            {
              key: "history",
              label: "历史对比",
              children: (
                <HistoryTrendPanel
                  metric={displayMetric}
                  taskId={taskId}
                  ruleCode={ruleCode}
                  unitId={unitId}
                  unit={metric.display_unit}
                />
              ),
            },
            {
              key: "version",
              label: "版本对比",
              children: (
                <VersionComparePanel
                  metric={displayMetric}
                  taskId={taskId}
                  ruleCode={ruleCode}
                  unitId={unitId}
                  unit={metric.display_unit}
                />
              ),
            },
          ]}
        />
      </Modal>
    </>
  );
}
