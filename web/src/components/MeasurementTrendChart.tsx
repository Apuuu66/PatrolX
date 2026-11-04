import { Modal, Spin } from "antd";
import { lazy, Suspense, useState } from "react";
import type { MeasurementMetadataMetric, MeasurementTrendPoint } from "../api/http";
import type { MetricTrendCellMetric } from "./MeasurementTrendTypes";

const MeasurementTrendDetail = lazy(() => import("./MeasurementTrendDetail"));

function MetricDisplayName(metric: MetricTrendCellMetric): string {
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

export function MetricTrendCell({
  metric,
  detailMetric,
  taskId,
  ruleCode,
  unitId,
}: {
  metric: MetricTrendCellMetric;
  detailMetric?: MeasurementMetadataMetric | null;
  taskId?: string;
  ruleCode?: string;
  unitId?: string;
}) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const allPoints = detailMetric?.trend_points ?? metric.trend_points ?? [];
  const trendPointCount = metric.trend_point_count ?? allPoints.length;
  const metricName = MetricDisplayName(metric);
  const insufficientPoints = trendPointCount < 2;

  return (
    <>
      <button
        type="button"
        className={insufficientPoints ? "metric-trend-trigger is-text" : "metric-trend-trigger"}
        title={insufficientPoints ? "查看时间点明细" : "查看完整趋势"}
        aria-label={`查看${metricName}完整趋势`}
        aria-haspopup="dialog"
        onClick={() => setIsModalOpen(true)}
      >
        {insufficientPoints ? "趋势点不足，查看明细" : allPoints.length >= 2 ? <MiniTrend points={allPoints} /> : "查看趋势"}
      </button>
      {isModalOpen ? (
        <Modal
          destroyOnHidden
          footer={null}
          open
          title={metricName}
          width={960}
          onCancel={() => setIsModalOpen(false)}
        >
          <Suspense
            fallback={
              <div style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
                <Spin />
              </div>
            }
          >
            <MeasurementTrendDetail
              metric={metric}
              detailMetric={detailMetric}
              taskId={taskId}
              ruleCode={ruleCode}
              unitId={unitId}
            />
          </Suspense>
        </Modal>
      ) : null}
    </>
  );
}
