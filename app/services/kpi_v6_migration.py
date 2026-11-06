"""KPI v5 配置到 v6 网元作用域的幂等只读迁移。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.db import (
    KpiLegacyRecoveryAudit,
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    KpiPendingAttribution,
    KpiRuleAssignmentGlobalState,
    KpiTeamFocusRevision,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    TaskRecord,
    session_factory,
)

_SUPPORTED_NETWORK_TYPES = ("CSP", "UMF")
_VALID_RESOURCE_SOURCES = frozenset({"preset", "discovered", "manual"})
_VALID_BINDING_STATES = frozenset({"candidate", "confirmed", "conflict", "ignored"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _network_type_from_task(task: TaskRecord | None) -> str | None:
    """仅从任务元数据提取受支持的网元类型，不使用规则字段兜底。"""
    if task is None or not isinstance(task.customer, dict):
        return None
    value = task.customer.get("product")
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if normalized in _SUPPORTED_NETWORK_TYPES else None


def _stable_source_key(source_table: str, source_record_id: object) -> str:
    return f"v5:{source_table}:{source_record_id}"


def _idempotency_key(source_key: str) -> str:
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _snapshot(row: Any, *field_names: str) -> dict[str, Any]:
    return {name: _json_value(getattr(row, name, None)) for name in field_names}


def _unique_type(candidates: set[str]) -> str | None:
    return next(iter(candidates)) if len(candidates) == 1 else None


def _row_enabled(row: Any) -> bool:
    return bool(getattr(row, "enabled", False))


def _row_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _pending_reason(candidates: set[str], *, orphan_reference: bool = False) -> str:
    if orphan_reference:
        return "orphan_reference"
    if not candidates:
        return "missing_product"
    return "ambiguous_product"


def _insert_ignore(session: Session, model: type[Any], values: dict[str, Any]) -> None:
    session.execute(sqlite_insert(model.__table__).values(**values).on_conflict_do_nothing())


def _insert_pending(
    session: Session,
    *,
    source_table: str,
    source_record_id: object,
    payload: dict[str, Any],
    candidates: set[str],
    reason: str,
    now: datetime,
    last_error: str | None = None,
) -> None:
    source_key = _stable_source_key(source_table, source_record_id)
    _insert_ignore(
        session,
        KpiPendingAttribution,
        {
            "source_table": source_table,
            "source_record_id": str(source_record_id),
            "source_key": source_key,
            "source_payload": _json_value(payload),
            "candidate_network_element_types": sorted(candidates),
            "reason": reason,
            "resolution_state": "pending",
            "assigned_network_element_type": None,
            "attempt_count": 1 if last_error else 0,
            "last_error": last_error,
            "idempotency_key": _idempotency_key(source_key),
            "created_at": now,
            "updated_at": now,
        },
    )


def _insert_recovery_audit(
    session: Session,
    *,
    source_table: str,
    source_record_id: object,
    network_element_type: str | None,
    measurement_unit_id: str | None,
    metric_resource_id: str | None,
    object_kind: str,
    before_snapshot: dict[str, Any],
    result: str,
    now: datetime,
    error_code: str | None = None,
) -> None:
    source_key = _stable_source_key(source_table, source_record_id)
    _insert_ignore(
        session,
        KpiLegacyRecoveryAudit,
        {
            "source_table": source_table,
            "source_record_id": str(source_record_id),
            "source_key": source_key,
            "network_element_type": network_element_type,
            "measurement_unit_id": measurement_unit_id,
            "metric_resource_id": metric_resource_id,
            "object_kind": object_kind,
            "before_snapshot": before_snapshot,
            "result": result,
            "error_code": error_code,
            "attempt_count": 0,
            "actor": None,
            "source": "migration",
            "created_at": now,
            "updated_at": now,
        },
    )


def _initialize_shared_state(session: Session, now: datetime) -> None:
    for network_element_type in _SUPPORTED_NETWORK_TYPES:
        _insert_ignore(
            session,
            KpiTeamFocusRevision,
            {
                "network_element_type": network_element_type,
                "revision": 0,
                "updated_at": now,
            },
        )
    _insert_ignore(
        session,
        KpiRuleAssignmentGlobalState,
        {
            "id": 1,
            "revision": 0,
            "updated_at": now,
        },
    )


def _resource_values(row: KpiMeasurementResource, network_element_type: str) -> dict[str, Any]:
    source = row.source if row.source in _VALID_RESOURCE_SOURCES else "discovered"
    return {
        "network_element_type": network_element_type,
        "resource_id": row.resource_id,
        "kind": row.kind,
        "name_zh": row.name_zh,
        "name_en": row.name_en,
        "filename_fragment": row.filename_fragment,
        "display_order": row.display_order,
        "metric_group": row.metric_group,
        "direction": row.direction,
        "importance": row.importance,
        "warning_threshold": row.warning_threshold,
        "critical_threshold": row.critical_threshold,
        "source": source,
        "origin_task_id": row.origin_task_id,
        "origin_file": row.origin_file,
        "legacy_source_key": _stable_source_key(KpiMeasurementResource.__tablename__, row.resource_id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _unit_values(row: KpiMeasurementResource, network_element_type: str) -> dict[str, Any]:
    fingerprint_payload = {
        "network_element_type": network_element_type,
        "measurement_unit_id": row.resource_id,
        "name_zh": row.name_zh,
        "name_en": row.name_en,
        "filename_fragment": row.filename_fragment,
        "inspection_enabled": bool(row.enabled),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    source = row.source if row.source in _VALID_RESOURCE_SOURCES else "discovered"
    return {
        "network_element_type": network_element_type,
        "measurement_unit_id": row.resource_id,
        "name_zh": row.name_zh,
        "name_en": row.name_en,
        "inspection_enabled": bool(row.enabled),
        "revision": 0,
        "config_fingerprint": fingerprint,
        "source": source,
        "origin_task_id": row.origin_task_id,
        "legacy_source_key": _stable_source_key(KpiMeasurementResource.__tablename__, row.resource_id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _binding_values(row: KpiMeasurementBinding, network_element_type: str) -> dict[str, Any]:
    binding_state = row.status if row.status in _VALID_BINDING_STATES else "candidate"
    return {
        "network_element_type": network_element_type,
        "measurement_unit_id": row.measurement_unit_id,
        "raw_source_name": row.raw_source_name,
        "base_source_name": row.base_source_name,
        "metric_resource_id": row.metric_resource_id,
        "display_unit": row.display_unit,
        "binding_state": binding_state,
        "source_file": row.source_file,
        "origin_task_id": row.task_id,
        "revision": 0,
        "legacy_source_key": _stable_source_key(KpiMeasurementBinding.__tablename__, row.id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _derived_values(row: KpiMeasurementDerived, network_element_type: str) -> dict[str, Any]:
    return {
        "network_element_type": network_element_type,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "numerator_metric_id": row.numerator_metric_id,
        "denominator_metric_id": row.denominator_metric_id,
        "template": row.template,
        "definition_state": "defined",
        "revision": 0,
        "legacy_source_key": _stable_source_key(KpiMeasurementDerived.__tablename__, row.id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _maintenance_values(
    row: KpiMetricMaintenanceConfig,
    *,
    network_element_type: str,
    metric_resource: KpiMeasurementResource | None,
) -> dict[str, Any]:
    return {
        "network_element_type": network_element_type,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "role": row.role,
        "direction": metric_resource.direction if metric_resource is not None else None,
        "warning_threshold": metric_resource.warning_threshold if metric_resource is not None else None,
        "critical_threshold": metric_resource.critical_threshold if metric_resource is not None else None,
        "daily_aggregation": row.daily_aggregation,
        "daily_change_threshold": row.daily_change_threshold,
        "daily_change_threshold_unit": row.daily_change_threshold_unit,
        "is_percentage": bool(row.is_percentage),
        "zero_semantics": row.zero_semantics,
        "consistency_tolerance": row.consistency_tolerance,
        "object_match_mode": row.object_match_mode,
        "config_state": "ready",
        "revision": 0,
        "legacy_source_key": _stable_source_key(KpiMetricMaintenanceConfig.__tablename__, row.id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def migrate_kpi_v6() -> dict[str, int]:
    """幂等迁移可唯一归属的 v5 KPI 配置，不修改或删除 v5 行。"""
    now = _utc_now()
    with session_factory() as session:
        tasks = {task.task_id: task for task in session.query(TaskRecord).all()}
        resources = session.query(KpiMeasurementResource).all()
        bindings = session.query(KpiMeasurementBinding).all()
        derived_rows = session.query(KpiMeasurementDerived).all()
        maintenance_rows = session.query(KpiMetricMaintenanceConfig).all()

        resource_ids = {resource.resource_id for resource in resources}
        metric_resources = {resource.resource_id: resource for resource in resources if resource.kind == "me"}

        evidence: dict[str, set[str]] = defaultdict(set)
        for resource in resources:
            task_type = _network_type_from_task(tasks.get(resource.origin_task_id or ""))
            if task_type is not None:
                evidence[resource.resource_id].add(task_type)
        for binding in bindings:
            binding_type = _network_type_from_task(tasks.get(binding.task_id))
            if binding_type is None:
                continue
            evidence[binding.measurement_unit_id].add(binding_type)
            if binding.metric_resource_id:
                evidence[binding.metric_resource_id].add(binding_type)

        _initialize_shared_state(session, now)

        mapped_resource_count = 0
        pending_count = 0
        mapped_resource_ids: set[str] = set()
        for resource in resources:
            candidates = set(evidence.get(resource.resource_id, set()))
            network_element_type = _unique_type(candidates)
            resource_payload = _snapshot(
                resource,
                "resource_id",
                "kind",
                "name_zh",
                "name_en",
                "enabled",
                "origin_task_id",
            )
            mapping_error: str | None = None
            if network_element_type is None:
                _insert_pending(
                    session,
                    source_table=KpiMeasurementResource.__tablename__,
                    source_record_id=resource.resource_id,
                    payload=resource_payload,
                    candidates=candidates,
                    reason=_pending_reason(candidates),
                    now=now,
                )
                pending_count += 1
            else:
                try:
                    with session.begin_nested():
                        values = _resource_values(resource, network_element_type)
                        _insert_ignore(session, KpiV6MeasurementResource, values)
                        if resource.kind == "mu":
                            _insert_ignore(
                                session,
                                KpiV6MeasurementUnit,
                                _unit_values(resource, network_element_type),
                            )
                except Exception as exc:
                    mapping_error = _row_error(exc)
                    _insert_pending(
                        session,
                        source_table=KpiMeasurementResource.__tablename__,
                        source_record_id=resource.resource_id,
                        payload=resource_payload,
                        candidates=candidates,
                        reason="migration_error",
                        last_error=mapping_error,
                        now=now,
                    )
                    pending_count += 1
                else:
                    mapped_resource_count += 1
                    mapped_resource_ids.add(resource.resource_id)
            if resource.kind == "me" and not _row_enabled(resource):
                _insert_recovery_audit(
                    session,
                    source_table=KpiMeasurementResource.__tablename__,
                    source_record_id=resource.resource_id,
                    network_element_type=network_element_type,
                    measurement_unit_id=None,
                    metric_resource_id=resource.resource_id,
                    object_kind="metric",
                    before_snapshot=_snapshot(resource, "resource_id", "kind", "name_zh", "enabled"),
                    result=(
                        "failed"
                        if mapping_error is not None
                        else "recovered"
                        if network_element_type is not None
                        else "pending"
                    ),
                    error_code="migration_row_error" if mapping_error is not None else None,
                    now=now,
                )
        session.flush()

        mapped_binding_count = 0
        for binding in bindings:
            task_candidates = {
                value for value in (_network_type_from_task(tasks.get(binding.task_id)),) if value is not None
            }
            unit_candidates = set(evidence.get(binding.measurement_unit_id, set()))
            metric_candidates = (
                set(evidence.get(binding.metric_resource_id, set())) if binding.metric_resource_id else None
            )
            resource_references_mapped = binding.measurement_unit_id in mapped_resource_ids and (
                not binding.metric_resource_id or binding.metric_resource_id in mapped_resource_ids
            )
            orphan_reference = (
                binding.measurement_unit_id not in resource_ids
                or bool(binding.metric_resource_id and binding.metric_resource_id not in resource_ids)
                or (not resource_references_mapped and bool(binding.metric_resource_id))
            )
            required_sets = [task_candidates, unit_candidates]
            if metric_candidates is not None:
                required_sets.append(metric_candidates)
            non_empty = [values for values in required_sets if values]
            common_candidates = set.intersection(*non_empty) if non_empty else set()
            all_candidates = set().union(*required_sets) if required_sets else set()
            can_map = (
                all(len(values) == 1 for values in required_sets if values)
                and len(common_candidates) == 1
                and not orphan_reference
            )
            network_element_type = _unique_type(common_candidates) if can_map else None
            binding_payload = _snapshot(
                binding,
                "id",
                "measurement_unit_id",
                "metric_resource_id",
                "raw_source_name",
                "base_source_name",
                "status",
                "enabled",
                "task_id",
                "source_file",
            )
            mapping_error: str | None = None
            if network_element_type is None:
                _insert_pending(
                    session,
                    source_table=KpiMeasurementBinding.__tablename__,
                    source_record_id=binding.id,
                    payload=binding_payload,
                    candidates=all_candidates,
                    reason=_pending_reason(all_candidates, orphan_reference=orphan_reference),
                    now=now,
                )
                pending_count += 1
            else:
                try:
                    with session.begin_nested():
                        _insert_ignore(
                            session,
                            KpiV6MeasurementBinding,
                            _binding_values(binding, network_element_type),
                        )
                except Exception as exc:
                    mapping_error = _row_error(exc)
                    _insert_pending(
                        session,
                        source_table=KpiMeasurementBinding.__tablename__,
                        source_record_id=binding.id,
                        payload=binding_payload,
                        candidates=all_candidates,
                        reason="migration_error",
                        last_error=mapping_error,
                        now=now,
                    )
                    pending_count += 1
                else:
                    mapped_binding_count += 1
            if not _row_enabled(binding):
                _insert_recovery_audit(
                    session,
                    source_table=KpiMeasurementBinding.__tablename__,
                    source_record_id=binding.id,
                    network_element_type=network_element_type,
                    measurement_unit_id=binding.measurement_unit_id,
                    metric_resource_id=binding.metric_resource_id,
                    object_kind="binding",
                    before_snapshot=_snapshot(binding, "id", "measurement_unit_id", "metric_resource_id", "enabled"),
                    result=(
                        "failed"
                        if mapping_error is not None
                        else "recovered"
                        if network_element_type is not None
                        else "pending"
                    ),
                    error_code="migration_row_error" if mapping_error is not None else None,
                    now=now,
                )

        confirmed_source_identities = {
            (
                row.network_element_type,
                row.measurement_unit_id,
                row.metric_resource_id,
            )
            for row in session.query(KpiV6MeasurementBinding)
            .filter(
                KpiV6MeasurementBinding.binding_state == "confirmed",
                KpiV6MeasurementBinding.metric_resource_id.is_not(None),
            )
            .all()
        }

        mapped_derived_count = 0
        for row in derived_rows:
            unit_candidates = set(evidence.get(row.measurement_unit_id, set()))
            metric_candidates = set(evidence.get(row.metric_resource_id, set()))
            all_candidates = unit_candidates | metric_candidates
            network_element_type = (
                _unique_type(unit_candidates)
                if len(unit_candidates) == 1 and unit_candidates == metric_candidates
                else None
            )
            required_resources = {
                row.measurement_unit_id,
                row.metric_resource_id,
                row.numerator_metric_id,
                row.denominator_metric_id,
            }
            orphan_reference = not required_resources <= mapped_resource_ids
            derived_payload = _snapshot(
                row,
                "id",
                "measurement_unit_id",
                "metric_resource_id",
                "numerator_metric_id",
                "denominator_metric_id",
                "template",
                "enabled",
            )
            mapping_error: str | None = None
            source_backed_base_conflict = (
                network_element_type is not None
                and (
                    network_element_type,
                    row.measurement_unit_id,
                    row.metric_resource_id,
                )
                in confirmed_source_identities
            )
            if network_element_type is None or orphan_reference:
                _insert_pending(
                    session,
                    source_table=KpiMeasurementDerived.__tablename__,
                    source_record_id=row.id,
                    payload=derived_payload,
                    candidates=all_candidates,
                    reason=_pending_reason(all_candidates, orphan_reference=orphan_reference),
                    now=now,
                )
                pending_count += 1
            elif source_backed_base_conflict:
                _insert_recovery_audit(
                    session,
                    source_table=KpiMeasurementDerived.__tablename__,
                    source_record_id=row.id,
                    network_element_type=network_element_type,
                    measurement_unit_id=row.measurement_unit_id,
                    metric_resource_id=row.metric_resource_id,
                    object_kind="derived",
                    before_snapshot=derived_payload,
                    result="skipped",
                    error_code="source_backed_base_conflict",
                    now=now,
                )
            else:
                try:
                    with session.begin_nested():
                        _insert_ignore(
                            session,
                            KpiV6MeasurementDerived,
                            _derived_values(row, network_element_type),
                        )
                except Exception as exc:
                    mapping_error = _row_error(exc)
                    _insert_pending(
                        session,
                        source_table=KpiMeasurementDerived.__tablename__,
                        source_record_id=row.id,
                        payload=derived_payload,
                        candidates=all_candidates,
                        reason="migration_error",
                        last_error=mapping_error,
                        now=now,
                    )
                    pending_count += 1
                else:
                    mapped_derived_count += 1
            if not _row_enabled(row) and not source_backed_base_conflict:
                _insert_recovery_audit(
                    session,
                    source_table=KpiMeasurementDerived.__tablename__,
                    source_record_id=row.id,
                    network_element_type=network_element_type,
                    measurement_unit_id=row.measurement_unit_id,
                    metric_resource_id=row.metric_resource_id,
                    object_kind="derived",
                    before_snapshot=_snapshot(
                        row,
                        "id",
                        "measurement_unit_id",
                        "metric_resource_id",
                        "numerator_metric_id",
                        "denominator_metric_id",
                        "template",
                        "enabled",
                    ),
                    result=(
                        "failed"
                        if mapping_error is not None
                        else "recovered"
                        if network_element_type is not None
                        else "pending"
                    ),
                    error_code="migration_row_error" if mapping_error is not None else None,
                    now=now,
                )

        mapped_maintenance_count = 0
        for row in maintenance_rows:
            unit_candidates = set(evidence.get(row.measurement_unit_id, set()))
            metric_candidates = set(evidence.get(row.metric_resource_id, set()))
            all_candidates = unit_candidates | metric_candidates
            network_element_type = (
                _unique_type(unit_candidates)
                if len(unit_candidates) == 1 and unit_candidates == metric_candidates
                else None
            )
            orphan_reference = (
                not {
                    row.measurement_unit_id,
                    row.metric_resource_id,
                }
                <= mapped_resource_ids
            )
            maintenance_payload = _snapshot(
                row,
                "id",
                "measurement_unit_id",
                "metric_resource_id",
                "role",
                "is_percentage",
            )
            mapping_error: str | None = None
            if network_element_type is None or orphan_reference:
                _insert_pending(
                    session,
                    source_table=KpiMetricMaintenanceConfig.__tablename__,
                    source_record_id=row.id,
                    payload=maintenance_payload,
                    candidates=all_candidates,
                    reason=_pending_reason(all_candidates, orphan_reference=orphan_reference),
                    now=now,
                )
                pending_count += 1
            else:
                try:
                    with session.begin_nested():
                        _insert_ignore(
                            session,
                            KpiV6MetricMaintenanceConfig,
                            _maintenance_values(
                                row,
                                network_element_type=network_element_type,
                                metric_resource=metric_resources.get(row.metric_resource_id),
                            ),
                        )
                except Exception as exc:
                    mapping_error = _row_error(exc)
                    _insert_pending(
                        session,
                        source_table=KpiMetricMaintenanceConfig.__tablename__,
                        source_record_id=row.id,
                        payload=maintenance_payload,
                        candidates=all_candidates,
                        reason="migration_error",
                        last_error=mapping_error,
                        now=now,
                    )
                    pending_count += 1
                else:
                    mapped_maintenance_count += 1

        session.commit()
        return {
            "pending": pending_count,
            "resources": mapped_resource_count,
            "bindings": mapped_binding_count,
            "derived": mapped_derived_count,
            "maintenance": mapped_maintenance_count,
        }
