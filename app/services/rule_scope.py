"""任务规则范围冻结与单规则重跑范围校验。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.core.dicts import load_dicts
from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry, registry
from app.models.db import (
    KpiRuleAssignmentGlobalState,
    KpiRuleNetworkAssignment,
    session_factory,
)
from app.services.task_db import RuleScopeItemData, RuleScopeSnapshotData

_PUBLIC_SCOPES = frozenset({"*", "COMMON", "PUBLIC", "GENERIC", ""})


class RuleScopeError(Exception):
    """规则范围冻结或重跑校验错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _allowed_network_types() -> tuple[str, ...]:
    return tuple(item.code.strip().upper() for item in load_dicts().product)


def _normalize_network_type(network_element_type: str | None) -> str | None:
    if network_element_type is None:
        return None
    normalized = str(network_element_type).strip().upper()
    if normalized in _PUBLIC_SCOPES or normalized not in _allowed_network_types():
        raise RuleScopeError(
            "invalid_network_element_type",
            "网元类型不在运行时字典中",
            400,
            {
                "network_element_type": network_element_type,
                "allowed": list(_allowed_network_types()),
            },
        )
    return normalized


def _callable_identity(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if module is None and qualname is None:
        return {"repr": repr(value)}
    return {
        "module": str(module or ""),
        "qualname": str(qualname or ""),
    }


def _registry_fingerprint(rules: list[Inspector]) -> str:
    """对完整规则注册元数据生成顺序无关的稳定 SHA-256。"""
    payload = []
    for rule in sorted(rules, key=lambda item: item.code):
        prepare = rule.prepare
        payload.append(
            {
                "code": rule.code,
                "name": rule.name,
                "category": _enum_value(rule.category),
                "severity": _enum_value(rule.severity),
                "priority": int(rule.priority),
                "rule_version": rule.rule_version,
                "hidden": rule.hidden,
                "source_patterns": list(rule.source_patterns or []),
                "source_refs": list(rule.source_refs or []),
                "run": _callable_identity(rule.run),
                "prepare": (
                    {
                        "code": prepare.code,
                        "owner_code": prepare.owner_code,
                        "run": _callable_identity(prepare.run),
                    }
                    if prepare is not None
                    else None
                ),
            }
        )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _ordered_types(values: set[str]) -> list[str]:
    allowed = _allowed_network_types()
    order = {value: index for index, value in enumerate(allowed)}
    return sorted(values, key=lambda value: (order.get(value, len(order)), value))


class RuleScopeResolver:
    """在任务真正开始时冻结业务规则范围。"""

    def __init__(
        self,
        registry_override: RuleRegistry | Any | None = None,
    ) -> None:
        self.registry = registry_override or registry
        self.registry.load_all()

    def resolve(
        self,
        *,
        task_id: str,
        network_element_type: str | None,
        trigger: str,
        source: str,
        now: datetime | None = None,
    ) -> RuleScopeSnapshotData:
        normalized_type = _normalize_network_type(network_element_type)
        rules = self.registry.all()
        business_rules = {rule.code: rule for rule in rules if not rule.hidden}
        frozen_at = now or datetime.now(UTC)
        if frozen_at.tzinfo is None:
            frozen_at = frozen_at.replace(tzinfo=UTC)
        else:
            frozen_at = frozen_at.astimezone(UTC)

        with session_factory() as session:
            global_state = session.get(KpiRuleAssignmentGlobalState, 1)
            assignment_revision = global_state.revision if global_state is not None else 0
            rows = session.query(KpiRuleNetworkAssignment).all() if normalized_type is not None else []

        assignments_by_rule: dict[str, set[str]] = {}
        for row in rows:
            if row.rule_code in business_rules:
                assignments_by_rule.setdefault(row.rule_code, set()).add(row.network_element_type)

        selected: list[Inspector] = []
        if normalized_type is not None:
            for rule in business_rules.values():
                if normalized_type in assignments_by_rule.get(rule.code, set()):
                    selected.append(rule)
        selected.sort(key=lambda rule: (int(rule.priority), rule.code))

        items = tuple(
            RuleScopeItemData(
                rule_code=rule.code,
                rule_version=rule.rule_version,
                category=_enum_value(rule.category),
                priority=int(rule.priority),
                execution_order=index,
                assignment_snapshot={
                    "network_element_types": _ordered_types(assignments_by_rule.get(rule.code, set())),
                    "assignment_revision": assignment_revision,
                },
            )
            for index, rule in enumerate(selected)
        )
        return RuleScopeSnapshotData(
            task_id=task_id,
            network_element_type=normalized_type,
            assignment_revision=assignment_revision,
            registry_fingerprint=_registry_fingerprint(rules),
            trigger=trigger,
            source=source,
            frozen_at=frozen_at,
            snapshot_state="frozen",
            items=items,
        )

    def validate_frozen_rules(
        self,
        snapshot: RuleScopeSnapshotData,
        rule_codes: list[str],
    ) -> tuple[Inspector, ...]:
        """校验重跑规则仍在冻结范围且当前版本未漂移。"""
        frozen = {item.rule_code: item for item in snapshot.items}
        for code in rule_codes:
            if code not in frozen:
                raise RuleScopeError(
                    "rule_not_in_task_scope",
                    "规则不在该任务冻结的业务规则范围内",
                    409,
                    {"rule_code": code, "task_id": snapshot.task_id},
                )

        current = {rule.code: rule for rule in self.registry.all() if not rule.hidden}
        selected: list[Inspector] = []
        for code in rule_codes:
            item = frozen[code]
            rule = current.get(code)
            current_version = rule.rule_version if rule is not None else None
            if rule is None or current_version != item.rule_version:
                raise RuleScopeError(
                    "rule_snapshot_version_mismatch",
                    "规则实现版本与任务冻结快照不一致，请全量重建",
                    409,
                    {
                        "rule_code": code,
                        "frozen_version": item.rule_version,
                        "current_version": current_version,
                    },
                )
            selected.append(rule)
        return tuple(selected)

    def validate_snapshot_versions(
        self,
        snapshot: RuleScopeSnapshotData,
    ) -> None:
        """任务启动前校验全部冻结规则版本，避免静默换版本。"""
        self.validate_frozen_rules(
            snapshot,
            [item.rule_code for item in snapshot.items],
        )
