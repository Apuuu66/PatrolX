"""KPI 指标维护配置、派生配置与审计服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, aliased

from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceAudit,
    KpiMetricMaintenanceConfig,
    init_db,
    session_factory,
)
from app.services.kpi_measurement_units import KpiMeasurementError

_MUTABLE_CONFIG_FIELDS = (
    "role",
    "direction",
    "warning_threshold",
    "critical_threshold",
    "daily_aggregation",
    "daily_change_threshold",
    "daily_change_threshold_unit",
    "is_percentage",
    "zero_semantics",
    "consistency_tolerance",
    "object_match_mode",
    "enabled",
)
_DERIVED_FIELDS = ("numerator_metric_id", "denominator_metric_id", "template", "enabled")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_percentage_metric(resource: KpiMeasurementResource, *, role: str) -> bool:
    if role == "derived":
        return True
    display_unit = (resource.filename_fragment or "").strip()
    name = f"{resource.name_zh} {resource.name_en} {resource.resource_id}".lower()
    return (
        display_unit == "%"
        or "率" in resource.name_zh
        or any(token in name for token in ("rate", "ratio", "percent", "utilization"))
    )


def _require_binding(
    session: Session,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> tuple[KpiMeasurementResource, KpiMeasurementResource, KpiMeasurementBinding]:
    unit = session.get(KpiMeasurementResource, measurement_unit_id)
    if unit is None or unit.kind != "mu":
        raise KpiMeasurementError(
            "kpi_metric_config_not_found",
            f"测量单元不存在: {measurement_unit_id}",
            404,
        )
    resource = session.get(KpiMeasurementResource, metric_resource_id)
    if resource is None or resource.kind != "me":
        raise KpiMeasurementError(
            "kpi_metric_config_not_found",
            f"指标不存在或未绑定到测量单元: {metric_resource_id}",
            404,
        )
    binding = (
        session.query(KpiMeasurementBinding)
        .filter_by(
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            status="confirmed",
        )
        .first()
    )
    if binding is None:
        raise KpiMeasurementError(
            "kpi_metric_config_not_found",
            f"指标未确认绑定到测量单元: {metric_resource_id}",
            404,
        )
    return unit, resource, binding


def _effective_config(
    session: Session,
    unit: KpiMeasurementResource,
    resource: KpiMeasurementResource,
    binding: KpiMeasurementBinding,
    config_row: KpiMetricMaintenanceConfig | None = None,
    derived_row: KpiMeasurementDerived | None = None,
) -> dict[str, Any]:
    if config_row is None:
        config_row = (
            session.query(KpiMetricMaintenanceConfig)
            .filter_by(
                measurement_unit_id=unit.resource_id,
                metric_resource_id=resource.resource_id,
            )
            .first()
        )
    if derived_row is None:
        derived_row = (
            session.query(KpiMeasurementDerived)
            .filter_by(
                measurement_unit_id=unit.resource_id,
                metric_resource_id=resource.resource_id,
            )
            .first()
        )
    role = config_row.role if config_row is not None else ("derived" if derived_row is not None else "base")
    return {
        "measurement_unit_id": unit.resource_id,
        "metric_resource_id": resource.resource_id,
        "name_zh": resource.name_zh,
        "role": role,
        "direction": resource.direction,
        "warning_threshold": resource.warning_threshold,
        "critical_threshold": resource.critical_threshold,
        "daily_aggregation": config_row.daily_aggregation if config_row is not None else "latest",
        "daily_change_threshold": config_row.daily_change_threshold if config_row is not None else None,
        "daily_change_threshold_unit": (config_row.daily_change_threshold_unit if config_row is not None else "auto"),
        "is_percentage": (
            config_row.is_percentage if config_row is not None else _is_percentage_metric(resource, role=role)
        ),
        "zero_semantics": config_row.zero_semantics if config_row is not None else "unknown",
        "consistency_tolerance": config_row.consistency_tolerance if config_row is not None else 0.2,
        "object_match_mode": config_row.object_match_mode if config_row is not None else "exact",
        "numerator_metric_id": derived_row.numerator_metric_id if derived_row is not None else None,
        "denominator_metric_id": derived_row.denominator_metric_id if derived_row is not None else None,
        "template": derived_row.template if derived_row is not None else "success_rate",
        "enabled": bool(resource.enabled and binding.enabled),
        "config_source": "custom" if config_row is not None else "legacy_resource",
        "updated_at": _as_utc(config_row.updated_at if config_row is not None else resource.updated_at),
    }


def get_metric_maintenance_config(measurement_unit_id: str, metric_resource_id: str) -> dict[str, Any]:
    """返回单个已绑定指标的有效维护配置。"""
    init_db()
    with session_factory() as session:
        unit, resource, binding = _require_binding(session, measurement_unit_id, metric_resource_id)
        return _effective_config(session, unit, resource, binding)


def list_metric_maintenance_configs(
    *,
    measurement_unit_id: str | None = None,
    metric_resource_id: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页返回已确认绑定指标的有效维护配置。"""
    init_db()
    unit_resource = aliased(KpiMeasurementResource)
    with session_factory() as session:
        query = (
            session.query(KpiMeasurementBinding, KpiMeasurementResource, unit_resource)
            .join(
                KpiMeasurementResource,
                KpiMeasurementResource.resource_id == KpiMeasurementBinding.metric_resource_id,
            )
            .join(unit_resource, unit_resource.resource_id == KpiMeasurementBinding.measurement_unit_id)
            .filter(
                KpiMeasurementBinding.status == "confirmed",
                KpiMeasurementResource.kind == "me",
                unit_resource.kind == "mu",
            )
        )
        if measurement_unit_id:
            query = query.filter(KpiMeasurementBinding.measurement_unit_id == measurement_unit_id)
        if metric_resource_id:
            query = query.filter(KpiMeasurementBinding.metric_resource_id == metric_resource_id)
        rows = query.all()
        configs = [_effective_config(session, unit, resource, binding) for binding, resource, unit in rows]
        if enabled is not None:
            configs = [item for item in configs if item["enabled"] is enabled]
        configs.sort(
            key=lambda item: (
                next(
                    (
                        unit.display_order if unit.display_order is not None else 2**31
                        for binding, resource, unit in rows
                        if unit.resource_id == item["measurement_unit_id"]
                    ),
                    2**31,
                ),
                item["measurement_unit_id"],
                next(
                    (
                        resource.display_order if resource.display_order is not None else 2**31
                        for binding, resource, unit in rows
                        if binding.measurement_unit_id == item["measurement_unit_id"]
                        and resource.resource_id == item["metric_resource_id"]
                    ),
                    2**31,
                ),
                item["metric_resource_id"],
            )
        )
        total = len(configs)
        offset = (page - 1) * page_size
        return {
            "total": total,
            "items": configs[offset : offset + page_size],
            "page": page,
            "page_size": page_size,
        }


def update_metric_maintenance_config(
    measurement_unit_id: str,
    metric_resource_id: str,
    updates: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """原子更新资源阈值和扩展维护口径，并写审计。"""
    requested = {field: value for field, value in updates.items() if field in _MUTABLE_CONFIG_FIELDS}
    if not requested:
        raise KpiMeasurementError("kpi_metric_config_empty_update", "没有可更新的配置字段", 400)
    if requested.get("object_match_mode", "exact") != "exact":
        raise KpiMeasurementError(
            "kpi_metric_object_match_unsupported",
            "当前只支持对象精确匹配",
            409,
        )
    init_db()
    with session_factory() as session:
        unit, resource, binding = _require_binding(session, measurement_unit_id, metric_resource_id)
        config_row = (
            session.query(KpiMetricMaintenanceConfig)
            .filter_by(measurement_unit_id=measurement_unit_id, metric_resource_id=metric_resource_id)
            .first()
        )
        derived_row = (
            session.query(KpiMeasurementDerived)
            .filter_by(measurement_unit_id=measurement_unit_id, metric_resource_id=metric_resource_id)
            .first()
        )
        if requested.get("role") == "derived" and derived_row is None:
            raise KpiMeasurementError(
                "kpi_metric_role_requires_derived",
                "设为聚合指标前必须先配置分子和分母",
                409,
            )

        before = _effective_config(session, unit, resource, binding, config_row, derived_row)
        now = _utc_now()
        if config_row is None:
            config_row = KpiMetricMaintenanceConfig(
                measurement_unit_id=measurement_unit_id,
                metric_resource_id=metric_resource_id,
                role=before["role"],
                daily_aggregation=before["daily_aggregation"],
                daily_change_threshold=before["daily_change_threshold"],
                daily_change_threshold_unit=before["daily_change_threshold_unit"],
                is_percentage=before["is_percentage"],
                zero_semantics=before["zero_semantics"],
                consistency_tolerance=before["consistency_tolerance"],
                object_match_mode=before["object_match_mode"],
                created_at=now,
                updated_at=now,
            )
            session.add(config_row)

        if "role" in requested:
            config_row.role = requested["role"]
        if "daily_aggregation" in requested:
            config_row.daily_aggregation = requested["daily_aggregation"]
        if "daily_change_threshold" in requested:
            config_row.daily_change_threshold = requested["daily_change_threshold"]
        if "daily_change_threshold_unit" in requested:
            config_row.daily_change_threshold_unit = requested["daily_change_threshold_unit"]
        if "is_percentage" in requested:
            config_row.is_percentage = requested["is_percentage"]
        if "zero_semantics" in requested:
            config_row.zero_semantics = requested["zero_semantics"]
        if "consistency_tolerance" in requested:
            config_row.consistency_tolerance = requested["consistency_tolerance"]
        if "object_match_mode" in requested:
            config_row.object_match_mode = requested["object_match_mode"]
        config_row.updated_at = now

        if "direction" in requested:
            resource.direction = requested["direction"]
        if "warning_threshold" in requested:
            resource.warning_threshold = requested["warning_threshold"]
        if "critical_threshold" in requested:
            resource.critical_threshold = requested["critical_threshold"]
        if "enabled" in requested:
            resource.enabled = requested["enabled"]
        resource.updated_at = now
        session.flush()

        after = _effective_config(session, unit, resource, binding, config_row, derived_row)
        # 审计记录维护人员本次显式提交的字段；即使有效值与历史默认值相同，
        # 也需要保留“已确认该口径”的操作证据。
        changed_fields = list(requested)
        if changed_fields:
            session.add(
                KpiMetricMaintenanceAudit(
                    measurement_unit_id=measurement_unit_id,
                    metric_resource_id=metric_resource_id,
                    actor=actor,
                    changed_fields=changed_fields,
                    before_values={field: before.get(field) for field in changed_fields},
                    after_values={field: after.get(field) for field in changed_fields},
                    created_at=now,
                )
            )
        session.commit()
        return after


def list_metric_maintenance_audits(
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """按配置分页读取审计记录。"""
    init_db()
    with session_factory() as session:
        _require_binding(session, measurement_unit_id, metric_resource_id)
        query = session.query(KpiMetricMaintenanceAudit).filter_by(
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
        )
        total = query.count()
        rows = (
            query.order_by(KpiMetricMaintenanceAudit.created_at.desc(), KpiMetricMaintenanceAudit.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "total": total,
            "items": [
                {
                    "id": row.id,
                    "measurement_unit_id": row.measurement_unit_id,
                    "metric_resource_id": row.metric_resource_id,
                    "actor": row.actor,
                    "changed_fields": list(row.changed_fields or []),
                    "before_values": row.before_values or {},
                    "after_values": row.after_values or {},
                    "created_at": _as_utc(row.created_at),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
        }


def _derived_view(session: Session, row: KpiMeasurementDerived) -> dict[str, Any]:
    resource_ids = {
        row.metric_resource_id,
        row.numerator_metric_id,
        row.denominator_metric_id,
    }
    names = {
        resource.resource_id: resource.name_zh
        for resource in session.query(KpiMeasurementResource)
        .filter(KpiMeasurementResource.resource_id.in_(resource_ids))
        .all()
    }
    return {
        "id": row.id,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "numerator_metric_id": row.numerator_metric_id,
        "denominator_metric_id": row.denominator_metric_id,
        "template": row.template,
        "enabled": bool(row.enabled),
        "metric_resource_name_zh": names.get(row.metric_resource_id, ""),
        "numerator_metric_name_zh": names.get(row.numerator_metric_id, ""),
        "denominator_metric_name_zh": names.get(row.denominator_metric_id, ""),
        "created_at": _as_utc(row.created_at),
        "updated_at": _as_utc(row.updated_at),
    }


def list_measurement_derived(
    *,
    measurement_unit_id: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页读取派生配置并补充独立指标名称。"""
    init_db()
    with session_factory() as session:
        query = session.query(KpiMeasurementDerived)
        if measurement_unit_id:
            query = query.filter(KpiMeasurementDerived.measurement_unit_id == measurement_unit_id)
        if enabled is not None:
            query = query.filter(KpiMeasurementDerived.enabled.is_(enabled))
        total = query.count()
        rows = (
            query.order_by(
                KpiMeasurementDerived.measurement_unit_id,
                KpiMeasurementDerived.metric_resource_id,
                KpiMeasurementDerived.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "total": total,
            "items": [_derived_view(session, row) for row in rows],
            "page": page,
            "page_size": page_size,
        }


def get_measurement_derived(derived_id: int) -> dict[str, Any]:
    """读取单条派生配置。"""
    init_db()
    with session_factory() as session:
        row = session.get(KpiMeasurementDerived, derived_id)
        if row is None:
            raise KpiMeasurementError(
                "kpi_measurement_derived_not_found",
                f"派生配置不存在: {derived_id}",
                404,
            )
        return _derived_view(session, row)


def _validate_derived_dependency(
    session: Session,
    *,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> None:
    resource = session.get(KpiMeasurementResource, metric_resource_id)
    if resource is None or resource.kind != "me":
        raise KpiMeasurementError(
            "kpi_metric_not_found",
            f"派生依赖指标不存在: {metric_resource_id}",
            404,
        )
    binding = (
        session.query(KpiMeasurementBinding)
        .filter_by(
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            status="confirmed",
            enabled=True,
        )
        .first()
    )
    if binding is None:
        raise KpiMeasurementError(
            "kpi_binding_not_confirmed",
            f"依赖指标未确认绑定: {metric_resource_id}",
            409,
        )


def update_measurement_derived(
    derived_id: int,
    updates: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """更新派生依赖或启用状态并写维护审计。"""
    requested = {field: value for field, value in updates.items() if field in _DERIVED_FIELDS}
    if not requested:
        raise KpiMeasurementError("kpi_measurement_derived_empty_update", "没有可更新的派生配置字段", 400)
    init_db()
    with session_factory() as session:
        row = session.get(KpiMeasurementDerived, derived_id)
        if row is None:
            raise KpiMeasurementError(
                "kpi_measurement_derived_not_found",
                f"派生配置不存在: {derived_id}",
                404,
            )
        for field in ("numerator_metric_id", "denominator_metric_id"):
            if field in requested:
                _validate_derived_dependency(
                    session,
                    measurement_unit_id=row.measurement_unit_id,
                    metric_resource_id=requested[field],
                )
        before = {field: getattr(row, field) for field in _DERIVED_FIELDS}
        for field, value in requested.items():
            setattr(row, field, value)
        row.updated_at = _utc_now()
        session.flush()
        after = {field: getattr(row, field) for field in _DERIVED_FIELDS}
        changed_fields = [field for field in requested if before[field] != after[field]]
        if changed_fields:
            session.add(
                KpiMetricMaintenanceAudit(
                    measurement_unit_id=row.measurement_unit_id,
                    metric_resource_id=row.metric_resource_id,
                    actor=actor,
                    changed_fields=changed_fields,
                    before_values={field: before[field] for field in changed_fields},
                    after_values={field: after[field] for field in changed_fields},
                    created_at=row.updated_at,
                )
            )
        session.commit()
        return _derived_view(session, row)
