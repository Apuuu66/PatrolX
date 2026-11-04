import { Alert, Button, Descriptions, Empty, Select, Spin, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  MeasurementHistoryTrend,
  MeasurementVersionCandidateList,
  MeasurementVersionComparison,
} from "../api/http";
import { api } from "../api/http";
import echarts from "../lib/echarts";
import {
  buildHistoryTrendChartOption,
  buildTrendSelectionOptions,
  defaultTrendSelection,
  historyMatchAlert,
  type TrendSelection,
} from "../utils/measurementHistory";
import {
  buildVersionCompareChartOption,
  formatVersionDateTime,
  versionCandidateLabel,
  versionCandidateOption,
  versionSummaryMessage,
} from "../utils/measurementVersionCompare";
import type { MetricTrendCellMetric } from "./MeasurementTrendTypes";

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

export function VersionComparePanel({
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
    () => (candidates ? candidates.items?.map((item) => versionCandidateOption(item, candidates.current_version ?? null)) : []),
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
      ) : candidates && !candidates.items?.length ? (
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
            <Descriptions.Item label="当前版本">{versionCandidateLabel({ version: comparison.current_version ?? null, version_known: comparison.current_version !== null && comparison.current_version !== undefined })}</Descriptions.Item>
            <Descriptions.Item label="基线版本">{versionCandidateLabel({ version: comparison.baseline_version ?? null, version_known: comparison.baseline_version != null })}</Descriptions.Item>
            <Descriptions.Item label="基线任务">{comparison.baseline_task?.task_id ?? "未选择"}</Descriptions.Item>
            <Descriptions.Item label="完成时间">{formatVersionDateTime(comparison.baseline_task?.completed_at)}</Descriptions.Item>
          </Descriptions>
          {comparison.match.status === "matched" ? (
            <Typography.Paragraph>{versionSummaryMessage({
              current_value: comparison.summary.current_value ?? null,
              baseline_value: comparison.summary.baseline_value ?? null,
              absolute_change: comparison.summary.absolute_change ?? null,
              change_ratio: comparison.summary.change_ratio ?? null,
              direction: comparison.summary.direction,
              message: comparison.summary.message,
            })}</Typography.Paragraph>
          ) : null}
          {comparison.current_points?.length || comparison.baseline_points?.length ? (
            <VersionCompareChart comparison={comparison} unit={unit} />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function HistoryTrendPanel({
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
          {(history.baseline_points ?? []).some((point) => point.significance === "insufficient") ? (
            <Typography.Paragraph type="secondary">部分同时刻历史样本不足 3 个，基线标记为样本不足。</Typography.Paragraph>
          ) : null}
          {(history.history_series ?? []).length ? (
            <HistoryTrendChart history={history} unit={unit} />
          ) : (
            <Empty description="没有历史曲线数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </>
      ) : null}
    </div>
  );
}
