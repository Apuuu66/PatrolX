"""规则网元归属 v6 服务与 API 契约测试。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.inspectors.base import Inspector
from app.models import kpi_v6 as schemas
from app.models.db import (
    KpiRuleAssignmentAudit,
    KpiRuleAssignmentGlobalState,
    KpiRuleAssignmentState,
    KpiRuleNetworkAssignment,
    RuleState,
    session_factory,
)
from app.models.schemas import Priority, RuleCategory, Severity
from app.services.auth import AuthSession

_ADMIN = AuthSession(
    token="rule-assignment-admin-token",
    username="rule-admin",
    role="admin",
)
_VIEWER = AuthSession(
    token="rule-assignment-viewer-token",
    username="rule-viewer",
    role="viewer",
)


def _rule(
    code: str,
    *,
    name: str,
    priority: Priority = Priority.P1,
    hidden: bool = False,
) -> Inspector:
    return Inspector(
        code=code,
        name=name,
        category=RuleCategory.KPI,
        severity=Severity.MEDIUM,
        priority=priority,
        rule_version="1.0.0",
        description=f"{name}说明",
        recommendation=f"{name}建议",
        hidden=hidden,
        source_patterns=[r"kpi/.+\.csv"],
        run=lambda _context: None,
    )


@dataclass
class _FakeRegistry:
    rules: list[Inspector]

    def load_all(self) -> None:
        return None

    def all(self, include_hidden: bool = False) -> list[Inspector]:
        ordered = sorted(self.rules, key=lambda rule: (rule.priority, rule.code))
        return ordered if include_hidden else [rule for rule in ordered if not rule.hidden]

    def get(self, code: str) -> Inspector:
        for rule in self.rules:
            if rule.code == code:
                return rule
        raise KeyError(code)


@pytest.fixture
def assignment_registry() -> _FakeRegistry:
    return _FakeRegistry(
        rules=[
            _rule("kpi.measurement_units", name="测量单元巡检"),
            _rule(
                "kpi.media.unassigned",
                name="媒体资源未归属规则",
                priority=Priority.P2,
            ),
            _rule(
                "pkg.extract",
                name="内部解压",
                hidden=True,
            ),
        ]
    )


def _patch_request(
    network_element_types: list[str],
    *,
    expected_revision: int = 0,
    confirm_unassign: bool = False,
) -> schemas.KpiRuleAssignmentPatchRequestV6:
    return schemas.KpiRuleAssignmentPatchRequestV6(
        expected_revision=expected_revision,
        network_element_types=network_element_types,
        confirm_unassign=confirm_unassign,
    )


def _batch_item(
    rule_code: str,
    network_element_types: list[str],
    *,
    expected_revision: int,
    confirm_unassign: bool = False,
) -> schemas.KpiRuleAssignmentBatchItemV6:
    return schemas.KpiRuleAssignmentBatchItemV6(
        rule_code=rule_code,
        expected_revision=expected_revision,
        network_element_types=network_element_types,
        confirm_unassign=confirm_unassign,
    )


def test_initial_catalog_is_unassigned_and_ignores_legacy_rule_state(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    with session_factory() as session:
        session.add(
            RuleState(
                rule_code="kpi.measurement_units",
                enabled=True,
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    page = rule_network_assignments.list_rule_assignments(
        page=1,
        page_size=20,
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    assert page.global_revision == 0
    assert page.total == 2
    assert page.can_write is True
    assert [item.rule_code for item in page.items] == [
        "kpi.measurement_units",
        "kpi.media.unassigned",
    ]
    assert {item.assignment_state for item in page.items} == {schemas.KpiRuleAssignmentState.UNASSIGNED}
    assert all(item.network_element_types == [] for item in page.items)
    assert all(item.revision == 0 for item in page.items)

    with session_factory() as session:
        assert session.query(KpiRuleNetworkAssignment).count() == 0
        assert session.query(KpiRuleAssignmentState).count() == 0


def test_single_patch_replaces_multiple_types_and_appends_audit(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    assigned = rule_network_assignments.update_rule_assignment(
        "kpi.measurement_units",
        _patch_request(["CSP", "UMF"]),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    assert assigned.assignment_state == schemas.KpiRuleAssignmentState.ASSIGNED
    assert assigned.network_element_types == ["UMF", "CSP"]
    assert assigned.revision == 1
    assert assigned.global_revision == 1
    assert assigned.audit_id
    assert "后续" in (assigned.snapshot_notice or "")

    assigned_csp_only = rule_network_assignments.update_rule_assignment(
        "kpi.measurement_units",
        _patch_request(["CSP"], expected_revision=1),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    assert assigned_csp_only.network_element_types == ["CSP"]
    assert assigned_csp_only.revision == 2
    assert assigned_csp_only.global_revision == 2

    with session_factory() as session:
        audit = session.get(KpiRuleAssignmentAudit, assigned.audit_id)
        assert audit is not None
        assert audit.rule_code == "kpi.measurement_units"
        assert audit.before_network_element_types == []
        assert audit.after_network_element_types == ["UMF", "CSP"]
        assert audit.rule_revision == 1
        assert audit.global_revision == 1
        assert audit.actor == _ADMIN.username
        assert audit.source == "api"
        assert audit.result == "success"


def test_stale_revision_is_rejected_without_writing(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    first = rule_network_assignments.update_rule_assignment(
        "kpi.measurement_units",
        _patch_request(["UMF"]),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    with pytest.raises(rule_network_assignments.RuleAssignmentError) as exc_info:
        rule_network_assignments.update_rule_assignment(
            "kpi.measurement_units",
            _patch_request(["CSP"], expected_revision=first.revision - 1),
            actor=_ADMIN,
            registry_override=assignment_registry,
        )

    assert exc_info.value.code == "rule_assignment_revision_conflict"
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "rule_code": "kpi.measurement_units",
        "expected_revision": 0,
        "current_revision": 1,
    }

    with session_factory() as session:
        state = session.get(KpiRuleAssignmentState, "kpi.measurement_units")
        assert state is not None
        assert state.revision == 1
        assert [
            row.network_element_type
            for row in session.query(KpiRuleNetworkAssignment)
            .filter(KpiRuleNetworkAssignment.rule_code == "kpi.measurement_units")
            .all()
        ] == ["UMF"]


def test_batch_is_atomic_and_increments_global_revision_once(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    response = rule_network_assignments.batch_update_rule_assignments(
        schemas.KpiRuleAssignmentBatchRequestV6(
            items=[
                _batch_item(
                    "kpi.measurement_units",
                    ["UMF", "CSP"],
                    expected_revision=0,
                ),
                _batch_item(
                    "kpi.media.unassigned",
                    [],
                    expected_revision=0,
                    confirm_unassign=True,
                ),
            ]
        ),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    assert response.global_revision == 1
    assert len(response.audit_ids) == 2
    assert [item.revision for item in response.items] == [1, 1]
    assert response.items[1].assignment_state == schemas.KpiRuleAssignmentState.UNASSIGNED


def test_batch_conflict_applies_nothing(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    rule_network_assignments.update_rule_assignment(
        "kpi.measurement_units",
        _patch_request(["UMF"]),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    with pytest.raises(rule_network_assignments.RuleAssignmentError) as exc_info:
        rule_network_assignments.batch_update_rule_assignments(
            schemas.KpiRuleAssignmentBatchRequestV6(
                items=[
                    _batch_item(
                        "kpi.measurement_units",
                        ["CSP"],
                        expected_revision=0,
                    ),
                    _batch_item(
                        "kpi.media.unassigned",
                        ["UMF"],
                        expected_revision=0,
                    ),
                ]
            ),
            actor=_ADMIN,
            registry_override=assignment_registry,
        )

    assert exc_info.value.code == "rule_assignment_revision_conflict"
    assert exc_info.value.detail["applied"] is False
    assert exc_info.value.detail["conflicts"] == [
        {
            "rule_code": "kpi.measurement_units",
            "expected_revision": 0,
            "current_revision": 1,
        }
    ]

    with session_factory() as session:
        rows = session.query(KpiRuleNetworkAssignment).all()
        assert [(row.rule_code, row.network_element_type) for row in rows] == [("kpi.measurement_units", "UMF")]
        global_state = session.get(KpiRuleAssignmentGlobalState, 1)
        assert global_state is not None
        assert global_state.revision == 1


def test_duplicate_rule_batch_is_rejected_before_writes(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    with pytest.raises(rule_network_assignments.RuleAssignmentError) as exc_info:
        rule_network_assignments.batch_update_rule_assignments(
            schemas.KpiRuleAssignmentBatchRequestV6(
                items=[
                    _batch_item(
                        "kpi.measurement_units",
                        ["UMF"],
                        expected_revision=0,
                    ),
                    _batch_item(
                        "kpi.measurement_units",
                        ["CSP"],
                        expected_revision=0,
                    ),
                ]
            ),
            actor=_ADMIN,
            registry_override=assignment_registry,
        )

    assert exc_info.value.code == "duplicate_rule_in_batch"
    assert exc_info.value.status_code == 400


def test_empty_assignment_requires_explicit_confirmation(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    with pytest.raises(ValidationError, match="清空最后归属必须显式确认"):
        _patch_request([])

    unconfirmed = schemas.KpiRuleAssignmentPatchRequestV6.model_construct(
        expected_revision=0,
        network_element_types=[],
        confirm_unassign=False,
    )
    with pytest.raises(rule_network_assignments.RuleAssignmentError) as exc_info:
        rule_network_assignments.update_rule_assignment(
            "kpi.measurement_units",
            unconfirmed,
            actor=_ADMIN,
            registry_override=assignment_registry,
        )

    assert exc_info.value.code == "rule_unassign_confirmation_required"
    assert exc_info.value.status_code == 400


def test_public_scope_values_are_rejected(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    for invalid in ("COMMON", "*", "PUBLIC", "A" * 33, ""):
        with pytest.raises(ValidationError):
            _patch_request([invalid])

    forged = schemas.KpiRuleAssignmentPatchRequestV6.model_construct(
        expected_revision=0,
        network_element_types=["GENERIC"],
        confirm_unassign=False,
    )
    with pytest.raises(rule_network_assignments.RuleAssignmentError) as exc_info:
        rule_network_assignments.update_rule_assignment(
            "kpi.measurement_units",
            forged,
            actor=_ADMIN,
            registry_override=assignment_registry,
        )

    assert exc_info.value.code == "invalid_network_element_type"
    assert exc_info.value.status_code == 400


def test_only_normal_business_rules_are_mutable(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    with pytest.raises(rule_network_assignments.RuleAssignmentError) as hidden:
        rule_network_assignments.update_rule_assignment(
            "pkg.extract",
            _patch_request(["UMF"]),
            actor=_ADMIN,
            registry_override=assignment_registry,
        )
    assert hidden.value.code == "business_rule_not_found"
    assert hidden.value.status_code == 404

    with pytest.raises(rule_network_assignments.RuleAssignmentError) as unknown:
        rule_network_assignments.update_rule_assignment(
            "kpi.unknown",
            _patch_request(["UMF"]),
            actor=_ADMIN,
            registry_override=assignment_registry,
        )
    assert unknown.value.code == "business_rule_not_found"


def test_catalog_filters_search_and_audits(
    isolated_db,
    assignment_registry: _FakeRegistry,
) -> None:
    from app.services import rule_network_assignments

    first = rule_network_assignments.update_rule_assignment(
        "kpi.measurement_units",
        _patch_request(["UMF"]),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )
    rule_network_assignments.update_rule_assignment(
        "kpi.media.unassigned",
        _patch_request(["CSP"]),
        actor=_ADMIN,
        registry_override=assignment_registry,
    )

    umf = rule_network_assignments.list_rule_assignments(
        network_element_type="UMF",
        actor=_ADMIN,
        registry_override=assignment_registry,
    )
    assert [item.rule_code for item in umf.items] == ["kpi.measurement_units"]

    unassigned = rule_network_assignments.list_rule_assignments(
        assignment_state=schemas.KpiRuleAssignmentState.UNASSIGNED,
        actor=_ADMIN,
        registry_override=assignment_registry,
    )
    assert unassigned.total == 0

    searched = rule_network_assignments.list_rule_assignments(
        search="媒体资源",
        actor=_ADMIN,
        registry_override=assignment_registry,
    )
    assert [item.rule_code for item in searched.items] == ["kpi.media.unassigned"]

    audit_page = rule_network_assignments.list_rule_assignment_audits(
        network_element_type="UMF",
        page=1,
        page_size=20,
    )
    assert audit_page.total == 1
    assert audit_page.items[0].audit_id == first.audit_id
    assert audit_page.items[0].after_network_element_types == ["UMF"]


def test_api_exposes_catalog_patch_batch_audit_and_conflicts(
    isolated_db,
    assignment_registry: _FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import rule_network_assignments

    monkeypatch.setattr(rule_network_assignments, "registry", assignment_registry)
    client = TestClient(app)

    listed = client.get("/api/v6/kpi/rule-network-assignments", params={"page_size": 20})
    assert listed.status_code == 200
    assert listed.json()["global_revision"] == 0
    assert listed.json()["total"] == 2
    assert {item["assignment_state"] for item in listed.json()["items"]} == {"unassigned"}

    patched = client.patch(
        "/api/v6/kpi/rule-network-assignments/kpi.measurement_units",
        json={
            "expected_revision": 0,
            "network_element_types": ["UMF", "CSP"],
            "confirm_unassign": False,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["network_element_types"] == ["UMF", "CSP"]
    assert patched.json()["revision"] == 1

    filtered = client.get(
        "/api/v6/kpi/rule-network-assignments",
        params={"network_element_type": "UMF"},
    )
    assert filtered.status_code == 200
    assert [item["rule_code"] for item in filtered.json()["items"]] == ["kpi.measurement_units"]

    batch = client.post(
        "/api/v6/kpi/rule-network-assignments/batch",
        json={
            "items": [
                {
                    "rule_code": "kpi.measurement_units",
                    "expected_revision": 1,
                    "network_element_types": ["CSP"],
                },
                {
                    "rule_code": "kpi.media.unassigned",
                    "expected_revision": 0,
                    "network_element_types": [],
                    "confirm_unassign": True,
                },
            ]
        },
    )
    assert batch.status_code == 200
    assert batch.json()["global_revision"] == 2
    assert len(batch.json()["audit_ids"]) == 2

    stale = client.patch(
        "/api/v6/kpi/rule-network-assignments/kpi.measurement_units",
        json={
            "expected_revision": 1,
            "network_element_types": ["UMF"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "rule_assignment_revision_conflict"

    audits = client.get(
        "/api/v6/kpi/rule-network-assignments/audits",
        params={"network_element_type": "UMF", "page_size": 20},
    )
    assert audits.status_code == 200
    assert audits.json()["total"] == 2
    assert {item["result"] for item in audits.json()["items"]} == {"success"}


def test_api_validates_filter_and_empty_unassign(
    isolated_db,
    assignment_registry: _FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import rule_network_assignments

    monkeypatch.setattr(rule_network_assignments, "registry", assignment_registry)
    client = TestClient(app)

    conflicting = client.get(
        "/api/v6/kpi/rule-network-assignments",
        params={
            "network_element_type": "UMF",
            "assignment_state": "unassigned",
        },
    )
    assert conflicting.status_code == 400
    assert conflicting.json()["code"] == "invalid_rule_assignment_filter"

    invalid_type = client.get(
        "/api/v6/kpi/rule-network-assignments",
        params={"network_element_type": "GENERIC"},
    )
    assert invalid_type.status_code == 400
    assert invalid_type.json()["code"] == "invalid_network_element_type"

    unconfirmed = client.patch(
        "/api/v6/kpi/rule-network-assignments/kpi.measurement_units",
        json={
            "expected_revision": 0,
            "network_element_types": [],
            "confirm_unassign": False,
        },
    )
    assert unconfirmed.status_code == 422


def test_api_maps_viewer_to_domain_forbidden(
    isolated_db,
    assignment_registry: _FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import rule_network_assignments
    from app.services.auth import get_current_user

    monkeypatch.setattr(rule_network_assignments, "registry", assignment_registry)
    app.dependency_overrides[get_current_user] = lambda: _VIEWER
    client = TestClient(app)

    denied = client.patch(
        "/api/v6/kpi/rule-network-assignments/kpi.measurement_units",
        json={
            "expected_revision": 0,
            "network_element_types": ["UMF"],
        },
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "rule_assignment_write_forbidden"
