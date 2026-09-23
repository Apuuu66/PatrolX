"""规则结果展示层摘要与明细拆分。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models.schemas import RuleResult

KPI_RULE_CODE = "kpi.measurement_units"
KPI_SUMMARY_TREND_POINTS = 24
_RECORD_ONLY_METRIC_FIELDS = ("trends", "observations", "source_rows", "source_files")
_RECORD_ONLY_UNIT_FIELDS = ("objects",)


def _sample_points(points: list[dict[str, Any]], limit: int = KPI_SUMMARY_TREND_POINTS) -> list[dict[str, Any]]:
    """等距保留趋势形态；点数不足时原样返回。"""
    if len(points) <= limit:
        return points
    if limit < 2:
        return points[:limit]
    indexes = sorted({round(index * (len(points) - 1) / (limit - 1)) for index in range(limit)})
    return [points[index] for index in indexes]


def _strip_source_rows(point: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in point.items() if key != "source_rows"}


def summarize_kpi_result(result: RuleResult) -> RuleResult:
    """生成 KPI 首屏摘要；完整趋势、行观察和来源行由明细接口返回。"""
    if result.code != KPI_RULE_CODE:
        return result

    metadata = deepcopy(result.metadata)
    units = metadata.get("measurement_units", [])
    if isinstance(units, list):
        for unit in units:
            if not isinstance(unit, dict):
                continue
            unit.pop("objects", None)
            metrics = unit.get("metrics", [])
            if not isinstance(metrics, list):
                continue
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                for field in _RECORD_ONLY_METRIC_FIELDS:
                    metric.pop(field, None)
                points = metric.get("trend_points", [])
                if isinstance(points, list):
                    metric["trend_point_count"] = len(points)
                    metric["trend_points"] = [_strip_source_rows(point) for point in _sample_points(points)]

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
