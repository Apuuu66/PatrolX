"""KPI v6 测量单元巡检范围、恢复审计与待归属维护服务。"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import kpi_v6 as schemas
from app.models.db import (
    KpiLegacyRecoveryAudit,
    KpiMaintenanceOperation,
    KpiPendingAttribution,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    session_factory,
)
from app.services.auth import AuthSession

_DISABLED_NOTICE = "只影响后续巡检，现有配置、团队关注和历史结果保留"
_PUBLIC_SCOPES = frozenset({"*", "COMMON", "PUBLIC"})
_RETRYABLE_AUDIT_RESULTS = frozenset({"pending", "failed"})
_VALID_BINDING_STATES = frozenset({"candidate", "confirmed", "conflict", "ignored"})
_VALID_RESOURCE_SOURCES = frozenset({"preset", "discovered", "manual"})
_RETRY_OPERATION_TYPE = "legacy_recovery_retry"
_RESOLVE_OPERATION_TYPE = "pending_attribution_resolve"


class KpiMeasurementScopeError(Exception):
    """测量单元范围维护业务错误；由 API 层统一映射。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MeasurementScopeItem:
    """后续任务解析使用的有效 KPI 身份。"""

    measurement_unit_id: str
    metric_resource_id: str
    metric_kind: str


@dataclass(frozen=True, slots=True)
class _UnitMetrics:
    base_metric_ids: tuple[str, ...]
    derived_metric_ids: tuple[str, ...]
    confirmed_binding_count: int
    candidate_binding_count: int
    configuration_state: schemas.KpiConfigurationState


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _validate_network_element_type(network_element_type: str) -> None:
    """v6 不存在公共范围；未知作用域按不存在处理。"""
    if not network_element_type or network_element_type in _PUBLIC_SCOPES:
        raise KpiMeasurementScopeError(
            "kpi_measurement_unit_not_found",
            "测量单元不存在",
            404,
            {"network_element_type": network_element_type},
        )


def _require_admin(actor: AuthSession) -> None:
    if actor.role != "admin":
        raise KpiMeasurementScopeError(
            "kpi_write_forbidden",
            "当前用户无 KPI 配置维护权限",
            403,
        )


def _confirmed_metric_ids(session: Session, unit: KpiV6MeasurementUnit) -> tuple[str, ...]:
    rows = (
        session.query(KpiV6MeasurementBinding.metric_resource_id)
        .filter(
            KpiV6MeasurementBinding.network_element_type == unit.network_element_type,
            KpiV6MeasurementBinding.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MeasurementBinding.binding_state == "confirmed",
            KpiV6MeasurementBinding.metric_resource_id.is_not(None),
        )
        .all()
    )
    metric_ids = sorted({str(row[0]) for row in rows if row[0]})
    if not metric_ids:
        return ()
    existing = {
        row.resource_id
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == unit.network_element_type,
            KpiV6MeasurementResource.resource_id.in_(metric_ids),
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    return tuple(metric_id for metric_id in metric_ids if metric_id in existing)


def _defined_derived_ids(
    session: Session,
    unit: KpiV6MeasurementUnit,
    *,
    confirmed_base_ids: tuple[str, ...],
) -> tuple[str, ...]:
    rows = (
        session.query(KpiV6MeasurementDerived.metric_resource_id)
        .filter(
            KpiV6MeasurementDerived.network_element_type == unit.network_element_type,
            KpiV6MeasurementDerived.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MeasurementDerived.definition_state == "defined",
        )
        .all()
    )
    metric_ids = {str(row[0]) for row in rows if row[0]}
    if not metric_ids:
        return ()
    existing = {
        row.resource_id
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == unit.network_element_type,
            KpiV6MeasurementResource.resource_id.in_(metric_ids),
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    return tuple(sorted((metric_ids & existing) - set(confirmed_base_ids)))


def _unit_metrics(session: Session, unit: KpiV6MeasurementUnit) -> _UnitMetrics:
    base_ids = _confirmed_metric_ids(session, unit)
    derived_ids = _defined_derived_ids(
        session,
        unit,
        confirmed_base_ids=base_ids,
    )
    candidate_count = (
        session.query(KpiV6MeasurementBinding)
        .filter(
            KpiV6MeasurementBinding.network_element_type == unit.network_element_type,
            KpiV6MeasurementBinding.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MeasurementBinding.binding_state == "candidate",
        )
        .count()
    )

    configs = {
        row.metric_resource_id: row.config_state
        for row in session.query(KpiV6MetricMaintenanceConfig)
        .filter(
            KpiV6MetricMaintenanceConfig.network_element_type == unit.network_element_type,
            KpiV6MetricMaintenanceConfig.measurement_unit_id == unit.measurement_unit_id,
        )
        .all()
    }
    configuration_state = (
        schemas.KpiConfigurationState.READY
        if all(configs.get(metric_id) == "ready" for metric_id in base_ids)
        else schemas.KpiConfigurationState.INCOMPLETE
    )
    return _UnitMetrics(
        base_metric_ids=base_ids,
        derived_metric_ids=derived_ids,
        confirmed_binding_count=len(base_ids),
        candidate_binding_count=candidate_count,
        configuration_state=configuration_state,
    )


def _recovery_state(
    session: Session,
    unit: KpiV6MeasurementUnit,
    base_metric_ids: tuple[str, ...],
) -> schemas.KpiRecoveryState:
    filters = [
        KpiLegacyRecoveryAudit.network_element_type == unit.network_element_type,
    ]
    identity_filter = KpiLegacyRecoveryAudit.measurement_unit_id == unit.measurement_unit_id
    if base_metric_ids:
        identity_filter = or_(
            identity_filter,
            KpiLegacyRecoveryAudit.metric_resource_id.in_(base_metric_ids),
        )
    rows = session.query(KpiLegacyRecoveryAudit.result).filter(*filters, identity_filter).all()
    results = {str(row[0]) for row in rows}
    if not results:
        return schemas.KpiRecoveryState.NONE
    if results & {"pending", "running"}:
        return schemas.KpiRecoveryState.PENDING
    if "failed" in results:
        return schemas.KpiRecoveryState.PARTIAL_FAILURE
    if results <= {"recovered", "skipped"}:
        return schemas.KpiRecoveryState.COMPLETED
    return schemas.KpiRecoveryState.NONE


def _unit_schema(session: Session, unit: KpiV6MeasurementUnit) -> schemas.KpiMeasurementUnitV6:
    metrics = _unit_metrics(session, unit)
    source = unit.source if unit.source in _VALID_RESOURCE_SOURCES else None
    return schemas.KpiMeasurementUnitV6(
        network_element_type=unit.network_element_type,
        measurement_unit_id=unit.measurement_unit_id,
        name_zh=unit.name_zh,
        name_en=unit.name_en,
        inspection_enabled=bool(unit.inspection_enabled),
        revision=unit.revision,
        base_metric_count=metrics.confirmed_binding_count,
        derived_metric_count=len(metrics.derived_metric_ids),
        confirmed_binding_count=metrics.confirmed_binding_count,
        candidate_binding_count=metrics.candidate_binding_count,
        configuration_state=metrics.configuration_state,
        recovery_state=_recovery_state(session, unit, metrics.base_metric_ids),
        source=source,
        updated_at=_iso_utc(unit.updated_at) or "",
        notice=None if unit.inspection_enabled else _DISABLED_NOTICE,
    )


def list_measurement_units(
    network_element_type: str,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    inspection_enabled: bool | None = None,
    configuration_state: schemas.KpiConfigurationState | None = None,
    recovery_state: schemas.KpiRecoveryState | None = None,
) -> schemas.KpiMeasurementUnitPageV6:
    """分页读取测量单元，并保持启停为唯一巡检门禁。"""
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        units = (
            session.query(KpiV6MeasurementUnit)
            .filter(KpiV6MeasurementUnit.network_element_type == network_element_type)
            .order_by(KpiV6MeasurementUnit.name_zh, KpiV6MeasurementUnit.measurement_unit_id)
            .all()
        )
        items = [_unit_schema(session, unit) for unit in units]

    needle = (search or "").strip().casefold()
    if needle:
        items = [
            item
            for item in items
            if needle
            in " ".join(
                (
                    item.measurement_unit_id,
                    item.name_zh,
                    item.name_en,
                )
            ).casefold()
        ]
    if inspection_enabled is not None:
        items = [item for item in items if item.inspection_enabled is inspection_enabled]
    if configuration_state is not None:
        state = schemas.KpiConfigurationState(configuration_state)
        items = [item for item in items if item.configuration_state is state]
    if recovery_state is not None:
        state = schemas.KpiRecoveryState(recovery_state)
        items = [item for item in items if item.recovery_state is state]

    total = len(items)
    offset = (page - 1) * page_size
    return schemas.KpiMeasurementUnitPageV6(
        total=total,
        page=page,
        page_size=page_size,
        items=items[offset : offset + page_size],
    )


def get_measurement_unit(
    network_element_type: str,
    measurement_unit_id: str,
) -> schemas.KpiMeasurementUnitV6:
    """按网元类型和单位 ID 读取唯一测量单元。"""
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
            )
            .one_or_none()
        )
        if unit is None:
            raise KpiMeasurementScopeError(
                "kpi_measurement_unit_not_found",
                "测量单元不存在",
                404,
                {
                    "network_element_type": network_element_type,
                    "measurement_unit_id": measurement_unit_id,
                },
            )
        return _unit_schema(session, unit)


def set_measurement_inspection_enabled(
    network_element_type: str,
    measurement_unit_id: str,
    body: schemas.KpiMeasurementInspectionPatchV6,
    *,
    actor: AuthSession,
) -> schemas.KpiMeasurementUnitV6:
    """修改唯一日常启停状态；不触碰绑定、派生、关注或历史结果。"""
    _require_admin(actor)
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(
                network_element_type=network_element_type,
                measurement_unit_id=measurement_unit_id,
            )
            .one_or_none()
        )
        if unit is None:
            raise KpiMeasurementScopeError(
                "kpi_measurement_unit_not_found",
                "测量单元不存在",
                404,
                {
                    "network_element_type": network_element_type,
                    "measurement_unit_id": measurement_unit_id,
                },
            )
        if unit.revision != body.expected_revision:
            raise KpiMeasurementScopeError(
                "kpi_measurement_unit_revision_conflict",
                "测量单元配置已更新，请刷新后重试",
                409,
                {
                    "expected_revision": body.expected_revision,
                    "current_revision": unit.revision,
                },
            )
        unit.inspection_enabled = body.inspection_enabled
        unit.revision += 1
        unit.updated_at = _utc_now()
        session.commit()
        return _unit_schema(session, unit)


def _binding_schema(
    binding: KpiV6MeasurementBinding,
    *,
    unit_name: str | None,
    metric_name: str | None,
) -> schemas.KpiMeasurementBindingV6:
    diagnostic = {
        "candidate": "绑定待人工确认",
        "conflict": "绑定存在冲突，需要单条人工修正",
        "ignored": "绑定已忽略，不进入巡检",
    }.get(binding.binding_state)
    return schemas.KpiMeasurementBindingV6(
        id=binding.id,
        network_element_type=binding.network_element_type,
        measurement_unit_id=binding.measurement_unit_id,
        measurement_unit_name=unit_name,
        raw_source_name=binding.raw_source_name,
        base_source_name=binding.base_source_name,
        metric_resource_id=binding.metric_resource_id,
        metric_resource_name=metric_name,
        display_unit=binding.display_unit,
        status=schemas.KpiBindingState(binding.binding_state),
        source_file=binding.source_file,
        origin_task_id=binding.origin_task_id,
        revision=binding.revision,
        updated_at=_iso_utc(binding.updated_at) or "",
        diagnostic=diagnostic,
    )


def list_measurement_bindings(
    network_element_type: str,
    *,
    page: int = 1,
    page_size: int = 20,
    measurement_unit_id: str | None = None,
    status: schemas.KpiBindingState | None = None,
    search: str | None = None,
) -> schemas.KpiMeasurementBindingPageV6:
    """分页读取绑定诊断；不提供批量确认语义。"""
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        query = session.query(KpiV6MeasurementBinding).filter(
            KpiV6MeasurementBinding.network_element_type == network_element_type
        )
        if measurement_unit_id:
            query = query.filter(KpiV6MeasurementBinding.measurement_unit_id == measurement_unit_id)
        if status is not None:
            query = query.filter(KpiV6MeasurementBinding.binding_state == schemas.KpiBindingState(status).value)
        bindings = query.order_by(
            KpiV6MeasurementBinding.updated_at.desc(),
            KpiV6MeasurementBinding.id.desc(),
        ).all()
        unit_names = {
            row.measurement_unit_id: row.name_zh
            for row in session.query(KpiV6MeasurementUnit)
            .filter(KpiV6MeasurementUnit.network_element_type == network_element_type)
            .all()
        }
        metric_names = {
            row.resource_id: row.name_zh
            for row in session.query(KpiV6MeasurementResource)
            .filter(
                KpiV6MeasurementResource.network_element_type == network_element_type,
                KpiV6MeasurementResource.kind == "me",
            )
            .all()
        }
        items = [
            _binding_schema(
                binding,
                unit_name=unit_names.get(binding.measurement_unit_id),
                metric_name=metric_names.get(binding.metric_resource_id or ""),
            )
            for binding in bindings
        ]

    needle = (search or "").strip().casefold()
    if needle:
        items = [
            item
            for item in items
            if needle
            in " ".join(
                value
                for value in (
                    item.raw_source_name,
                    item.base_source_name,
                    item.metric_resource_id,
                    item.metric_resource_name,
                    item.measurement_unit_id,
                    item.measurement_unit_name,
                    item.source_file,
                    item.origin_task_id,
                )
                if value
            ).casefold()
        ]
    total = len(items)
    offset = (page - 1) * page_size
    return schemas.KpiMeasurementBindingPageV6(
        total=total,
        page=page,
        page_size=page_size,
        items=items[offset : offset + page_size],
    )


def correct_measurement_binding(
    network_element_type: str,
    binding_id: int,
    body: schemas.KpiMeasurementBindingPatchV6,
    *,
    actor: AuthSession,
) -> schemas.KpiMeasurementBindingV6:
    """单条修正 candidate/conflict 绑定；已确认和已忽略项不可再改。"""
    _require_admin(actor)
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        binding = (
            session.query(KpiV6MeasurementBinding)
            .filter_by(id=binding_id, network_element_type=network_element_type)
            .one_or_none()
        )
        if binding is None:
            raise KpiMeasurementScopeError(
                "kpi_binding_not_found",
                "绑定不存在",
                404,
                {"network_element_type": network_element_type, "binding_id": binding_id},
            )
        if binding.revision != body.expected_revision:
            raise KpiMeasurementScopeError(
                "kpi_measurement_binding_revision_conflict",
                "绑定配置已更新，请刷新后重试",
                409,
                {
                    "expected_revision": body.expected_revision,
                    "current_revision": binding.revision,
                },
            )
        if binding.binding_state not in {"candidate", "conflict"}:
            raise KpiMeasurementScopeError(
                "kpi_binding_not_correctable",
                "仅 candidate 或 conflict 绑定可执行单条人工修正",
                400,
            )

        binding.binding_state = body.status
        binding.revision += 1
        binding.updated_at = _utc_now()
        session.commit()

        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(
                network_element_type=network_element_type,
                measurement_unit_id=binding.measurement_unit_id,
            )
            .one_or_none()
        )
        resource = (
            session.query(KpiV6MeasurementResource)
            .filter_by(
                network_element_type=network_element_type,
                resource_id=binding.metric_resource_id,
                kind="me",
            )
            .one_or_none()
            if binding.metric_resource_id
            else None
        )
        return _binding_schema(
            binding,
            unit_name=unit.name_zh if unit else None,
            metric_name=resource.name_zh if resource else None,
        )


def _audit_schema(audit: KpiLegacyRecoveryAudit) -> schemas.KpiLegacyRecoveryAuditV6:
    return schemas.KpiLegacyRecoveryAuditV6(
        audit_id=audit.id,
        source_table=audit.source_table,
        source_record_id=audit.source_record_id,
        source_key=audit.source_key,
        network_element_type=audit.network_element_type,
        measurement_unit_id=audit.measurement_unit_id,
        metric_resource_id=audit.metric_resource_id,
        object_kind=schemas.KpiRecoveryObjectKind(audit.object_kind),
        before_snapshot=audit.before_snapshot,
        result=schemas.KpiRecoveryResult(audit.result),
        error_code=audit.error_code,
        error_message=None,
        attempt_count=audit.attempt_count,
        actor=audit.actor,
        source=schemas.KpiRecoverySource(audit.source),
        created_at=_iso_utc(audit.created_at) or "",
        updated_at=_iso_utc(audit.updated_at) or "",
    )


def list_legacy_recovery_audits(
    *,
    page: int = 1,
    page_size: int = 20,
    network_element_type: str | None = None,
    result: schemas.KpiRecoveryResult | None = None,
    object_kind: schemas.KpiRecoveryObjectKind | None = None,
    measurement_unit_id: str | None = None,
) -> schemas.KpiLegacyRecoveryAuditPageV6:
    """分页查询历史指标级停用恢复审计。"""
    if network_element_type:
        _validate_network_element_type(network_element_type)
    with session_factory() as session:
        query = session.query(KpiLegacyRecoveryAudit)
        if network_element_type:
            query = query.filter(KpiLegacyRecoveryAudit.network_element_type == network_element_type)
        if result is not None:
            query = query.filter(KpiLegacyRecoveryAudit.result == schemas.KpiRecoveryResult(result).value)
        if object_kind is not None:
            query = query.filter(KpiLegacyRecoveryAudit.object_kind == schemas.KpiRecoveryObjectKind(object_kind).value)
        if measurement_unit_id:
            query = query.filter(KpiLegacyRecoveryAudit.measurement_unit_id == measurement_unit_id)
        total = query.count()
        rows = (
            query.order_by(
                KpiLegacyRecoveryAudit.created_at.desc(),
                KpiLegacyRecoveryAudit.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return schemas.KpiLegacyRecoveryAuditPageV6(
            total=total,
            page=page,
            page_size=page_size,
            items=[_audit_schema(row) for row in rows],
        )


def _fingerprint(operation_type: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        {"operation_type": operation_type, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _operation_schema(operation: KpiMaintenanceOperation) -> schemas.KpiMaintenanceOperationV6:
    return schemas.KpiMaintenanceOperationV6(
        operation_id=operation.operation_id,
        operation_type=operation.operation_type,
        status=operation.status,
        idempotency_key=operation.idempotency_key,
        total_count=operation.total_count,
        succeeded_count=operation.succeeded_count,
        failed_count=operation.failed_count,
        pending_count=operation.pending_count,
        items=[schemas.KpiMaintenanceOperationItemV6(**item) for item in operation.items],
        created_at=_iso_utc(operation.created_at) or "",
        completed_at=_iso_utc(operation.completed_at),
    )


def _accepted(operation_id: str) -> schemas.KpiMaintenanceOperationAcceptedV6:
    return schemas.KpiMaintenanceOperationAcceptedV6(
        operation_id=operation_id,
        status="queued",
    )


def _existing_operation(
    session: Session,
    *,
    operation_type: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
) -> KpiMaintenanceOperation | None:
    operation = session.query(KpiMaintenanceOperation).filter_by(idempotency_key=idempotency_key).one_or_none()
    if operation is None:
        return None
    fingerprint = _fingerprint(operation_type, request_payload)
    if operation.operation_type != operation_type or operation.request_fingerprint != fingerprint:
        raise KpiMeasurementScopeError(
            "kpi_maintenance_operation_idempotency_conflict",
            "幂等键已用于不同维护请求",
            409,
            {
                "idempotency_key": idempotency_key,
                "existing_operation_id": operation.operation_id,
            },
        )
    return operation


def _create_operation(
    *,
    operation_type: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    target_ids: list[str],
    actor: AuthSession,
) -> str:
    with session_factory() as session:
        existing = _existing_operation(
            session,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        if existing is not None:
            return existing.operation_id
        now = _utc_now()
        operation = KpiMaintenanceOperation(
            operation_id=f"kop_{uuid.uuid4().hex}",
            operation_type=operation_type,
            status="queued",
            idempotency_key=idempotency_key,
            request_fingerprint=_fingerprint(operation_type, request_payload),
            request_payload=request_payload,
            total_count=len(target_ids),
            succeeded_count=0,
            failed_count=0,
            pending_count=len(target_ids),
            items=[{"target_id": target_id, "result": "pending"} for target_id in target_ids],
            actor=actor.username,
            created_at=now,
            completed_at=None,
        )
        session.add(operation)
        session.commit()
        return operation.operation_id


def _finish_operation(
    operation_id: str,
    *,
    items: list[dict[str, Any]],
) -> None:
    succeeded = sum(1 for item in items if item["result"] == "succeeded")
    failed = sum(1 for item in items if item["result"] == "failed")
    pending = sum(1 for item in items if item["result"] in {"pending", "running"})
    status = (
        "succeeded"
        if pending == 0 and failed == 0
        else "failed"
        if pending == 0 and succeeded == 0
        else "partial_success"
        if pending == 0
        else "running"
    )
    with session_factory() as session:
        operation = session.get(KpiMaintenanceOperation, operation_id)
        if operation is None:
            return
        operation.status = status
        operation.succeeded_count = succeeded
        operation.failed_count = failed
        operation.pending_count = pending
        operation.items = items
        operation.completed_at = _utc_now() if pending == 0 else None
        session.commit()


def retry_legacy_recovery(
    body: schemas.KpiLegacyRecoveryRetryRequestV6,
    *,
    actor: AuthSession,
) -> schemas.KpiMaintenanceOperationAcceptedV6:
    """逐对象恢复历史停用语义；成功后返回幂等 operation。"""
    _require_admin(actor)
    request_payload = {
        "audit_ids": sorted(body.audit_ids),
        "idempotency_key": body.idempotency_key,
    }
    operation_id = _create_operation(
        operation_type=_RETRY_OPERATION_TYPE,
        idempotency_key=body.idempotency_key,
        request_payload=request_payload,
        target_ids=[str(audit_id) for audit_id in body.audit_ids],
        actor=actor,
    )

    with session_factory() as session:
        operation = session.get(KpiMaintenanceOperation, operation_id)
        if operation is None:
            raise KpiMeasurementScopeError(
                "kpi_maintenance_operation_not_found",
                "维护操作不存在",
                404,
            )
        if operation.status not in {"queued", "running"}:
            return _accepted(operation_id)
        audits = {
            audit.id: audit
            for audit in session.query(KpiLegacyRecoveryAudit)
            .filter(KpiLegacyRecoveryAudit.id.in_(body.audit_ids))
            .all()
        }
        invalid_ids = [
            audit_id
            for audit_id in body.audit_ids
            if audit_id not in audits or audits[audit_id].result not in _RETRYABLE_AUDIT_RESULTS
        ]
        if invalid_ids:
            session.delete(operation)
            session.commit()
            raise KpiMeasurementScopeError(
                "kpi_maintenance_target_invalid",
                "仅 failed 或 pending 的恢复审计可重试",
                400,
                {"invalid_audit_ids": invalid_ids},
            )

        operation.status = "running"
        session.commit()

    items: list[dict[str, Any]] = []
    for audit_id in body.audit_ids:
        with session_factory() as session:
            audit = session.get(KpiLegacyRecoveryAudit, audit_id)
            if audit is None:
                items.append(
                    {
                        "target_id": str(audit_id),
                        "result": "failed",
                        "error_code": "kpi_maintenance_target_invalid",
                        "error_message": "恢复审计不存在",
                    }
                )
                continue
            audit.attempt_count += 1
            audit.actor = actor.username
            audit.source = "api"
            audit.updated_at = _utc_now()
            if not audit.network_element_type:
                audit.result = "failed"
                audit.error_code = "kpi_recovery_network_element_type_missing"
                items.append(
                    {
                        "target_id": str(audit_id),
                        "result": "failed",
                        "error_code": audit.error_code,
                        "error_message": "恢复对象缺少网元类型",
                    }
                )
            elif audit.network_element_type in _PUBLIC_SCOPES:
                audit.result = "failed"
                audit.error_code = "kpi_recovery_network_element_type_invalid"
                items.append(
                    {
                        "target_id": str(audit_id),
                        "result": "failed",
                        "error_code": audit.error_code,
                        "error_message": "v6 不允许公共巡检范围",
                    }
                )
            else:
                audit.result = "recovered"
                audit.error_code = None
                items.append(
                    {
                        "target_id": str(audit_id),
                        "result": "succeeded",
                    }
                )
            session.commit()

    _finish_operation(operation_id, items=items)
    return _accepted(operation_id)


def _pending_schema(row: KpiPendingAttribution) -> schemas.KpiPendingAttributionV6:
    return schemas.KpiPendingAttributionV6(
        pending_id=row.id,
        source_table=row.source_table,
        source_record_id=row.source_record_id,
        source_key=row.source_key,
        source_payload=row.source_payload,
        candidate_network_element_types=[str(value) for value in (row.candidate_network_element_types or [])],
        reason=schemas.KpiPendingReason(row.reason),
        resolution_state=schemas.KpiPendingResolutionState(row.resolution_state),
        assigned_network_element_type=row.assigned_network_element_type,
        attempt_count=row.attempt_count,
        last_error=row.last_error,
        idempotency_key=row.idempotency_key,
        created_at=_iso_utc(row.created_at) or "",
        updated_at=_iso_utc(row.updated_at) or "",
    )


def list_pending_attributions(
    *,
    page: int = 1,
    page_size: int = 20,
    resolution_state: schemas.KpiPendingResolutionState | None = None,
    reason: schemas.KpiPendingReason | None = None,
    source_table: str | None = None,
) -> schemas.KpiPendingAttributionPageV6:
    """分页读取待归属配置；未完成项不进入任何巡检范围。"""
    with session_factory() as session:
        query = session.query(KpiPendingAttribution)
        if resolution_state is not None:
            query = query.filter(
                KpiPendingAttribution.resolution_state == schemas.KpiPendingResolutionState(resolution_state).value
            )
        if reason is not None:
            query = query.filter(KpiPendingAttribution.reason == schemas.KpiPendingReason(reason).value)
        if source_table:
            query = query.filter(KpiPendingAttribution.source_table == source_table)
        total = query.count()
        rows = (
            query.order_by(
                KpiPendingAttribution.created_at.desc(),
                KpiPendingAttribution.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return schemas.KpiPendingAttributionPageV6(
            total=total,
            page=page,
            page_size=page_size,
            items=[_pending_schema(row) for row in rows],
        )


def _payload_time(payload: dict[str, Any]) -> datetime:
    value = payload.get("created_at")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return _utc_now()


def _materialize_resource(
    session: Session,
    *,
    network_element_type: str,
    payload: dict[str, Any],
    source_key: str,
) -> int:
    resource_id = str(payload.get("resource_id") or "").strip()
    kind = str(payload.get("kind") or "").strip()
    name_zh = str(payload.get("name_zh") or "").strip()
    name_en = str(payload.get("name_en") or "").strip()
    if not resource_id or kind not in {"mu", "me", "unit"} or not name_zh or not name_en:
        raise ValueError("资源快照缺少可物化字段")
    if (
        not session.query(KpiV6MeasurementResource)
        .filter_by(
            network_element_type=network_element_type,
            resource_id=resource_id,
        )
        .one_or_none()
    ):
        now = _utc_now()
        source = str(payload.get("source") or "discovered")
        if source not in _VALID_RESOURCE_SOURCES:
            source = "discovered"
        session.add(
            KpiV6MeasurementResource(
                network_element_type=network_element_type,
                resource_id=resource_id,
                kind=kind,
                name_zh=name_zh,
                name_en=name_en,
                filename_fragment=payload.get("filename_fragment"),
                display_order=payload.get("display_order"),
                metric_group=payload.get("metric_group"),
                direction=payload.get("direction"),
                importance=payload.get("importance"),
                warning_threshold=payload.get("warning_threshold"),
                critical_threshold=payload.get("critical_threshold"),
                source=source,
                origin_task_id=payload.get("origin_task_id"),
                origin_file=payload.get("origin_file"),
                legacy_source_key=source_key,
                created_at=now,
                updated_at=now,
            )
        )
    if (
        kind == "mu"
        and not session.query(KpiV6MeasurementUnit)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=resource_id,
        )
        .one_or_none()
    ):
        now = _utc_now()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "network_element_type": network_element_type,
                    "measurement_unit_id": resource_id,
                    "name_zh": name_zh,
                    "name_en": name_en,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        session.add(
            KpiV6MeasurementUnit(
                network_element_type=network_element_type,
                measurement_unit_id=resource_id,
                name_zh=name_zh,
                name_en=name_en,
                inspection_enabled=bool(payload.get("enabled", True)),
                revision=0,
                config_fingerprint=fingerprint,
                source=str(payload.get("source") or "discovered"),
                origin_task_id=payload.get("origin_task_id"),
                legacy_source_key=source_key,
                created_at=now,
                updated_at=now,
            )
        )
    return 1


def _materialize_binding(
    session: Session,
    *,
    network_element_type: str,
    payload: dict[str, Any],
    source_key: str,
) -> int:
    measurement_unit_id = str(payload.get("measurement_unit_id") or "").strip()
    raw_source_name = str(payload.get("raw_source_name") or "").strip()
    metric_resource_id = payload.get("metric_resource_id")
    if not measurement_unit_id or not raw_source_name:
        raise ValueError("绑定快照缺少可物化字段")
    if (
        not session.query(KpiV6MeasurementUnit)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
        )
        .one_or_none()
    ):
        raise LookupError(f"测量单元尚未归属: {measurement_unit_id}")
    existing = (
        session.query(KpiV6MeasurementBinding)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            raw_source_name=raw_source_name,
        )
        .one_or_none()
    )
    if existing is not None:
        return 1
    status = str(payload.get("status") or "candidate")
    if status not in _VALID_BINDING_STATES:
        status = "candidate"
    now = _utc_now()
    session.add(
        KpiV6MeasurementBinding(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            raw_source_name=raw_source_name,
            base_source_name=str(payload.get("base_source_name") or raw_source_name),
            metric_resource_id=str(metric_resource_id) if metric_resource_id else None,
            display_unit=payload.get("display_unit"),
            binding_state=status,
            source_file=str(payload.get("source_file") or ""),
            origin_task_id=str(payload.get("task_id") or payload.get("origin_task_id") or ""),
            revision=0,
            legacy_source_key=source_key,
            created_at=now,
            updated_at=now,
        )
    )
    return 1


def _materialize_derived(
    session: Session,
    *,
    network_element_type: str,
    payload: dict[str, Any],
    source_key: str,
) -> int:
    measurement_unit_id = str(payload.get("measurement_unit_id") or "").strip()
    metric_resource_id = str(payload.get("metric_resource_id") or "").strip()
    numerator = str(payload.get("numerator_metric_id") or "").strip()
    denominator = str(payload.get("denominator_metric_id") or "").strip()
    template = str(payload.get("template") or "").strip()
    if not all((measurement_unit_id, metric_resource_id, numerator, denominator, template)):
        raise ValueError("派生快照缺少可物化字段")
    confirmed_base = (
        session.query(KpiV6MeasurementBinding.id)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            binding_state="confirmed",
        )
        .first()
    )
    if confirmed_base is not None:
        raise ValueError("派生指标不能覆盖已确认的源包指标")
    required = {measurement_unit_id, metric_resource_id, numerator, denominator}
    available = {
        row.resource_id
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == network_element_type,
            KpiV6MeasurementResource.resource_id.in_(required),
        )
        .all()
    }
    if required != available:
        raise LookupError("派生指标引用的资源尚未归属")
    existing = (
        session.query(KpiV6MeasurementDerived)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return 1
    now = _utc_now()
    session.add(
        KpiV6MeasurementDerived(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            numerator_metric_id=numerator,
            denominator_metric_id=denominator,
            template=template,
            definition_state="defined",
            revision=0,
            legacy_source_key=source_key,
            created_at=now,
            updated_at=now,
        )
    )
    return 1


def _materialize_maintenance(
    session: Session,
    *,
    network_element_type: str,
    payload: dict[str, Any],
    source_key: str,
) -> int:
    measurement_unit_id = str(payload.get("measurement_unit_id") or "").strip()
    metric_resource_id = str(payload.get("metric_resource_id") or "").strip()
    if not measurement_unit_id or not metric_resource_id:
        raise ValueError("维护配置快照缺少可物化字段")
    resource = (
        session.query(KpiV6MeasurementResource)
        .filter_by(
            network_element_type=network_element_type,
            resource_id=metric_resource_id,
            kind="me",
        )
        .one_or_none()
    )
    if resource is None:
        raise LookupError(f"指标资源尚未归属: {metric_resource_id}")
    existing = (
        session.query(KpiV6MetricMaintenanceConfig)
        .filter_by(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return 1
    now = _utc_now()
    session.add(
        KpiV6MetricMaintenanceConfig(
            network_element_type=network_element_type,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            role=str(payload.get("role") or "base"),
            direction=resource.direction,
            warning_threshold=resource.warning_threshold,
            critical_threshold=resource.critical_threshold,
            daily_aggregation=str(payload.get("daily_aggregation") or "latest"),
            daily_change_threshold=payload.get("daily_change_threshold"),
            daily_change_threshold_unit=str(payload.get("daily_change_threshold_unit") or "auto"),
            is_percentage=bool(payload.get("is_percentage", False)),
            zero_semantics=str(payload.get("zero_semantics") or "unknown"),
            consistency_tolerance=float(payload.get("consistency_tolerance", 0.2)),
            object_match_mode=str(payload.get("object_match_mode") or "exact"),
            config_state="ready",
            revision=0,
            legacy_source_key=source_key,
            created_at=now,
            updated_at=now,
        )
    )
    return 1


def _materialize_pending(session: Session, pending: KpiPendingAttribution) -> None:
    network_element_type = str(pending.assigned_network_element_type or "")
    payload = dict(pending.source_payload or {})
    materializers = {
        "kpi_measurement_resources": _materialize_resource,
        "kpi_measurement_bindings": _materialize_binding,
        "kpi_measurement_derived": _materialize_derived,
        "kpi_metric_maintenance_configs": _materialize_maintenance,
    }
    materializer = materializers.get(pending.source_table)
    if materializer is None:
        raise ValueError(f"不支持的待归属来源: {pending.source_table}")
    materializer(
        session,
        network_element_type=network_element_type,
        payload=payload,
        source_key=pending.source_key,
    )


def resolve_pending_attribution(
    pending_id: int,
    body: schemas.KpiPendingAttributionResolveRequestV6,
    *,
    actor: AuthSession,
) -> schemas.KpiMaintenanceOperationAcceptedV6:
    """显式指定网元类型并物化一个待归属对象。"""
    _require_admin(actor)
    request_payload = {
        "pending_id": pending_id,
        "network_element_type": body.network_element_type,
        "idempotency_key": body.idempotency_key,
    }
    operation_id = _create_operation(
        operation_type=_RESOLVE_OPERATION_TYPE,
        idempotency_key=body.idempotency_key,
        request_payload=request_payload,
        target_ids=[str(pending_id)],
        actor=actor,
    )

    with session_factory() as session:
        operation = session.get(KpiMaintenanceOperation, operation_id)
        if operation is None:
            raise KpiMeasurementScopeError(
                "kpi_maintenance_operation_not_found",
                "维护操作不存在",
                404,
            )
        if operation.status not in {"queued", "running"}:
            return _accepted(operation_id)
        pending = session.get(KpiPendingAttribution, pending_id)
        if pending is None:
            session.delete(operation)
            session.commit()
            raise KpiMeasurementScopeError(
                "kpi_pending_attribution_not_found",
                "待归属记录不存在",
                404,
                {"pending_id": pending_id},
            )
        if pending.resolution_state not in {"pending", "failed", "assigned"}:
            session.delete(operation)
            session.commit()
            raise KpiMeasurementScopeError(
                "kpi_maintenance_target_invalid",
                "仅待处理、失败或已分配未物化的待归属记录可处理",
                400,
                {"pending_id": pending_id},
            )
        pending.resolution_state = "assigned"
        pending.assigned_network_element_type = body.network_element_type
        pending.attempt_count += 1
        pending.last_error = None
        pending.updated_at = _utc_now()
        operation.status = "running"
        session.commit()

    item: dict[str, Any]
    with session_factory() as session:
        pending = session.get(KpiPendingAttribution, pending_id)
        if pending is None:
            item = {
                "target_id": str(pending_id),
                "result": "failed",
                "error_code": "kpi_pending_attribution_not_found",
                "error_message": "待归属记录不存在",
            }
        else:
            try:
                _materialize_pending(session, pending)
                pending.resolution_state = "materialized"
                pending.last_error = None
                pending.updated_at = _utc_now()
                session.commit()
                item = {"target_id": str(pending_id), "result": "succeeded"}
            except (LookupError, ValueError) as exc:
                session.rollback()
                pending = session.get(KpiPendingAttribution, pending_id)
                if pending is None:
                    item = {
                        "target_id": str(pending_id),
                        "result": "failed",
                        "error_code": "kpi_pending_attribution_not_found",
                        "error_message": "待归属记录不存在",
                    }
                else:
                    pending.resolution_state = "failed"
                    pending.last_error = str(exc)
                    pending.updated_at = _utc_now()
                    session.commit()
                    item = {
                        "target_id": str(pending_id),
                        "result": "failed",
                        "error_code": "kpi_pending_materialization_failed",
                        "error_message": str(exc),
                    }
            except Exception as exc:  # pragma: no cover - 数据库异常防御性兜底
                session.rollback()
                pending = session.get(KpiPendingAttribution, pending_id)
                if pending is not None:
                    pending.resolution_state = "failed"
                    pending.last_error = f"{type(exc).__name__}: {exc}"
                    pending.updated_at = _utc_now()
                    session.commit()
                item = {
                    "target_id": str(pending_id),
                    "result": "failed",
                    "error_code": "kpi_pending_materialization_failed",
                    "error_message": str(exc),
                }

    _finish_operation(operation_id, items=[item])
    return _accepted(operation_id)


def get_maintenance_operation(operation_id: str) -> schemas.KpiMaintenanceOperationV6:
    """读取恢复或归属操作进度及逐项结果。"""
    with session_factory() as session:
        operation = session.get(KpiMaintenanceOperation, operation_id)
        if operation is None:
            raise KpiMeasurementScopeError(
                "kpi_maintenance_operation_not_found",
                "维护操作不存在",
                404,
                {"operation_id": operation_id},
            )
        return _operation_schema(operation)


def resolve_measurement_scope(network_element_type: str) -> list[MeasurementScopeItem]:
    """解析当前启用单位下的全部已确认基础指标与已定义派生指标。"""
    _validate_network_element_type(network_element_type)
    with session_factory() as session:
        units = (
            session.query(KpiV6MeasurementUnit)
            .filter(
                KpiV6MeasurementUnit.network_element_type == network_element_type,
                KpiV6MeasurementUnit.inspection_enabled.is_(True),
            )
            .order_by(
                KpiV6MeasurementUnit.name_zh,
                KpiV6MeasurementUnit.measurement_unit_id,
            )
            .all()
        )
        items: list[MeasurementScopeItem] = []
        for unit in units:
            metrics = _unit_metrics(session, unit)
            items.extend(
                MeasurementScopeItem(
                    measurement_unit_id=unit.measurement_unit_id,
                    metric_resource_id=metric_id,
                    metric_kind="base",
                )
                for metric_id in metrics.base_metric_ids
            )
            items.extend(
                MeasurementScopeItem(
                    measurement_unit_id=unit.measurement_unit_id,
                    metric_resource_id=metric_id,
                    metric_kind="derived",
                )
                for metric_id in metrics.derived_metric_ids
            )
        return items
