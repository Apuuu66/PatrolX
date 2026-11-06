"""v6 团队关注的共享读取与原子差异写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import kpi_v6 as schemas
from app.models.db import (
    KpiTeamFocusItem,
    KpiTeamFocusRevision,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    TaskKpiScopeItem,
    TaskKpiScopeSnapshot,
    TaskRecord,
    session_factory,
)
from app.services.auth import AuthSession


class KpiTeamFocusError(Exception):
    """团队关注业务错误；由路由层映射为统一 API 错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        detail: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _FocusContext:
    snapshot: TaskKpiScopeSnapshot
    scope_keys: frozenset[tuple[str, str]]
    units: dict[str, KpiV6MeasurementUnit]
    resources: dict[str, KpiV6MeasurementResource]


def _iso_utc(value: datetime) -> str:
    """SQLite 可能返回无时区时间；统一按 UTC 输出。"""
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _focus_context(session: Session, network_element_type: str, task_id: str) -> _FocusContext:
    """校验任务与网元类型，并读取可用性判断所需的冻结范围。"""
    task = session.get(TaskRecord, task_id)
    if task is None:
        raise KpiTeamFocusError("task_not_found", f"任务不存在: {task_id}", 404)

    snapshot = session.get(TaskKpiScopeSnapshot, task_id)
    if snapshot is None:
        raise KpiTeamFocusError(
            "task_result_requires_rebuild",
            "旧任务结果需要按当前规则和配置重建",
            409,
            {"task_id": task_id, "action": "rebuild_full"},
        )
    if snapshot.network_element_type != network_element_type:
        raise KpiTeamFocusError(
            "cross_network_element_scope",
            "任务与请求的网元类型不一致",
            400,
            {
                "task_id": task_id,
                "task_network_element_type": snapshot.network_element_type,
                "network_element_type": network_element_type,
            },
        )

    scope_rows = (
        session.query(TaskKpiScopeItem)
        .filter(
            TaskKpiScopeItem.task_id == task_id,
            TaskKpiScopeItem.network_element_type == network_element_type,
        )
        .all()
    )
    units = {
        row.measurement_unit_id: row
        for row in session.query(KpiV6MeasurementUnit)
        .filter(KpiV6MeasurementUnit.network_element_type == network_element_type)
        .all()
    }
    resources = {
        row.resource_id: row
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == network_element_type,
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    return _FocusContext(
        snapshot=snapshot,
        scope_keys=frozenset((row.measurement_unit_id, row.metric_resource_id) for row in scope_rows),
        units=units,
        resources=resources,
    )


def _availability(
    context: _FocusContext,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> tuple[schemas.FocusAvailability, schemas.FocusAvailabilityReason | None]:
    unit = context.units.get(measurement_unit_id)
    if unit is None or not unit.inspection_enabled:
        return (
            schemas.FocusAvailability.UNAVAILABLE,
            schemas.FocusAvailabilityReason.MEASUREMENT_UNIT_DISABLED,
        )
    if (measurement_unit_id, metric_resource_id) not in context.scope_keys:
        return (
            schemas.FocusAvailability.UNAVAILABLE,
            schemas.FocusAvailabilityReason.NOT_IN_TASK_SCOPE,
        )
    return schemas.FocusAvailability.AVAILABLE, None


def _focus_item(context: _FocusContext, row: KpiTeamFocusItem) -> schemas.KpiTeamFocusItemV6:
    unit = context.units.get(row.measurement_unit_id)
    resource = context.resources.get(row.metric_resource_id)
    availability, reason = _availability(
        context,
        row.measurement_unit_id,
        row.metric_resource_id,
    )
    return schemas.KpiTeamFocusItemV6(
        network_element_type=row.network_element_type,
        measurement_unit_id=row.measurement_unit_id,
        measurement_unit_name=(unit.name_zh if unit is not None and unit.name_zh.strip() else row.measurement_unit_id),
        metric_resource_id=row.metric_resource_id,
        metric_name=(resource.name_zh if resource is not None and resource.name_zh.strip() else row.metric_resource_id),
        availability=availability,
        availability_reason=reason,
        added_by=row.added_by,
        added_at=_iso_utc(row.added_at),
    )


def _focus_rows(session: Session, network_element_type: str) -> list[KpiTeamFocusItem]:
    return (
        session.query(KpiTeamFocusItem)
        .filter(KpiTeamFocusItem.network_element_type == network_element_type)
        .order_by(
            KpiTeamFocusItem.measurement_unit_id,
            KpiTeamFocusItem.metric_resource_id,
        )
        .all()
    )


def _revision(session: Session, network_element_type: str) -> int:
    revision = session.get(KpiTeamFocusRevision, network_element_type)
    return revision.revision if revision is not None else 0


def _counts(
    context: _FocusContext,
    rows: list[KpiTeamFocusItem],
) -> tuple[int, int]:
    available = 0
    for row in rows:
        availability, _ = _availability(context, row.measurement_unit_id, row.metric_resource_id)
        if availability == schemas.FocusAvailability.AVAILABLE:
            available += 1
    return available, len(rows) - available


def _validate_patch(body: schemas.KpiTeamFocusPatchRequestV6) -> None:
    """服务层再次校验，避免绕过请求模型时出现部分写入。"""
    add_keys = [(item.measurement_unit_id, item.metric_resource_id) for item in body.add]
    remove_keys = [(item.measurement_unit_id, item.metric_resource_id) for item in body.remove]
    if not add_keys and not remove_keys:
        raise KpiTeamFocusError(
            "team_focus_operation_empty",
            "至少需要加入或移出一个关注项",
            400,
        )
    if len(add_keys) != len(set(add_keys)) or len(remove_keys) != len(set(remove_keys)):
        raise KpiTeamFocusError(
            "team_focus_identity_duplicate",
            "add/remove 数组内身份必须唯一",
            400,
        )
    if set(add_keys) & set(remove_keys):
        raise KpiTeamFocusError(
            "team_focus_add_remove_overlap",
            "同一身份不能同时加入和移出",
            400,
        )


def list_team_focus(
    network_element_type: str,
    *,
    task_id: str,
    actor: AuthSession,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    measurement_unit_id: str | None = None,
    availability: schemas.FocusAvailability | None = None,
) -> schemas.KpiTeamFocusPageV6:
    """读取共享关注，并按当前任务冻结范围计算可用性。"""
    with session_factory() as session:
        context = _focus_context(session, network_element_type, task_id)
        rows = _focus_rows(session, network_element_type)
        items = [_focus_item(context, row) for row in rows]
        available_count, unavailable_count = _counts(context, rows)

        if search and search.strip():
            needle = search.strip().casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    (
                        item.measurement_unit_id,
                        item.measurement_unit_name,
                        item.metric_resource_id,
                        item.metric_name,
                    )
                ).casefold()
            ]
        if measurement_unit_id is not None:
            items = [item for item in items if item.measurement_unit_id == measurement_unit_id]
        if availability is not None:
            items = [item for item in items if item.availability == availability]

        total = len(items)
        offset = (page - 1) * page_size
        return schemas.KpiTeamFocusPageV6(
            network_element_type=network_element_type,
            revision=_revision(session, network_element_type),
            page=page,
            page_size=page_size,
            total=total,
            available_count=available_count,
            unavailable_count=unavailable_count,
            items=items[offset : offset + page_size],
            can_write=actor.role == "admin",
        )


def patch_team_focus(
    network_element_type: str,
    body: schemas.KpiTeamFocusPatchRequestV6,
    *,
    actor: AuthSession,
) -> schemas.KpiTeamFocusPatchResponseV6:
    """在一个事务内应用关注差异，只写关注项与 revision。"""
    if actor.role != "admin":
        raise KpiTeamFocusError(
            "kpi_write_forbidden",
            "当前用户无团队关注维护权限",
            403,
        )
    _validate_patch(body)

    with session_factory() as session:
        context = _focus_context(session, network_element_type, body.task_id)
        revision = session.get(KpiTeamFocusRevision, network_element_type)
        current_revision = revision.revision if revision is not None else 0
        if body.expected_revision != current_revision:
            raise KpiTeamFocusError(
                "team_focus_revision_conflict",
                "团队关注已被其他维护人员更新，请刷新后重试",
                409,
                {
                    "network_element_type": network_element_type,
                    "expected_revision": body.expected_revision,
                    "current_revision": current_revision,
                },
            )

        for identity in body.add:
            unit = context.units.get(identity.measurement_unit_id)
            if (
                (identity.measurement_unit_id, identity.metric_resource_id) not in context.scope_keys
                or unit is None
                or not unit.inspection_enabled
            ):
                raise KpiTeamFocusError(
                    "team_focus_item_not_available",
                    "指标不属于当前任务可关注范围",
                    400,
                    {
                        "measurement_unit_id": identity.measurement_unit_id,
                        "metric_resource_id": identity.metric_resource_id,
                    },
                )

        existing = {
            (row.measurement_unit_id, row.metric_resource_id): row for row in _focus_rows(session, network_element_type)
        }
        removed_count = 0
        for identity in body.remove:
            row = existing.pop((identity.measurement_unit_id, identity.metric_resource_id), None)
            if row is not None:
                session.delete(row)
                removed_count += 1

        added_count = 0
        now = datetime.now(UTC)
        for identity in body.add:
            key = (identity.measurement_unit_id, identity.metric_resource_id)
            if key in existing:
                continue
            row = KpiTeamFocusItem(
                network_element_type=network_element_type,
                measurement_unit_id=identity.measurement_unit_id,
                metric_resource_id=identity.metric_resource_id,
                added_by=actor.username,
                added_at=now,
            )
            session.add(row)
            existing[key] = row
            added_count += 1

        next_revision = current_revision + 1
        if revision is None:
            session.add(
                KpiTeamFocusRevision(
                    network_element_type=network_element_type,
                    revision=next_revision,
                    updated_at=now,
                )
            )
        else:
            revision.revision = next_revision
            revision.updated_at = now

        session.flush()
        rows = _focus_rows(session, network_element_type)
        available_count, unavailable_count = _counts(context, rows)
        session.commit()
        return schemas.KpiTeamFocusPatchResponseV6(
            network_element_type=network_element_type,
            revision=next_revision,
            added_count=added_count,
            removed_count=removed_count,
            available_count=available_count,
            unavailable_count=unavailable_count,
        )
