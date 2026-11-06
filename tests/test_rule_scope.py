"""任务规则范围快照与重跑冻结边界测试。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.inspectors.base import Inspector, PrepareSpec
from app.models import kpi_v6 as schemas
from app.models.schemas import Priority, RuleCategory, Severity
from app.services.auth import AuthSession

_ADMIN = AuthSession(token="rule-scope-admin", username="scope-admin", role="admin")


def _rule(
    code: str,
    *,
    name: str | None = None,
    priority: Priority = Priority.P1,
    version: str = "1.0.0",
    hidden: bool = False,
    owner_prepare: bool = False,
) -> Inspector:
    prepare = PrepareSpec(code=f"{code}.prepare", owner_code=code, run=lambda _context: None) if owner_prepare else None
    return Inspector(
        code=code,
        name=name or code,
        category=RuleCategory.KPI if not hidden else RuleCategory.OTHER,
        severity=Severity.MEDIUM,
        priority=priority,
        rule_version=version,
        description=f"{code}说明",
        recommendation=f"{code}建议",
        hidden=hidden,
        source_patterns=None if hidden and code.startswith("pkg.extract") else [r"kpi/.+\.csv"],
        run=lambda _context: None,
        prepare=prepare,
    )


@dataclass
class _FakeRegistry:
    rules: list[Inspector]

    def load_all(self) -> None:
        return None

    def all(self, include_hidden: bool = False) -> list[Inspector]:
        ordered = sorted(self.rules, key=lambda rule: (rule.priority, rule.code))
        return ordered if include_hidden else [rule for rule in ordered if not rule.hidden]

    def codes(self) -> list[str]:
        return sorted(rule.code for rule in self.rules)

    def prepares(self) -> list[tuple[Inspector, PrepareSpec]]:
        return sorted(
            ((rule, rule.prepare) for rule in self.rules if rule.prepare is not None),
            key=lambda item: (item[0].priority, item[0].code, item[1].code),
        )

    def get(self, code: str) -> Inspector:
        for rule in self.rules:
            if rule.code == code:
                return rule
        raise KeyError(code)


@pytest.fixture
def scope_registry() -> _FakeRegistry:
    return _FakeRegistry(
        rules=[
            _rule("pkg.extract.main", hidden=True, priority=Priority.P0),
            _rule("pkg.extract.classification", hidden=True, priority=Priority.P0),
            _rule(
                "kpi.measurement_units",
                name="测量单元巡检",
                priority=Priority.P1,
                owner_prepare=True,
            ),
            _rule("kpi.media.resource", name="媒体资源巡检", priority=Priority.P2),
        ]
    )


def _assign(
    registry: _FakeRegistry,
    rule_code: str,
    network_element_types: list[str],
    *,
    revision: int = 0,
) -> None:
    from app.services import rule_network_assignments

    rule_network_assignments.update_rule_assignment(
        rule_code,
        schemas.KpiRuleAssignmentPatchRequestV6(
            expected_revision=revision,
            network_element_types=network_element_types,
            confirm_unassign=not network_element_types,
        ),
        actor=_ADMIN,
        registry_override=registry,
    )


def test_unassigned_rules_are_not_frozen_and_hidden_units_stay_technical(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeResolver

    snapshot = RuleScopeResolver(scope_registry).resolve(
        task_id="task-scope-empty",
        network_element_type="UMF",
        trigger="api",
        source="api",
        now=datetime(2026, 11, 6, tzinfo=UTC),
    )

    assert snapshot.task_id == "task-scope-empty"
    assert snapshot.network_element_type == "UMF"
    assert snapshot.assignment_revision == 0
    assert snapshot.items == ()
    assert len(snapshot.registry_fingerprint) == 64
    assert {rule.code for rule in scope_registry.rules if rule.hidden}.isdisjoint(
        {item.rule_code for item in snapshot.items}
    )


def test_resolver_filters_each_network_type_and_freezes_rule_metadata(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeResolver

    _assign(scope_registry, "kpi.measurement_units", ["UMF", "CSP"])
    _assign(scope_registry, "kpi.media.resource", ["CSP"])

    resolver = RuleScopeResolver(scope_registry)
    umf = resolver.resolve(
        task_id="task-umf",
        network_element_type="UMF",
        trigger="api",
        source="upload",
        now=datetime(2026, 11, 6, tzinfo=UTC),
    )
    csp = resolver.resolve(
        task_id="task-csp",
        network_element_type="CSP",
        trigger="cli",
        source="cli",
        now=datetime(2026, 11, 6, tzinfo=UTC),
    )

    assert [item.rule_code for item in umf.items] == ["kpi.measurement_units"]
    assert [item.rule_code for item in csp.items] == [
        "kpi.measurement_units",
        "kpi.media.resource",
    ]
    first = umf.items[0]
    assert first.rule_version == "1.0.0"
    assert first.category == "kpi"
    assert first.priority == 1
    assert first.execution_order == 0
    assert first.assignment_snapshot == {
        "network_element_types": ["UMF", "CSP"],
        "assignment_revision": 2,
    }
    assert csp.assignment_revision == 2
    assert umf.registry_fingerprint == csp.registry_fingerprint


def test_assignment_changes_after_freeze_do_not_change_snapshot(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeResolver

    _assign(scope_registry, "kpi.measurement_units", ["UMF"])
    resolver = RuleScopeResolver(scope_registry)
    snapshot = resolver.resolve(
        task_id="task-frozen",
        network_element_type="UMF",
        trigger="api",
        source="upload",
        now=datetime(2026, 11, 6, tzinfo=UTC),
    )

    _assign(scope_registry, "kpi.measurement_units", ["CSP"], revision=1)
    assert [item.rule_code for item in snapshot.items] == ["kpi.measurement_units"]
    assert snapshot.assignment_revision == 1
    assert snapshot.items[0].assignment_snapshot["network_element_types"] == ["UMF"]


def test_registry_fingerprint_is_stable_and_changes_with_rule_definition(
    isolated_db,
) -> None:
    from app.services.rule_scope import RuleScopeResolver

    base = _FakeRegistry([_rule("kpi.measurement_units", name="测量单元巡检")])
    same = _FakeRegistry([_rule("kpi.measurement_units", name="测量单元巡检")])
    changed = _FakeRegistry([_rule("kpi.measurement_units", name="测量单元巡检新", version="1.0.1")])

    resolve = RuleScopeResolver.resolve
    kwargs = {
        "task_id": "task-fingerprint",
        "network_element_type": "UMF",
        "trigger": "api",
        "source": "api",
        "now": datetime(2026, 11, 6, tzinfo=UTC),
    }
    first = resolve(RuleScopeResolver(base), **kwargs)
    second = resolve(RuleScopeResolver(same), **kwargs)
    third = resolve(RuleScopeResolver(changed), **kwargs)

    assert first.registry_fingerprint == second.registry_fingerprint
    assert first.registry_fingerprint != third.registry_fingerprint


def test_log_supplement_without_network_type_freezes_no_business_rules(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeResolver

    _assign(scope_registry, "kpi.measurement_units", ["UMF"])
    snapshot = RuleScopeResolver(scope_registry).resolve(
        task_id="task-log-unscoped",
        network_element_type=None,
        trigger="api",
        source="upload",
        now=datetime(2026, 11, 6, tzinfo=UTC),
    )

    assert snapshot.network_element_type is None
    assert snapshot.items == ()
    assert snapshot.assignment_revision == 1


def test_public_or_unknown_network_scope_is_rejected(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeError, RuleScopeResolver

    resolver = RuleScopeResolver(scope_registry)
    for value in ("*", "COMMON", "PUBLIC", "GENERIC", "UNKNOWN"):
        with pytest.raises(RuleScopeError) as exc_info:
            resolver.resolve(
                task_id="task-invalid-scope",
                network_element_type=value,
                trigger="api",
                source="api",
            )
        assert exc_info.value.code == "invalid_network_element_type"
        assert exc_info.value.status_code == 400


def test_prepare_follows_frozen_owner_and_hidden_extract_remains_available(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.executor import Executor
    from app.services.rule_scope import RuleScopeResolver

    _assign(scope_registry, "kpi.measurement_units", ["UMF"])
    snapshot = RuleScopeResolver(scope_registry).resolve(
        task_id="task-plan",
        network_element_type="UMF",
        trigger="api",
        source="api",
    )
    executor = Executor(
        scope_registry,
        frozen_rule_codes={item.rule_code for item in snapshot.items},
    )

    assert executor.extract_plan() == [
        "pkg.extract.main",
        "pkg.extract.classification",
    ]
    assert executor.prepare_plan() == ["kpi.measurement_units.prepare"]
    assert executor.inspect_plan() == ["kpi.measurement_units"]


def test_rerun_rejects_rule_outside_snapshot_and_version_mismatch(
    isolated_db,
    scope_registry: _FakeRegistry,
) -> None:
    from app.services.rule_scope import RuleScopeError, RuleScopeResolver

    _assign(scope_registry, "kpi.measurement_units", ["UMF"])
    resolver = RuleScopeResolver(scope_registry)
    snapshot = resolver.resolve(
        task_id="task-rerun",
        network_element_type="UMF",
        trigger="api",
        source="api",
    )

    with pytest.raises(RuleScopeError) as outside:
        resolver.validate_frozen_rules(snapshot, ["kpi.media.resource"])
    assert outside.value.code == "rule_not_in_task_scope"
    assert outside.value.status_code == 409

    changed_registry = _FakeRegistry(
        [
            _rule("pkg.extract.main", hidden=True, priority=Priority.P0),
            _rule("pkg.extract.classification", hidden=True, priority=Priority.P0),
            _rule("kpi.measurement_units", version="2.0.0", owner_prepare=True),
        ]
    )
    with pytest.raises(RuleScopeError) as mismatch:
        RuleScopeResolver(changed_registry).validate_frozen_rules(
            snapshot,
            ["kpi.measurement_units"],
        )
    assert mismatch.value.code == "rule_snapshot_version_mismatch"
    assert mismatch.value.status_code == 409
    assert mismatch.value.detail == {
        "rule_code": "kpi.measurement_units",
        "frozen_version": "1.0.0",
        "current_version": "2.0.0",
    }
