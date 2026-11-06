"""把巡检器已解析的 KPI 时间序列组装成紧凑日健康快照。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from app.models.db import (
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    TaskRecord,
    init_db,
    session_factory,
)
from app.models.schemas import Product
from app.services.kpi_daily_health import (
    UTC8,
    DailyPoint,
    MetricDailyHealthConfig,
    build_metric_daily_health,
    current_counts,
    date_in_utc8,
    trend_counts,
)

_DEFAULT_PERCENTAGE_TOLERANCE = 0.2


@dataclass(frozen=True, slots=True)
class _DailyHealthScope:
    """单个任务在日健康快照中使用的 v6 冻结输入。"""

    enabled_units: list[KpiV6MeasurementUnit]
    confirmed_bindings: list[KpiV6MeasurementBinding]
    derived_rows: list[KpiV6MeasurementDerived]
    resources: dict[str, KpiV6MeasurementResource]
    configs_by_metric: dict[tuple[str, str], KpiV6MetricMaintenanceConfig]
    unconfirmed_binding_count: int


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_utc8(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC8)
    return value.astimezone(UTC8)


def _iso_utc8(value: datetime | None) -> str | None:
    return None if value is None else _as_utc8(value).isoformat()


def _task_fallback_date(task: TaskRecord | None) -> date:
    if task is not None:
        for value in (task.completed_at, task.last_run_at, task.created_at):
            if value is not None:
                return _as_utc(value).astimezone(UTC8).date()
    return datetime.now(UTC).astimezone(UTC8).date()


def _task_network_element_type(task: TaskRecord | None) -> str | None:
    """任务网元类型只从元数据 product 解析，未知值不猜测作用域。"""
    if task is None or not isinstance(task.customer, dict):
        return None
    value = task.customer.get("product")
    if not isinstance(value, str):
        return None
    try:
        return Product(value).value
    except ValueError:
        return None


def _as_point(payload: dict[str, Any], *, source_file: str | None = None) -> DailyPoint | None:
    measured_at = payload.get("time")
    if isinstance(measured_at, str):
        try:
            measured_at = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(measured_at, datetime):
        return None
    measured_at = measured_at.replace(tzinfo=UTC) if measured_at.tzinfo is None else measured_at.astimezone(UTC)
    raw_value = payload.get("value")
    value = float(raw_value) if isinstance(raw_value, (int, float)) else None
    period = payload.get("period_minutes")
    point_source = source_file
    source_rows = payload.get("source_rows")
    if point_source is None and isinstance(source_rows, list) and source_rows:
        first_source = source_rows[0]
        if isinstance(first_source, dict) and isinstance(first_source.get("source_file"), str):
            point_source = first_source["source_file"]
    return DailyPoint(
        object_key=str(payload.get("object_key") or "__all__"),
        measured_at=measured_at,
        period_minutes=period if isinstance(period, int) else None,
        value=value,
        source_file=point_source,
        unreadable=value is None,
    )


def _series_points(metric_results: dict[str, Any], metric_id: str) -> list[DailyPoint]:
    points: list[DailyPoint] = []
    for payload in metric_results.values():
        if not isinstance(payload, dict) or payload.get("metric_resource_id") != metric_id:
            continue
        source_files = payload.get("source_files")
        default_source = source_files[0] if isinstance(source_files, list) and source_files else None
        for raw_point in payload.get("time_series", []):
            if not isinstance(raw_point, dict):
                continue
            point = _as_point(raw_point, source_file=default_source)
            if point is not None:
                points.append(point)
    return points


def _format_value(value: object, *, is_percentage: bool, display_unit: str | None) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if is_percentage:
        return f"{number:.1f}%"
    if display_unit:
        return f"{number:.6g}{display_unit}"
    return f"{number:.6g}"


def _format_delta(delta: object, *, is_percentage: bool, display_unit: str | None) -> str | None:
    if not isinstance(delta, (int, float)):
        return None
    number = float(delta)
    if is_percentage:
        return f"{number:+.1f}pp"
    suffix = display_unit or ""
    return f"{number:+.6g}{suffix}"


def _object_evidence(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    for group in groups:
        today = group.get("today")
        yesterday = group.get("yesterday")
        today_bucket = today if isinstance(today, dict) else {}
        yesterday_bucket = yesterday if isinstance(yesterday, dict) else {}
        objects.append(
            {
                "object_key": group.get("object_key"),
                "period_minutes": group.get("period_minutes"),
                "current_status": group.get("current_status"),
                "current_reason": group.get("reason"),
                "current_reason_code": group.get("current_reason_code"),
                "today_value": today_bucket.get("value"),
                "yesterday_value": yesterday_bucket.get("value"),
                "trend_status": group.get("trend_status"),
                "trend_reason": group.get("trend_reason"),
                "trend_reason_code": group.get("trend_reason_code"),
                "numerator": today_bucket.get("numerator"),
                "denominator": today_bucket.get("denominator"),
                "valid_count": today_bucket.get("valid_count", 0),
                "first_measured_at": _iso_utc8(
                    today_bucket.get("first_measured_at")
                    if isinstance(today_bucket.get("first_measured_at"), datetime)
                    else None
                ),
                "last_measured_at": _iso_utc8(
                    today_bucket.get("last_measured_at")
                    if isinstance(today_bucket.get("last_measured_at"), datetime)
                    else None
                ),
                "source_files": group.get("source_files", []),
            }
        )
    return objects


def _internal_rate_dependency_ids(
    derived_rows: list[KpiV6MeasurementDerived],
) -> set[str]:
    """返回成功率公式内部证据指标。"""
    suffixes = ("_NUMERATOR", "_DENOMINATOR")
    return {
        metric_id
        for row in derived_rows
        for metric_id in (row.numerator_metric_id, row.denominator_metric_id)
        if metric_id and metric_id.upper().endswith(suffixes)
    }


def _load_scope(session: Any, network_element_type: str | None) -> _DailyHealthScope:
    """一次读取当前网元类型的 v6 单元、绑定、派生、资源和维护口径。"""
    if network_element_type is None:
        return _DailyHealthScope([], [], [], {}, {}, 0)

    enabled_units = (
        session.query(KpiV6MeasurementUnit)
        .filter(
            KpiV6MeasurementUnit.network_element_type == network_element_type,
            KpiV6MeasurementUnit.inspection_enabled.is_(True),
        )
        .order_by(
            KpiV6MeasurementUnit.measurement_unit_id,
        )
        .all()
    )
    enabled_unit_ids = {unit.measurement_unit_id for unit in enabled_units}
    if not enabled_unit_ids:
        return _DailyHealthScope([], [], [], {}, {}, 0)

    binding_rows = (
        session.query(KpiV6MeasurementBinding)
        .filter(
            KpiV6MeasurementBinding.network_element_type == network_element_type,
            KpiV6MeasurementBinding.measurement_unit_id.in_(enabled_unit_ids),
        )
        .order_by(
            KpiV6MeasurementBinding.measurement_unit_id,
            KpiV6MeasurementBinding.metric_resource_id,
            KpiV6MeasurementBinding.id,
        )
        .all()
    )
    derived_rows = (
        session.query(KpiV6MeasurementDerived)
        .filter(
            KpiV6MeasurementDerived.network_element_type == network_element_type,
            KpiV6MeasurementDerived.measurement_unit_id.in_(enabled_unit_ids),
            KpiV6MeasurementDerived.definition_state == "defined",
        )
        .order_by(
            KpiV6MeasurementDerived.measurement_unit_id,
            KpiV6MeasurementDerived.metric_resource_id,
        )
        .all()
    )

    resource_ids = {str(binding.metric_resource_id) for binding in binding_rows if binding.metric_resource_id}
    for row in derived_rows:
        resource_ids.update((row.metric_resource_id, row.numerator_metric_id, row.denominator_metric_id))
    resources = {
        row.resource_id: row
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == network_element_type,
            KpiV6MeasurementResource.resource_id.in_(resource_ids),
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    confirmed_bindings = [
        binding
        for binding in binding_rows
        if binding.binding_state == "confirmed"
        and binding.metric_resource_id
        and binding.metric_resource_id in resources
    ]
    unconfirmed_binding_count = sum(
        1
        for binding in binding_rows
        if binding.binding_state != "confirmed"
        and binding.metric_resource_id
        and binding.metric_resource_id in resources
    )
    confirmed_identities = {
        (binding.measurement_unit_id, binding.metric_resource_id)
        for binding in confirmed_bindings
        if binding.metric_resource_id
    }
    # 源包直出的确认绑定是身份权威；残留派生定义不得改变指标角色或参与依赖裁剪。
    defined_derived = [
        row
        for row in derived_rows
        if row.metric_resource_id in resources
        and (row.measurement_unit_id, row.metric_resource_id) not in confirmed_identities
    ]
    maintenance_rows = (
        session.query(KpiV6MetricMaintenanceConfig)
        .filter(
            KpiV6MetricMaintenanceConfig.network_element_type == network_element_type,
            KpiV6MetricMaintenanceConfig.measurement_unit_id.in_(enabled_unit_ids),
        )
        .all()
    )
    return _DailyHealthScope(
        enabled_units=enabled_units,
        confirmed_bindings=confirmed_bindings,
        derived_rows=defined_derived,
        resources=resources,
        configs_by_metric={(row.measurement_unit_id, row.metric_resource_id): row for row in maintenance_rows},
        unconfirmed_binding_count=unconfirmed_binding_count,
    )


def _scope_snapshot(
    *,
    task_id: str,
    files: list[dict[str, Any]],
    scope_data: _DailyHealthScope,
) -> dict[str, Any]:
    enabled_units = scope_data.enabled_units
    enabled_unit_ids = {unit.measurement_unit_id for unit in enabled_units}
    confirmed_bindings = scope_data.confirmed_bindings
    confirmed_by_unit: dict[str, set[str]] = defaultdict(set)
    for binding in confirmed_bindings:
        if binding.metric_resource_id:
            confirmed_by_unit[binding.measurement_unit_id].add(binding.metric_resource_id)

    derived = scope_data.derived_rows
    internal_dependency_ids = _internal_rate_dependency_ids(derived)
    display_confirmed_bindings = [
        binding for binding in confirmed_bindings if binding.metric_resource_id not in internal_dependency_ids
    ]
    expected_metric_count = len(
        {(binding.measurement_unit_id, binding.metric_resource_id) for binding in display_confirmed_bindings}
        | {(row.measurement_unit_id, row.metric_resource_id) for row in derived}
    )

    out_of_scope_reasons: Counter[str] = Counter()
    for item in files:
        status = item.get("status")
        unit_id = item.get("measurement_unit_id")
        if status == "disabled":
            out_of_scope_reasons["disabled_unit"] += 1
        elif unit_id in enabled_unit_ids and not confirmed_by_unit.get(str(unit_id)):
            out_of_scope_reasons["unconfirmed_binding"] += 1

    return {
        "enabled_measurement_unit_count": len(enabled_units),
        "confirmed_binding_metric_count": len(
            {(binding.measurement_unit_id, binding.metric_resource_id) for binding in display_confirmed_bindings}
        ),
        "expected_metric_count": expected_metric_count,
        "out_of_scope_file_count": sum(out_of_scope_reasons.values()),
        "unconfirmed_binding_count": scope_data.unconfirmed_binding_count,
        "out_of_scope_reason_counts": dict(sorted(out_of_scope_reasons.items())),
        "task_id": task_id,
    }


def _metric_config(
    *,
    unit: KpiV6MeasurementUnit,
    resource: KpiV6MeasurementResource,
    binding: KpiV6MeasurementBinding | None,
    derived: KpiV6MeasurementDerived | None,
    config_row: KpiV6MetricMaintenanceConfig | None,
) -> MetricDailyHealthConfig:
    role: Literal["base", "derived"] = "derived" if derived is not None else "base"
    is_percentage = bool(config_row.is_percentage) if config_row is not None else False
    return MetricDailyHealthConfig(
        measurement_unit_id=unit.measurement_unit_id,
        metric_resource_id=resource.resource_id,
        name_zh=resource.name_zh,
        role=role,
        direction=(config_row.direction if config_row is not None else resource.direction),  # type: ignore[arg-type]
        warning_threshold=(config_row.warning_threshold if config_row is not None else resource.warning_threshold),
        critical_threshold=(config_row.critical_threshold if config_row is not None else resource.critical_threshold),
        daily_aggregation=(config_row.daily_aggregation if config_row is not None else "latest"),  # type: ignore[arg-type]
        daily_change_threshold=config_row.daily_change_threshold if config_row is not None else None,
        daily_change_threshold_unit=(config_row.daily_change_threshold_unit if config_row is not None else "auto"),  # type: ignore[arg-type]
        is_percentage=is_percentage,
        zero_semantics=(config_row.zero_semantics if config_row is not None else "unknown"),  # type: ignore[arg-type]
        consistency_tolerance=(
            config_row.consistency_tolerance if config_row is not None else _DEFAULT_PERCENTAGE_TOLERANCE
        ),
        numerator_metric_id=derived.numerator_metric_id if derived is not None else None,
        denominator_metric_id=derived.denominator_metric_id if derived is not None else None,
        template=(derived.template if derived is not None else "success_rate"),  # type: ignore[arg-type]
        config_source="custom" if config_row is not None else "default",
        importance=resource.importance,
        display_unit=(binding.display_unit if binding is not None else "%" if is_percentage else None),
        measurement_unit_name_zh=unit.name_zh,
        metric_resource_enabled=True,
        measurement_unit_enabled=bool(unit.inspection_enabled),
        binding_confirmed=binding is not None or derived is not None,
        object_match_mode=(config_row.object_match_mode if config_row is not None else "exact"),  # type: ignore[arg-type]
    )


def _metric_summary(
    *,
    unit: KpiV6MeasurementUnit,
    resource: KpiV6MeasurementResource,
    config: MetricDailyHealthConfig,
    built: dict[str, object],
    aggregation_source: str,
) -> dict[str, object]:
    metric = built["metric"]
    groups = built["groups"]
    assert isinstance(metric, dict)
    assert isinstance(groups, list)
    today_values = [
        group["today"].get("value")
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("today"), dict)
    ]
    today_value = next(
        (value for value in today_values if isinstance(value, (int, float))),
        None,
    )
    yesterday_value = next(
        (
            group["yesterday"].get("value")
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("yesterday"), dict)
            and isinstance(group["yesterday"].get("value"), (int, float))
        ),
        None,
    )
    delta = (
        float(today_value) - float(yesterday_value)
        if isinstance(today_value, (int, float)) and isinstance(yesterday_value, (int, float))
        else None
    )
    return {
        "measurement_unit_id": unit.measurement_unit_id,
        "measurement_unit_name_zh": unit.name_zh,
        "measurement_unit_enabled": bool(unit.inspection_enabled),
        "metric_resource_id": resource.resource_id,
        "metric_resource_name_zh": resource.name_zh,
        "metric_resource_enabled": True,
        "binding_confirmed": config.binding_confirmed,
        "role": config.role,
        "importance": resource.importance or "normal",
        "direction": resource.direction,
        "display_unit": config.display_unit,
        "is_percentage": config.is_percentage,
        "current_status": metric["current_status"],
        "current_reason": metric["current_reason_code"],
        "current_reason_text": metric["current_reason"],
        "today_value": today_value,
        "today_display": _format_value(
            today_value,
            is_percentage=config.is_percentage,
            display_unit=config.display_unit,
        ),
        "yesterday_value": yesterday_value,
        "yesterday_display": _format_value(
            yesterday_value,
            is_percentage=config.is_percentage,
            display_unit=config.display_unit,
        ),
        "delta": delta,
        "delta_display": _format_delta(
            delta,
            is_percentage=config.is_percentage,
            display_unit=config.display_unit,
        ),
        "trend_status": metric["trend_status"],
        "trend_reason": metric["trend_reason"],
        "trend_reason_code": metric["trend_reason_code"],
        "current_threshold": metric["current_threshold"],
        "change_threshold": metric["change_threshold"],
        "daily_aggregation": metric["daily_aggregation"],
        "aggregation_source": aggregation_source,
        "zero_semantics": config.zero_semantics,
        "consistency": metric["consistency"],
        "objects": _object_evidence(groups),
    }


def build_daily_health_snapshot(
    task_id: str,
    unit_results: dict[str, dict[str, Any]],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    """生成规则结果 metadata 中的指标级日健康快照。"""
    init_db()
    with session_factory() as session:
        task = session.get(TaskRecord, task_id)
        scope_data = _load_scope(session, _task_network_element_type(task))
        scope = _scope_snapshot(task_id=task_id, files=files, scope_data=scope_data)

    enabled_units = scope_data.enabled_units
    enabled_unit_ids = {unit.measurement_unit_id for unit in enabled_units}
    confirmed_bindings = scope_data.confirmed_bindings
    derived_rows = scope_data.derived_rows
    resources = scope_data.resources
    configs_by_metric = scope_data.configs_by_metric
    series_by_unit: dict[str, dict[str, list[DailyPoint]]] = defaultdict(lambda: defaultdict(list))
    all_points: list[DailyPoint] = []
    for unit_id, unit_result in unit_results.items():
        if unit_id not in enabled_unit_ids:
            continue
        metric_results = unit_result.get("metric_results")
        if not isinstance(metric_results, dict):
            continue
        for metric_id in {item.get("metric_resource_id") for item in metric_results.values() if isinstance(item, dict)}:
            if not isinstance(metric_id, str):
                continue
            points = _series_points(metric_results, metric_id)
            series_by_unit[unit_id][metric_id].extend(points)
            all_points.extend(points)

    valid_times = [point.measured_at for point in all_points if point.value is not None and not point.unreadable]
    latest_measured_at = max(valid_times, key=_as_utc8) if valid_times else None
    data_date = date_in_utc8(latest_measured_at) if latest_measured_at is not None else _task_fallback_date(task)
    previous_date = data_date - timedelta(days=1)

    by_unit_bindings: dict[str, dict[str, KpiV6MeasurementBinding]] = defaultdict(dict)
    for binding in confirmed_bindings:
        if binding.metric_resource_id:
            by_unit_bindings[binding.measurement_unit_id].setdefault(binding.metric_resource_id, binding)
    derived_by_unit: dict[str, dict[str, KpiV6MeasurementDerived]] = defaultdict(dict)
    for row in derived_rows:
        derived_by_unit[row.measurement_unit_id][row.metric_resource_id] = row
    internal_dependency_ids = _internal_rate_dependency_ids(derived_rows)

    metrics: list[dict[str, object]] = []
    for unit in enabled_units:
        metric_ids = set(by_unit_bindings.get(unit.measurement_unit_id, {})) - internal_dependency_ids
        metric_ids.update(set(derived_by_unit.get(unit.measurement_unit_id, {})) - internal_dependency_ids)
        for metric_id in sorted(
            metric_ids,
            key=lambda value: (
                resources[value].display_order is None if value in resources else True,
                resources[value].display_order if value in resources else 2**31,
                value,
            ),
        ):
            resource = resources.get(metric_id)
            if resource is None or resource.kind != "me":
                continue
            binding = by_unit_bindings.get(unit.measurement_unit_id, {}).get(metric_id)
            derived = derived_by_unit.get(unit.measurement_unit_id, {}).get(metric_id)
            config_row = configs_by_metric.get((unit.measurement_unit_id, metric_id))
            config = _metric_config(
                unit=unit,
                resource=resource,
                binding=binding,
                derived=derived,
                config_row=config_row,
            )
            base_points = series_by_unit[unit.measurement_unit_id].get(metric_id, [])
            if derived is not None:
                built = build_metric_daily_health(
                    config,
                    [],
                    numerator_points=series_by_unit[unit.measurement_unit_id].get(
                        derived.numerator_metric_id,
                        [],
                    ),
                    denominator_points=series_by_unit[unit.measurement_unit_id].get(
                        derived.denominator_metric_id,
                        [],
                    ),
                    raw_rate_points=base_points,
                    anchor_date=data_date,
                )
                aggregation_source = "custom" if config_row is not None else "default"
            else:
                built = build_metric_daily_health(
                    config,
                    base_points,
                    anchor_date=data_date,
                )
                aggregation_source = "custom" if config_row is not None else "default"
            metrics.append(
                _metric_summary(
                    unit=unit,
                    resource=resource,
                    config=config,
                    built=built,
                    aggregation_source=aggregation_source,
                )
            )

    return {
        "schema_version": 1,
        "timezone": "Asia/Shanghai",
        "data_date": data_date.isoformat(),
        "previous_date": previous_date.isoformat(),
        "latest_measured_at": _iso_utc8(latest_measured_at),
        "legacy_fallback": None,
        "current_counts": current_counts(metrics),
        "trend_counts": trend_counts(metrics),
        "scope": {key: value for key, value in scope.items() if key != "task_id"},
        "metrics": metrics,
    }
