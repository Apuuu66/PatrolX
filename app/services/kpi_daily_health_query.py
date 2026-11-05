"""KPI 日健康详情的任务查询与证据组装。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.core.config import settings
from app.models.schemas import InspectionTask, RuleResult
from app.services import task_db
from app.services.kpi_daily_health import (
    UTC8,
    DailyPoint,
    MetricDailyHealthConfig,
    build_metric_daily_health,
    date_in_utc8,
)
from app.services.kpi_measurement_units import KpiMeasurementError
from app.services.kpi_metric_maintenance import get_metric_maintenance_config
from app.services.store import load_rule_result


def _load_rule(task_id: str, rule_code: str) -> RuleResult | None:
    rule = task_db.get_rule_result(task_id, rule_code)
    if rule is not None:
        return rule
    try:
        return load_rule_result(settings.output, task_id, rule_code)
    except (OSError, ValueError):
        return None


def _daily_health_metadata(rule: RuleResult) -> dict[str, Any]:
    raw = (rule.metadata or {}).get("daily_health")
    if not isinstance(raw, dict):
        raise KpiMeasurementError(
            "kpi_daily_health_not_available",
            "该任务由旧版巡检器生成，缺少日健康结论；请重跑任务后查看",
            404,
        )
    try:
        data_date = date.fromisoformat(str(raw.get("data_date")))
    except ValueError as exc:
        raise KpiMeasurementError(
            "kpi_daily_health_not_available",
            "日健康结论缺少有效数据日期；请重跑任务后查看",
            404,
        ) from exc
    metrics = raw.get("metrics")
    if not isinstance(metrics, list):
        raise KpiMeasurementError(
            "kpi_daily_health_not_available",
            "日健康结论缺少指标范围；请重跑任务后查看",
            404,
        )
    return {**raw, "data_date": data_date}


def _require_metric_scope(
    metadata: dict[str, Any],
    measurement_unit_id: str,
    metric_resource_id: str,
) -> dict[str, Any]:
    for item in metadata.get("metrics", []):
        if not isinstance(item, dict):
            continue
        if (
            item.get("measurement_unit_id") == measurement_unit_id
            and item.get("metric_resource_id") == metric_resource_id
        ):
            return item
    raise KpiMeasurementError(
        "kpi_daily_health_metric_not_found",
        "该测量单元指标不在本次巡检的日健康范围内",
        404,
    )


def _window(anchor_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(anchor_date - timedelta(days=6), time.min, tzinfo=UTC8)
    end = datetime.combine(anchor_date + timedelta(days=1), time.min, tzinfo=UTC8)
    return start.astimezone(UTC), end.astimezone(UTC)


def _day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC8)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC8)
    return start.astimezone(UTC), end.astimezone(UTC)


def _as_point(payload: dict[str, Any]) -> DailyPoint | None:
    measured_at = payload.get("measured_at")
    if not isinstance(measured_at, datetime):
        return None
    value = payload.get("value")
    return DailyPoint(
        object_key=str(payload.get("object_key") or "__all__"),
        measured_at=measured_at,
        period_minutes=(int(payload["period_minutes"]) if isinstance(payload.get("period_minutes"), int) else None),
        value=float(value) if isinstance(value, (int, float)) else None,
        source_file=(str(payload["source_file"]) if payload.get("source_file") is not None else None),
    )


def _query_metric_points(
    task_id: str,
    rule_code: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[DailyPoint]:
    rows = task_db.list_kpi_points_for_metric(
        task_id,
        measurement_unit_id,
        metric_resource_id,
        start_at=start_at,
        end_at=end_at,
    )
    points = [point for row in rows if (point := _as_point(row)) is not None]
    return points


def _group_keys(points: Iterable[DailyPoint], day: date) -> set[tuple[str, int | None]]:
    return {(point.object_key, point.period_minutes) for point in points if date_in_utc8(point.measured_at) == day}


def _missing_yesterday_keys(
    points_by_metric: dict[str, list[DailyPoint]],
    required_metrics: Iterable[str],
    *,
    data_date: date,
) -> dict[str, set[tuple[str, int | None]]]:
    yesterday = data_date - timedelta(days=1)
    missing: dict[str, set[tuple[str, int | None]]] = {}
    for metric_id in required_metrics:
        points = points_by_metric.get(metric_id, [])
        target_keys = _group_keys(points, data_date)
        available_keys = _group_keys(points, yesterday)
        absent = target_keys - available_keys
        if absent:
            missing[metric_id] = absent
    return missing


def _history_points(
    task: InspectionTask,
    *,
    rule_code: str,
    measurement_unit_id: str,
    missing: dict[str, set[tuple[str, int | None]]],
    yesterday: date,
) -> dict[str, list[DailyPoint]]:
    """从同设备最近已完成任务补齐缺失的昨日同对象/周期证据。"""
    if not missing:
        return {}
    system = task.system
    customer = system.customer if system is not None and isinstance(system.customer, dict) else {}
    device_id = str(customer.get("device_id") or "").strip()
    completed_before = task.completed_at or task.last_run_at or task.created_at
    if not device_id or completed_before is None:
        return {}

    start_at, end_at = _day_window(yesterday)
    candidate_ids = task_db.list_previous_completed_task_ids(
        device_id,
        completed_before=completed_before,
    )
    for candidate_id in candidate_ids:
        candidate_points: dict[str, list[DailyPoint]] = {}
        for metric_id, keys in missing.items():
            points = _query_metric_points(
                candidate_id,
                rule_code,
                measurement_unit_id,
                metric_id,
                start_at=start_at,
                end_at=end_at,
            )
            matching = [point for point in points if (point.object_key, point.period_minutes) in keys]
            if matching:
                candidate_points[metric_id] = matching
        if all(metric_id in candidate_points for metric_id in missing):
            return candidate_points
    return {}


def _metric_config(config: dict[str, Any]) -> MetricDailyHealthConfig:
    return MetricDailyHealthConfig(
        measurement_unit_id=str(config["measurement_unit_id"]),
        metric_resource_id=str(config["metric_resource_id"]),
        name_zh=str(config["name_zh"]),
        role=config["role"],
        direction=config["direction"],
        warning_threshold=config["warning_threshold"],
        critical_threshold=config["critical_threshold"],
        daily_aggregation=config["daily_aggregation"],
        daily_change_threshold=config["daily_change_threshold"],
        daily_change_threshold_unit=config["daily_change_threshold_unit"],
        is_percentage=bool(config["is_percentage"]),
        zero_semantics=config["zero_semantics"],
        consistency_tolerance=float(config["consistency_tolerance"]),
        numerator_metric_id=config.get("numerator_metric_id"),
        denominator_metric_id=config.get("denominator_metric_id"),
        template=config.get("template", "success_rate"),
        config_source=config["config_source"],
        enabled=bool(config["enabled"]),
        object_match_mode=config.get("object_match_mode", "exact"),
    )


def get_kpi_daily_health_metric(
    task_id: str,
    rule_code: str,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> dict[str, Any]:
    """按需组装单指标日健康详情，避免扫描任务全部 KPI 点。"""
    task = task_db.get_task(task_id)
    if task is None:
        raise KpiMeasurementError("not_found", "任务不存在", 404)
    rule = _load_rule(task_id, rule_code)
    if rule is None:
        raise KpiMeasurementError("not_found", "规则结果不存在", 404)
    metadata = _daily_health_metadata(rule)
    _require_metric_scope(metadata, measurement_unit_id, metric_resource_id)

    config_payload = get_metric_maintenance_config(measurement_unit_id, metric_resource_id)
    config = _metric_config(config_payload)
    data_date: date = metadata["data_date"]
    start_at, end_at = _window(data_date)

    metric_ids = {metric_resource_id}
    if config.role == "derived" and config.numerator_metric_id and config.denominator_metric_id:
        metric_ids.update({config.numerator_metric_id, config.denominator_metric_id})
    points_by_metric = {
        metric_id: _query_metric_points(
            task_id,
            rule_code,
            measurement_unit_id,
            metric_id,
            start_at=start_at,
            end_at=end_at,
        )
        for metric_id in metric_ids
    }

    required_metrics = (
        [config.numerator_metric_id, config.denominator_metric_id]
        if config.role == "derived"
        and config.numerator_metric_id is not None
        and config.denominator_metric_id is not None
        else [metric_resource_id]
    )
    missing = _missing_yesterday_keys(
        points_by_metric,
        required_metrics,
        data_date=data_date,
    )
    history = _history_points(
        task,
        rule_code=rule_code,
        measurement_unit_id=measurement_unit_id,
        missing=missing,
        yesterday=data_date - timedelta(days=1),
    )
    for metric_id, points in history.items():
        points_by_metric.setdefault(metric_id, []).extend(points)

    if config.role == "derived":
        result = build_metric_daily_health(
            config,
            points_by_metric.get(metric_resource_id, []),
            numerator_points=points_by_metric.get(str(config.numerator_metric_id), []),
            denominator_points=points_by_metric.get(str(config.denominator_metric_id), []),
            raw_rate_points=points_by_metric.get(metric_resource_id, []),
            anchor_date=data_date,
        )
    else:
        result = build_metric_daily_health(
            config,
            points_by_metric.get(metric_resource_id, []),
            anchor_date=data_date,
        )
    return {
        "task_id": task_id,
        "rule_code": rule_code,
        "measurement_unit_id": measurement_unit_id,
        "metric_resource_id": metric_resource_id,
        **result,
    }
