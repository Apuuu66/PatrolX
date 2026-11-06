"""团队关注 v6 的共享读取、原子写入与权限边界测试（041 T034）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

import pytest

from app.models import kpi_v6 as schemas
from app.models.db import (
    AuthSession,
    KpiTeamFocusItem,
    KpiTeamFocusRevision,
    KpiV6MeasurementUnit,
    TaskKpiScopeItem,
    TaskKpiScopeSnapshot,
    TaskRecord,
    session_factory,
)
from app.services import kpi_team_focus

_ADMIN = AuthSession(
    token="admin-token",
    username="focus-admin",
    role="admin",
    created_at=datetime(2026, 11, 5, 8, tzinfo=UTC),
    expires_at=datetime(2026, 11, 6, 8, tzinfo=UTC),
)
_VIEWER = AuthSession(
    token="viewer-token",
    username="focus-viewer",
    role="viewer",
    created_at=datetime(2026, 11, 5, 8, tzinfo=UTC),
    expires_at=datetime(2026, 11, 6, 8, tzinfo=UTC),
)
_ADD_METRIC_ID = "ME_AV_TERMINATION_UPDATE_REQUESTS"
_REMOVE_METRIC_ID = "ME_MEDIA_DELETION_REQUESTS"

_ModelT = TypeVar("_ModelT", TaskRecord, TaskKpiScopeSnapshot, TaskKpiScopeItem)


def _identity(
    measurement_unit_id: str,
    metric_resource_id: str,
) -> schemas.KpiFocusIdentity:
    return schemas.KpiFocusIdentity(
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
    )


def _patch_request(
    task_id: str,
    *,
    expected_revision: int,
    add: list[schemas.KpiFocusIdentity] | None = None,
    remove: list[schemas.KpiFocusIdentity] | None = None,
) -> schemas.KpiTeamFocusPatchRequestV6:
    return schemas.KpiTeamFocusPatchRequestV6(
        task_id=task_id,
        expected_revision=expected_revision,
        add=add or [],
        remove=remove or [],
    )


def _copy_row(
    session,
    model: type[_ModelT],
    source_row: _ModelT,
    *,
    primary_key: str,
    value: str,
) -> _ModelT:
    values = {
        column.name: getattr(source_row, column.name)
        for column in model.__table__.columns
        if column.name != primary_key
    }
    copied = model(**{primary_key: value, **values})
    session.add(copied)
    return copied


def _clone_umf_task(source_task_id: str, target_task_id: str) -> None:
    """复制一个 UMF 任务快照，证明关注身份不绑定 task_id。"""
    with session_factory() as session:
        source_task = session.get(TaskRecord, source_task_id)
        source_snapshot = session.get(TaskKpiScopeSnapshot, source_task_id)
        assert source_task is not None
        assert source_snapshot is not None
        _copy_row(
            session,
            TaskRecord,
            source_task,
            primary_key="task_id",
            value=target_task_id,
        )
        _copy_row(
            session,
            TaskKpiScopeSnapshot,
            source_snapshot,
            primary_key="task_id",
            value=target_task_id,
        )
        scope_rows = session.query(TaskKpiScopeItem).filter(TaskKpiScopeItem.task_id == source_task_id).all()
        for row in scope_rows:
            values = {
                column.name: getattr(row, column.name)
                for column in TaskKpiScopeItem.__table__.columns
                if column.name not in {"id", "task_id"}
            }
            session.add(
                TaskKpiScopeItem(
                    task_id=target_task_id,
                    **values,
                )
            )
        session.commit()


def test_list_keeps_unavailable_focus_and_filters_without_changing_totals(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        removed_scope = (
            session.query(TaskKpiScopeItem)
            .filter(
                TaskKpiScopeItem.task_id == seed.task_id,
                TaskKpiScopeItem.metric_resource_id == _REMOVE_METRIC_ID,
            )
            .one()
        )
        session.delete(removed_scope)
        session.commit()

    page = kpi_team_focus.list_team_focus(
        seed.network_element_type,
        task_id=seed.task_id,
        actor=_ADMIN,
        page_size=50,
    )

    assert page.revision == seed.team_focus_revision
    assert page.total == 10
    assert page.available_count == 9
    assert page.unavailable_count == 1
    assert page.can_write is True
    unavailable = next(item for item in page.items if item.metric_resource_id == _REMOVE_METRIC_ID)
    assert unavailable.availability is schemas.FocusAvailability.UNAVAILABLE
    assert unavailable.availability_reason is schemas.FocusAvailabilityReason.NOT_IN_TASK_SCOPE

    filtered = kpi_team_focus.list_team_focus(
        seed.network_element_type,
        task_id=seed.task_id,
        actor=_ADMIN,
        availability=schemas.FocusAvailability.UNAVAILABLE,
        page_size=50,
    )
    assert filtered.total == 1
    assert filtered.available_count == 9
    assert filtered.unavailable_count == 1
    assert [item.metric_resource_id for item in filtered.items] == [_REMOVE_METRIC_ID]


def test_disabled_measurement_unit_marks_shared_focus_unavailable(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter(
                KpiV6MeasurementUnit.network_element_type == seed.network_element_type,
                KpiV6MeasurementUnit.measurement_unit_id == seed.measurement_unit_id,
            )
            .one()
        )
        unit.inspection_enabled = False
        session.commit()

    page = kpi_team_focus.list_team_focus(
        seed.network_element_type,
        task_id=seed.task_id,
        actor=_ADMIN,
        page_size=50,
    )

    assert page.total == 10
    assert page.available_count == 0
    assert page.unavailable_count == 10
    assert {item.availability_reason for item in page.items} == {
        schemas.FocusAvailabilityReason.MEASUREMENT_UNIT_DISABLED
    }


def test_patch_is_shared_across_same_type_tasks_and_never_changes_task_results(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    target_task_id = "KPI-V6-UMF-TASK-SECOND"
    _clone_umf_task(seed.task_id, target_task_id)
    with session_factory() as session:
        before_snapshot = session.get(TaskKpiScopeSnapshot, seed.task_id)
        assert before_snapshot is not None
        before_revision = before_snapshot.team_focus_revision
        before_frozen_at = before_snapshot.frozen_at

    response = kpi_team_focus.patch_team_focus(
        seed.network_element_type,
        _patch_request(
            seed.task_id,
            expected_revision=seed.team_focus_revision,
            add=[_identity(seed.measurement_unit_id, _ADD_METRIC_ID)],
            remove=[_identity(seed.measurement_unit_id, _REMOVE_METRIC_ID)],
        ),
        actor=_ADMIN,
    )

    assert response.revision == seed.team_focus_revision + 1
    assert response.added_count == 1
    assert response.removed_count == 1
    assert response.available_count == 10
    assert response.unavailable_count == 0

    shared_page = kpi_team_focus.list_team_focus(
        seed.network_element_type,
        task_id=target_task_id,
        actor=_ADMIN,
        page_size=50,
    )
    shared_identities = {(item.measurement_unit_id, item.metric_resource_id) for item in shared_page.items}
    assert (seed.measurement_unit_id, _ADD_METRIC_ID) in shared_identities
    assert (seed.measurement_unit_id, _REMOVE_METRIC_ID) not in shared_identities
    added = next(item for item in shared_page.items if item.metric_resource_id == _ADD_METRIC_ID)
    assert added.added_by == _ADMIN.username

    with session_factory() as session:
        after_snapshot = session.get(TaskKpiScopeSnapshot, seed.task_id)
        assert after_snapshot is not None
        assert after_snapshot.team_focus_revision == before_revision
        assert after_snapshot.frozen_at == before_frozen_at


def test_umf_and_csp_focus_are_isolated_even_for_same_identity(kpi_v6_seed) -> None:
    umf = kpi_v6_seed.umf
    csp = kpi_v6_seed.csp

    kpi_team_focus.patch_team_focus(
        umf.network_element_type,
        _patch_request(
            umf.task_id,
            expected_revision=umf.team_focus_revision,
            remove=[_identity(umf.measurement_unit_id, _REMOVE_METRIC_ID)],
        ),
        actor=_ADMIN,
    )

    umf_page = kpi_team_focus.list_team_focus(
        umf.network_element_type,
        task_id=umf.task_id,
        actor=_ADMIN,
        page_size=50,
    )
    csp_page = kpi_team_focus.list_team_focus(
        csp.network_element_type,
        task_id=csp.task_id,
        actor=_ADMIN,
        page_size=50,
    )

    assert umf_page.total == 9
    assert csp_page.total == 10
    assert csp_page.revision == csp.team_focus_revision
    assert (csp.measurement_unit_id, _REMOVE_METRIC_ID) in {
        (item.measurement_unit_id, item.metric_resource_id) for item in csp_page.items
    }


def test_stale_revision_and_invalid_add_are_atomic(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf

    with pytest.raises(kpi_team_focus.KpiTeamFocusError) as stale:
        kpi_team_focus.patch_team_focus(
            seed.network_element_type,
            _patch_request(
                seed.task_id,
                expected_revision=seed.stale_team_focus_revision,
                remove=[_identity(seed.measurement_unit_id, _REMOVE_METRIC_ID)],
            ),
            actor=_ADMIN,
        )
    assert stale.value.status_code == 409
    assert stale.value.code == "team_focus_revision_conflict"
    assert stale.value.detail == {
        "network_element_type": seed.network_element_type,
        "expected_revision": seed.stale_team_focus_revision,
        "current_revision": seed.team_focus_revision,
    }

    with pytest.raises(kpi_team_focus.KpiTeamFocusError) as invalid:
        kpi_team_focus.patch_team_focus(
            seed.network_element_type,
            _patch_request(
                seed.task_id,
                expected_revision=seed.team_focus_revision,
                add=[_identity(seed.measurement_unit_id, "ME_NOT_IN_TASK_SCOPE")],
                remove=[_identity(seed.measurement_unit_id, _REMOVE_METRIC_ID)],
            ),
            actor=_ADMIN,
        )
    assert invalid.value.status_code == 400
    assert invalid.value.code == "team_focus_item_not_available"

    with session_factory() as session:
        revision = session.get(KpiTeamFocusRevision, seed.network_element_type)
        assert revision is not None
        assert revision.revision == seed.team_focus_revision
        identities = {
            (row.measurement_unit_id, row.metric_resource_id)
            for row in session.query(KpiTeamFocusItem)
            .filter(KpiTeamFocusItem.network_element_type == seed.network_element_type)
            .all()
        }
    assert (seed.measurement_unit_id, _REMOVE_METRIC_ID) in identities
    assert (seed.measurement_unit_id, "ME_NOT_IN_TASK_SCOPE") not in identities


def test_initial_empty_focus_and_viewer_permissions(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        session.query(KpiTeamFocusItem).filter(
            KpiTeamFocusItem.network_element_type == seed.network_element_type
        ).delete()
        revision = session.get(KpiTeamFocusRevision, seed.network_element_type)
        assert revision is not None
        session.delete(revision)
        session.commit()

    page = kpi_team_focus.list_team_focus(
        seed.network_element_type,
        task_id=seed.task_id,
        actor=_VIEWER,
        page_size=50,
    )
    assert page.revision == 0
    assert page.total == 0
    assert page.items == []
    assert page.can_write is False

    with pytest.raises(kpi_team_focus.KpiTeamFocusError) as forbidden:
        kpi_team_focus.patch_team_focus(
            seed.network_element_type,
            _patch_request(
                seed.task_id,
                expected_revision=0,
                add=[_identity(seed.measurement_unit_id, _ADD_METRIC_ID)],
            ),
            actor=_VIEWER,
        )
    assert forbidden.value.status_code == 403
    assert forbidden.value.code == "kpi_write_forbidden"


def test_task_type_mismatch_and_legacy_task_are_rejected(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with pytest.raises(kpi_team_focus.KpiTeamFocusError) as mismatch:
        kpi_team_focus.list_team_focus(
            "CSP",
            task_id=seed.task_id,
            actor=_ADMIN,
        )
    assert mismatch.value.status_code == 400
    assert mismatch.value.code == "cross_network_element_scope"

    with session_factory() as session:
        snapshot = session.get(TaskKpiScopeSnapshot, seed.task_id)
        assert snapshot is not None
        session.delete(snapshot)
        session.commit()

    with pytest.raises(kpi_team_focus.KpiTeamFocusError) as legacy:
        kpi_team_focus.list_team_focus(
            seed.network_element_type,
            task_id=seed.task_id,
            actor=_ADMIN,
        )
    assert legacy.value.status_code == 409
    assert legacy.value.code == "task_result_requires_rebuild"


def test_team_focus_api_reads_and_patches_atomically(kpi_v6_seed) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    seed = kpi_v6_seed.umf
    client = TestClient(app)
    url = f"/api/v6/kpi/team-focus/{seed.network_element_type}"

    listed = client.get(url, params={"task_id": seed.task_id, "page_size": 50})
    assert listed.status_code == 200
    assert listed.json()["revision"] == seed.team_focus_revision
    assert listed.json()["total"] == 10
    assert listed.json()["can_write"] is True

    patched = client.patch(
        url,
        json={
            "task_id": seed.task_id,
            "expected_revision": seed.team_focus_revision,
            "add": [
                {
                    "measurement_unit_id": seed.measurement_unit_id,
                    "metric_resource_id": _ADD_METRIC_ID,
                }
            ],
            "remove": [
                {
                    "measurement_unit_id": seed.measurement_unit_id,
                    "metric_resource_id": _REMOVE_METRIC_ID,
                }
            ],
        },
    )

    assert patched.status_code == 200
    assert patched.json() == {
        "network_element_type": seed.network_element_type,
        "revision": seed.team_focus_revision + 1,
        "added_count": 1,
        "removed_count": 1,
        "available_count": 10,
        "unavailable_count": 0,
    }


def test_team_focus_api_maps_stale_revision_and_legacy_task_to_409(kpi_v6_seed) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    seed = kpi_v6_seed.umf
    client = TestClient(app)
    url = f"/api/v6/kpi/team-focus/{seed.network_element_type}"
    stale = client.patch(
        url,
        json={
            "task_id": seed.task_id,
            "expected_revision": seed.stale_team_focus_revision,
            "add": [
                {
                    "measurement_unit_id": seed.measurement_unit_id,
                    "metric_resource_id": _ADD_METRIC_ID,
                }
            ],
            "remove": [],
        },
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "team_focus_revision_conflict"
    assert stale.json()["detail"] == {
        "network_element_type": seed.network_element_type,
        "expected_revision": seed.stale_team_focus_revision,
        "current_revision": seed.team_focus_revision,
    }

    with session_factory() as session:
        snapshot = session.get(TaskKpiScopeSnapshot, seed.task_id)
        assert snapshot is not None
        session.delete(snapshot)
        session.commit()

    legacy = client.get(url, params={"task_id": seed.task_id})
    assert legacy.status_code == 409
    assert legacy.json()["code"] == "task_result_requires_rebuild"


def test_team_focus_api_returns_domain_forbidden_for_viewer(kpi_v6_seed) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import get_current_user

    seed = kpi_v6_seed.umf
    app.dependency_overrides[get_current_user] = lambda: _VIEWER
    client = TestClient(app)
    url = f"/api/v6/kpi/team-focus/{seed.network_element_type}"

    listed = client.get(url, params={"task_id": seed.task_id})
    assert listed.status_code == 200
    assert listed.json()["can_write"] is False

    denied = client.patch(
        url,
        json={
            "task_id": seed.task_id,
            "expected_revision": seed.team_focus_revision,
            "add": [
                {
                    "measurement_unit_id": seed.measurement_unit_id,
                    "metric_resource_id": _ADD_METRIC_ID,
                }
            ],
            "remove": [],
        },
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "kpi_write_forbidden"
