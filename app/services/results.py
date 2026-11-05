"""规则结果展示层摘要与明细拆分。"""

from __future__ import annotations

from typing import Any

from app.models.schemas import RuleResult

KPI_RULE_CODE = "kpi.measurement_units"
_RECORD_ONLY_METRIC_FIELDS = ("trends", "trend_points", "observations", "source_rows", "source_files")
_RECORD_ONLY_UNIT_FIELDS = ("objects",)
_DAILY_HEALTH_DETAIL_FIELDS = ("objects", "groups", "seven_day_trend")


def summarize_kpi_result(result: RuleResult) -> RuleResult:
    """生成 KPI 首屏摘要；趋势点、行观察和来源行全部由明细接口返回。"""
    if result.code != KPI_RULE_CODE:
        return result

    metadata = dict(result.metadata)
    units = metadata.get("measurement_units")
    if isinstance(units, list):
        summary_units: list[Any] = []
        for unit in units:
            if not isinstance(unit, dict):
                summary_units.append(unit)
                continue

            summary_unit = {key: value for key, value in unit.items() if key not in _RECORD_ONLY_UNIT_FIELDS}
            metrics = summary_unit.get("metrics")
            if isinstance(metrics, list):
                summary_metrics: list[Any] = []
                for metric in metrics:
                    if not isinstance(metric, dict):
                        summary_metrics.append(metric)
                        continue

                    points = metric.get("trend_points")
                    summary_metric = {
                        key: value for key, value in metric.items() if key not in _RECORD_ONLY_METRIC_FIELDS
                    }
                    if isinstance(points, list):
                        summary_metric["trend_point_count"] = len(points)
                    summary_metrics.append(summary_metric)
                summary_unit["metrics"] = summary_metrics
            summary_units.append(summary_unit)
        metadata["measurement_units"] = summary_units

    daily_health = metadata.get("daily_health")
    if isinstance(daily_health, dict):
        summary_daily_health = dict(daily_health)
        metrics = summary_daily_health.get("metrics")
        if isinstance(metrics, list):
            summary_metrics: list[Any] = []
            for metric in metrics:
                if not isinstance(metric, dict):
                    summary_metrics.append(metric)
                    continue
                summary_metric = {key: value for key, value in metric.items() if key not in _DAILY_HEALTH_DETAIL_FIELDS}
                objects = metric.get("objects")
                if isinstance(objects, list):
                    summary_metric["object_count"] = len(objects)
                summary_metrics.append(summary_metric)
            summary_daily_health["metrics"] = summary_metrics
        metadata["daily_health"] = summary_daily_health

    return result.model_copy(update={"metadata": metadata, "metrics": [], "findings": []})


def find_kpi_metric_detail(
    result: RuleResult,
    *,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> dict[str, Any] | None:
    """从完整规则结果中定位单个指标明细。"""
    if result.code != KPI_RULE_CODE:
        return None
    units = result.metadata.get("measurement_units", [])
    if not isinstance(units, list):
        return None
    for unit in units:
        if not isinstance(unit, dict) or unit.get("measurement_unit_id") != measurement_unit_id:
            continue
        metrics = unit.get("metrics", [])
        if not isinstance(metrics, list):
            return None
        for metric in metrics:
            if isinstance(metric, dict) and metric.get("metric_resource_id") == metric_resource_id:
                return metric
        return None
    return None
