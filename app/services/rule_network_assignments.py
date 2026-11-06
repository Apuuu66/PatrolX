"""业务规则网元归属的共享配置、revision 与追加审计。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.dicts import load_dicts
from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry, registry
from app.models import kpi_v6 as schemas
from app.models.db import (
    KpiRuleAssignmentAudit,
    KpiRuleAssignmentGlobalState,
    KpiRuleAssignmentState,
    KpiRuleNetworkAssignment,
    session_factory,
)
from app.services.auth import AuthSession

_FORBIDDEN_TYPES = frozenset({"*", "COMMON", "PUBLIC", "GENERIC", ""})
_SNAPSHOT_NOTICE = "归属变更只影响后续启动或显式重建的任务。"


class RuleAssignmentError(Exception):
    """规则归属业务错误；由路由层映射为统一 API 错误。"""

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


def _iso_utc(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _allowed_types() -> tuple[str, ...]:
    return tuple(item.code.strip().upper() for item in load_dicts().product)


def _normalize_types(values: list[str]) -> list[str]:
    allowed = _allowed_types()
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or value.strip() != value:
            raise RuleAssignmentError(
                "invalid_network_element_type",
                "归属只能选择运行时网元类型字典中的值",
                400,
                {"allowed": list(allowed)},
            )
        canonical = value.upper()
        if canonical in _FORBIDDEN_TYPES or canonical not in allowed:
            raise RuleAssignmentError(
                "invalid_network_element_type",
                "归属只能选择运行时网元类型字典中的值",
                400,
                {"network_element_type": value, "allowed": list(allowed)},
            )
        normalized.add(canonical)
    return [item for item in allowed if item in normalized]


def _require_admin(actor: AuthSession) -> None:
    if actor.role != "admin":
        raise RuleAssignmentError(
            "rule_assignment_write_forbidden",
            "当前用户无规则网元归属维护权限",
            403,
        )


def _normal_business_rules(
    registry_override: RuleRegistry | Any | None,
) -> dict[str, Inspector]:
    active_registry = registry_override or registry
    active_registry.load_all()
    return {rule.code: rule for rule in active_registry.all() if not rule.hidden}


def _rule_or_error(
    rule_code: str,
    registry_override: RuleRegistry | Any | None,
) -> Inspector:
    rule = _normal_business_rules(registry_override).get(rule_code)
    if rule is None:
        raise RuleAssignmentError(
            "business_rule_not_found",
            "业务规则不存在或不可维护",
            404,
            {"rule_code": rule_code},
        )
    return rule


def _global_revision(session: Session) -> int:
    state = session.get(KpiRuleAssignmentGlobalState, 1)
    return state.revision if state is not None else 0


def _ensure_global_state(session: Session, now: datetime) -> KpiRuleAssignmentGlobalState:
    state = session.get(KpiRuleAssignmentGlobalState, 1)
    if state is None:
        state = KpiRuleAssignmentGlobalState(id=1, revision=0, updated_at=now)
        session.add(state)
    return state


def _rule_revision(session: Session, rule_code: str) -> int:
    state = session.get(KpiRuleAssignmentState, rule_code)
    return state.revision if state is not None else 0


def _assignments_for_rules(
    session: Session,
    rule_codes: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {code: [] for code in rule_codes}
    if not rule_codes:
        return result
    rows = session.query(KpiRuleNetworkAssignment).filter(KpiRuleNetworkAssignment.rule_code.in_(rule_codes)).all()
    allowed_order = {value: index for index, value in enumerate(_allowed_types())}
    for row in rows:
        result.setdefault(row.rule_code, []).append(row.network_element_type)
    for values in result.values():
        values.sort(key=lambda item: (allowed_order.get(item, 999), item))
    return result


def _assignment_item(
    rule: Inspector,
    network_element_types: list[str],
    revision: int,
    *,
    updated_at: datetime | None = None,
    updated_by: str | None = None,
) -> schemas.KpiRuleNetworkAssignmentV6:
    return schemas.KpiRuleNetworkAssignmentV6(
        rule_code=rule.code,
        name=rule.name,
        category=str(rule.category.value if hasattr(rule.category, "value") else rule.category),
        priority=int(rule.priority.value if hasattr(rule.priority, "value") else rule.priority),
        rule_version=rule.rule_version,
        description=rule.description,
        recommendation=rule.recommendation,
        assignment_state=(
            schemas.KpiRuleAssignmentState.ASSIGNED
            if network_element_types
            else schemas.KpiRuleAssignmentState.UNASSIGNED
        ),
        network_element_types=network_element_types,
        revision=revision,
        updated_at=_iso_utc(updated_at) if updated_at is not None else None,
        updated_by=updated_by,
    )


def list_rule_assignments(
    *,
    actor: AuthSession,
    page: int = 1,
    page_size: int = 20,
    network_element_type: str | None = None,
    assignment_state: schemas.KpiRuleAssignmentState | None = None,
    search: str | None = None,
    registry_override: RuleRegistry | Any | None = None,
) -> schemas.KpiRuleNetworkAssignmentPageV6:
    """返回普通业务规则目录及当前归属，不读取旧 RuleState。"""
    if network_element_type is not None and assignment_state == schemas.KpiRuleAssignmentState.UNASSIGNED:
        raise RuleAssignmentError(
            "invalid_rule_assignment_filter",
            "unassigned 筛选不能与 network_element_type 同时使用",
            400,
        )
    requested_type: str | None = None
    if network_element_type is not None:
        requested_type = _normalize_types([network_element_type])[0]

    rules = sorted(
        _normal_business_rules(registry_override).values(),
        key=lambda rule: (rule.priority, rule.code),
    )
    rule_codes = {rule.code for rule in rules}
    with session_factory() as session:
        global_revision = _global_revision(session)
        assignments = _assignments_for_rules(session, rule_codes)
        states = (
            {
                row.rule_code: row
                for row in session.query(KpiRuleAssignmentState)
                .filter(KpiRuleAssignmentState.rule_code.in_(rule_codes))
                .all()
            }
            if rule_codes
            else {}
        )

    items: list[schemas.KpiRuleNetworkAssignmentV6] = []
    for rule in rules:
        types = assignments.get(rule.code, [])
        state = states.get(rule.code)
        revision = state.revision if state is not None else 0
        item = _assignment_item(
            rule,
            types,
            revision,
            updated_at=state.updated_at if state is not None else None,
            updated_by=state.updated_by if state is not None else None,
        )
        if requested_type is not None and requested_type not in types:
            continue
        if assignment_state is not None and item.assignment_state != assignment_state:
            continue
        if search and search.strip():
            needle = search.strip().casefold()
            haystack = " ".join((rule.code, rule.name, item.category, rule.description)).casefold()
            if needle not in haystack:
                continue
        items.append(item)

    total = len(items)
    offset = (page - 1) * page_size
    return schemas.KpiRuleNetworkAssignmentPageV6(
        global_revision=global_revision,
        page=page,
        page_size=page_size,
        total=total,
        can_write=actor.role == "admin",
        items=items[offset : offset + page_size],
    )


def _validate_assignment_request(
    *,
    rule_code: str,
    network_element_types: list[str],
    confirm_unassign: bool,
) -> list[str]:
    if not network_element_types and not confirm_unassign:
        raise RuleAssignmentError(
            "rule_unassign_confirmation_required",
            "清空最后一个网元归属前必须确认该规则将停止参与后续任务",
            400,
            {"rule_code": rule_code},
        )
    return _normalize_types(network_element_types)


def _write_assignments(
    session: Session,
    *,
    rule_code: str,
    network_element_types: list[str],
    rule_revision: int,
    now: datetime,
) -> None:
    session.query(KpiRuleNetworkAssignment).filter(KpiRuleNetworkAssignment.rule_code == rule_code).delete(
        synchronize_session=False
    )
    for network_element_type in network_element_types:
        session.add(
            KpiRuleNetworkAssignment(
                rule_code=rule_code,
                network_element_type=network_element_type,
                rule_revision=rule_revision,
                created_at=now,
                updated_at=now,
            )
        )


def _upsert_rule_state(
    session: Session,
    *,
    rule_code: str,
    revision: int,
    network_element_types: list[str],
    actor: AuthSession,
    now: datetime,
) -> None:
    state = session.get(KpiRuleAssignmentState, rule_code)
    if state is None:
        state = KpiRuleAssignmentState(
            rule_code=rule_code,
            revision=revision,
            assignment_state="unassigned",
            updated_by=actor.username,
            updated_at=now,
        )
        session.add(state)
    else:
        state.revision = revision
        state.updated_by = actor.username
        state.updated_at = now
    state.assignment_state = "assigned" if network_element_types else "unassigned"


def _add_audit(
    session: Session,
    *,
    rule_code: str,
    before: list[str],
    after: list[str],
    rule_revision: int,
    global_revision: int,
    actor: AuthSession,
    source: str,
    now: datetime,
) -> str:
    audit_id = f"rna_{uuid.uuid4().hex}"
    session.add(
        KpiRuleAssignmentAudit(
            audit_id=audit_id,
            rule_code=rule_code,
            before_network_element_types=before,
            after_network_element_types=after,
            rule_revision=rule_revision,
            global_revision=global_revision,
            actor=actor.username,
            source=source,
            result="success",
            error_code=None,
            idempotency_key=None,
            created_at=now,
        )
    )
    return audit_id


def _write_result(
    rule: Inspector,
    network_element_types: list[str],
    *,
    revision: int,
    global_revision: int,
    audit_id: str,
    now: datetime,
) -> schemas.KpiRuleAssignmentWriteResultV6:
    return schemas.KpiRuleAssignmentWriteResultV6(
        rule_code=rule.code,
        assignment_state=(
            schemas.KpiRuleAssignmentState.ASSIGNED
            if network_element_types
            else schemas.KpiRuleAssignmentState.UNASSIGNED
        ),
        network_element_types=network_element_types,
        revision=revision,
        global_revision=global_revision,
        audit_id=audit_id,
        updated_at=_iso_utc(now),
        snapshot_notice=_SNAPSHOT_NOTICE,
    )


def update_rule_assignment(
    rule_code: str,
    body: schemas.KpiRuleAssignmentPatchRequestV6,
    *,
    actor: AuthSession,
    registry_override: RuleRegistry | Any | None = None,
    source: str = "api",
) -> schemas.KpiRuleAssignmentWriteResultV6:
    """以完整集合替换一条规则的网元归属，并原子追加状态与审计。"""
    _require_admin(actor)
    rule = _rule_or_error(rule_code, registry_override)
    normalized = _validate_assignment_request(
        rule_code=rule_code,
        network_element_types=body.network_element_types,
        confirm_unassign=body.confirm_unassign,
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        current_revision = _rule_revision(session, rule_code)
        if body.expected_revision != current_revision:
            raise RuleAssignmentError(
                "rule_assignment_revision_conflict",
                "规则网元归属已更新，请刷新后重试",
                409,
                {
                    "rule_code": rule_code,
                    "expected_revision": body.expected_revision,
                    "current_revision": current_revision,
                },
            )
        before = _assignments_for_rules(session, {rule_code})[rule_code]
        global_state = _ensure_global_state(session, now)
        next_global_revision = global_state.revision + 1
        next_rule_revision = current_revision + 1
        _write_assignments(
            session,
            rule_code=rule_code,
            network_element_types=normalized,
            rule_revision=next_rule_revision,
            now=now,
        )
        _upsert_rule_state(
            session,
            rule_code=rule_code,
            revision=next_rule_revision,
            network_element_types=normalized,
            actor=actor,
            now=now,
        )
        global_state.revision = next_global_revision
        global_state.updated_at = now
        audit_id = _add_audit(
            session,
            rule_code=rule_code,
            before=before,
            after=normalized,
            rule_revision=next_rule_revision,
            global_revision=next_global_revision,
            actor=actor,
            source=source,
            now=now,
        )
        session.commit()
        return _write_result(
            rule,
            normalized,
            revision=next_rule_revision,
            global_revision=next_global_revision,
            audit_id=audit_id,
            now=now,
        )


def _batch_conflict_error(conflicts: list[dict[str, object]]) -> RuleAssignmentError:
    return RuleAssignmentError(
        "rule_assignment_revision_conflict",
        "批量请求中有规则已更新，整批未应用",
        409,
        {"applied": False, "conflicts": conflicts},
    )


def batch_update_rule_assignments(
    body: schemas.KpiRuleAssignmentBatchRequestV6,
    *,
    actor: AuthSession,
    registry_override: RuleRegistry | Any | None = None,
    source: str = "api",
) -> schemas.KpiRuleAssignmentBatchResponseV6:
    """在一个事务内原子替换多条规则归属，全局 revision 只递增一次。"""
    _require_admin(actor)
    codes = [item.rule_code for item in body.items]
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            raise RuleAssignmentError(
                "duplicate_rule_in_batch",
                "批量请求中的 rule_code 不得重复",
                400,
                {"rule_code": code},
            )
        seen.add(code)

    rules = _normal_business_rules(registry_override)
    normalized_by_code: dict[str, list[str]] = {}
    for item in body.items:
        if item.rule_code not in rules:
            raise RuleAssignmentError(
                "business_rule_not_found",
                "业务规则不存在或不可维护",
                404,
                {"rule_code": item.rule_code},
            )
        normalized_by_code[item.rule_code] = _validate_assignment_request(
            rule_code=item.rule_code,
            network_element_types=item.network_element_types,
            confirm_unassign=item.confirm_unassign,
        )

    now = datetime.now(UTC)
    with session_factory() as session:
        conflicts: list[dict[str, object]] = []
        current_revisions = {item.rule_code: _rule_revision(session, item.rule_code) for item in body.items}
        for item in body.items:
            current = current_revisions[item.rule_code]
            if item.expected_revision != current:
                conflicts.append(
                    {
                        "rule_code": item.rule_code,
                        "expected_revision": item.expected_revision,
                        "current_revision": current,
                    }
                )
        if conflicts:
            raise _batch_conflict_error(conflicts)

        before_by_code = _assignments_for_rules(session, seen)
        global_state = _ensure_global_state(session, now)
        next_global_revision = global_state.revision + 1
        results: list[schemas.KpiRuleAssignmentWriteResultV6] = []
        audit_ids: list[str] = []
        for item in body.items:
            normalized = normalized_by_code[item.rule_code]
            next_rule_revision = current_revisions[item.rule_code] + 1
            _write_assignments(
                session,
                rule_code=item.rule_code,
                network_element_types=normalized,
                rule_revision=next_rule_revision,
                now=now,
            )
            _upsert_rule_state(
                session,
                rule_code=item.rule_code,
                revision=next_rule_revision,
                network_element_types=normalized,
                actor=actor,
                now=now,
            )
            audit_id = _add_audit(
                session,
                rule_code=item.rule_code,
                before=before_by_code[item.rule_code],
                after=normalized,
                rule_revision=next_rule_revision,
                global_revision=next_global_revision,
                actor=actor,
                source=source,
                now=now,
            )
            audit_ids.append(audit_id)
            results.append(
                _write_result(
                    rules[item.rule_code],
                    normalized,
                    revision=next_rule_revision,
                    global_revision=next_global_revision,
                    audit_id=audit_id,
                    now=now,
                )
            )
        global_state.revision = next_global_revision
        global_state.updated_at = now
        session.commit()
        return schemas.KpiRuleAssignmentBatchResponseV6(
            global_revision=next_global_revision,
            items=results,
            audit_ids=audit_ids,
        )


def list_rule_assignment_audits(
    *,
    page: int = 1,
    page_size: int = 20,
    rule_code: str | None = None,
    network_element_type: str | None = None,
    result: schemas.KpiRuleAssignmentAuditResult | None = None,
    source: schemas.KpiRuleAssignmentAuditSource | None = None,
) -> schemas.KpiRuleAssignmentAuditPageV6:
    """按追加时间倒序返回不可变规则归属审计。"""
    requested_type = _normalize_types([network_element_type])[0] if network_element_type is not None else None
    with session_factory() as session:
        rows = session.query(KpiRuleAssignmentAudit).all()
    filtered: list[schemas.KpiRuleAssignmentAuditV6] = []
    for row in rows:
        if rule_code is not None and row.rule_code != rule_code:
            continue
        before = [str(value) for value in (row.before_network_element_types or [])]
        after = [str(value) for value in (row.after_network_element_types or [])]
        if requested_type is not None and requested_type not in {*before, *after}:
            continue
        if result is not None and row.result != result.value:
            continue
        if source is not None and row.source != source.value:
            continue
        filtered.append(
            schemas.KpiRuleAssignmentAuditV6(
                audit_id=row.audit_id,
                rule_code=row.rule_code,
                before_network_element_types=before,
                after_network_element_types=after,
                rule_revision=row.rule_revision,
                global_revision=row.global_revision,
                actor=row.actor,
                source=schemas.KpiRuleAssignmentAuditSource(row.source),
                result=schemas.KpiRuleAssignmentAuditResult(row.result),
                error_code=row.error_code,
                idempotency_key=row.idempotency_key,
                created_at=_iso_utc(row.created_at),
            )
        )
    filtered.sort(key=lambda item: (item.created_at, item.audit_id), reverse=True)
    total = len(filtered)
    offset = (page - 1) * page_size
    return schemas.KpiRuleAssignmentAuditPageV6(
        total=total,
        page=page,
        page_size=page_size,
        items=filtered[offset : offset + page_size],
    )
