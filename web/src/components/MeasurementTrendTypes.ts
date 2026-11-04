import type { MeasurementMetadataMetric } from "../api/http";

export type MetricTrendCellMetric = Pick<
  MeasurementMetadataMetric,
  | "base_source_name"
  | "display_unit"
  | "metric_resource_id"
  | "metric_resource_name_zh"
  | "trend_point_count"
  | "trend_points"
  | "trend_reason"
  | "trends"
>;
