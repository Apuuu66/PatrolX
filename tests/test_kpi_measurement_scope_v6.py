"""041 US4：测量单元唯一巡检范围、恢复审计与异常修正。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import kpi_v6 as schemas
from app.models.db import (
    AuthSession,
    KpiLegacyRecoveryAudit,
    KpiPendingAttribution,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    TaskKpiScopeSnapshot,
    session_factory,
)
from app.services import kpi_measurement_scope

_ADMIN = AuthSession(
    token="scope-admin-token",
    username="scope-admin",
    role="admin",
    created_at=datetime(2026, 11, 5, 8, tzinfo=UTC),
    expires_at=datetime(2026, 11, 6, 8, tzinfo=UTC),
)
_NOW = datetime(2026, 11, 5, 8, tzinfo=UTC)


def _patch(enabled: bool, revision: int) -> schemas.KpiMeasurementInspectionPatchV6:
    return schemas.KpiMeasurementInspectionPatchV6(
        expected_revision=revision,
        inspection_enabled=enabled,
    )


def _binding_patch(
    revision: int,
    status: str,
) -> schemas.KpiMeasurementBindingPatchV6:
    return schemas.KpiMeasurementBindingPatchV6(
        expected_revision=revision,
        status=status,
        reason="人工核对源列后修正",
    )


def _audit(
    *,
    source_key: str,
    object_kind: str,
    result: str,
    network_element_type: str | None,
    record_id: str,
    source_table: str,
) -> KpiLegacyRecoveryAudit:
    return KpiLegacyRecoveryAudit(
        source_table=source_table,
        source_record_id=record_id,
        source_key=source_key,
        network_element_type=network_element_type,
        measurement_unit_id="MU_MEDIA_CALL",
        metric_resource_id="ME_MEDIA_CREATION_SUCCESS_RATE",
        object_kind=object_kind,
        before_snapshot={"enabled": False, "record_id": record_id},
        result=result,
        error_code="migration_row_error" if result == "failed" else None,
        attempt_count=0,
        actor=None,
        source="migration",
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_measurement_unit_is_only_scope_switch_and_counts_current_definitions(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        session.add(
            KpiV6MeasurementResource(
                network_element_type="UMF",
                resource_id="ME_DERIVED_SCOPE_TEST",
                kind="me",
                name_zh="范围测试派生指标",
                name_en="Scope Test Derived",
                source="manual",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_DERIVED_SCOPE_TEST",
                numerator_metric_id=seed.metric_resource_ids[0],
                denominator_metric_id=seed.metric_resource_ids[1],
                template="success_rate",
                definition_state="defined",
                revision=0,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MeasurementBinding(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                raw_source_name="待修正异常列",
                base_source_name="待修正异常列",
                metric_resource_id=None,
                binding_state="candidate",
                source_file="scope.csv",
                origin_task_id=seed.task_id,
                revision=0,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    listed = kpi_measurement_scope.list_measurement_units(
        "UMF",
        search="媒体与数据通道",
        page=1,
        page_size=20,
    )
    assert listed.total == 1
    unit = listed.items[0]
    assert unit.base_metric_count == 20
    assert unit.derived_metric_count == 1
    assert unit.confirmed_binding_count == 20
    assert unit.candidate_binding_count == 1
    assert unit.inspection_enabled is True

    before_scope = kpi_measurement_scope.resolve_measurement_scope("UMF")
    assert len(before_scope) == 21
    assert {item.metric_kind for item in before_scope} == {"base", "derived"}

    disabled = kpi_measurement_scope.set_measurement_inspection_enabled(
        "UMF",
        seed.measurement_unit_id,
        _patch(False, unit.revision),
        actor=_ADMIN,
    )
    assert disabled.inspection_enabled is False
    assert disabled.revision == unit.revision + 1
    assert disabled.notice == "只影响后续巡检，现有配置、团队关注和历史结果保留"
    assert kpi_measurement_scope.resolve_measurement_scope("UMF") == []

    with session_factory() as session:
        snapshot = session.get(TaskKpiScopeSnapshot, seed.task_id)
        assert snapshot is not None
        assert snapshot.snapshot_payload["enabled_measurement_unit_ids"] == [seed.measurement_unit_id]
        assert snapshot.snapshot_payload["metric_count"] == 20
        confirmed = (
            session.query(KpiV6MeasurementBinding)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                binding_state="confirmed",
            )
            .all()
        )
        assert len(confirmed) == 22
        assert {binding.metric_resource_id for binding in confirmed} == set(seed.metric_resource_ids)
        assert session.query(KpiV6MeasurementDerived).count() == 1

    reenabled = kpi_measurement_scope.set_measurement_inspection_enabled(
        "UMF",
        seed.measurement_unit_id,
        _patch(True, disabled.revision),
        actor=_ADMIN,
    )
    assert reenabled.inspection_enabled is True
    assert reenabled.base_metric_count == 20
    assert reenabled.derived_metric_count == 1
    assert len(kpi_measurement_scope.resolve_measurement_scope("UMF")) == 21


def test_revision_conflict_and_incomplete_configuration_are_visible(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        config = (
            session.query(KpiV6MetricMaintenanceConfig)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=seed.metric_resource_ids[0],
            )
            .one()
        )
        config.config_state = "incomplete"
        config.warning_threshold = None
        config.critical_threshold = None
        session.commit()

    page = kpi_measurement_scope.list_measurement_units(
        "UMF",
        configuration_state=schemas.KpiConfigurationState.INCOMPLETE,
        page_size=20,
    )
    assert page.total == 1
    assert page.items[0].configuration_state is schemas.KpiConfigurationState.INCOMPLETE
    assert page.items[0].base_metric_count == 20
    assert len(kpi_measurement_scope.resolve_measurement_scope("UMF")) == 20

    with pytest.raises(kpi_measurement_scope.KpiMeasurementScopeError) as exc_info:
        kpi_measurement_scope.set_measurement_inspection_enabled(
            "UMF",
            seed.measurement_unit_id,
            _patch(False, page.items[0].revision + 1),
            actor=_ADMIN,
        )
    assert exc_info.value.code == "kpi_measurement_unit_revision_conflict"
    assert exc_info.value.status_code == 409


def test_recovery_retry_is_per_object_partial_success_and_idempotent(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        success = _audit(
            source_key="recovery:test-success",
            object_kind="metric",
            result="failed",
            network_element_type="UMF",
            record_id=seed.metric_resource_ids[0],
            source_table="kpi_measurement_resources",
        )
        failure = _audit(
            source_key="recovery:test-failure",
            object_kind="binding",
            result="pending",
            network_element_type=None,
            record_id="999999",
            source_table="kpi_measurement_bindings",
        )
        session.add_all([success, failure])
        session.commit()
        success_id = success.id
        failure_id = failure.id

    body = schemas.KpiLegacyRecoveryRetryRequestV6(
        audit_ids=[success_id, failure_id],
        idempotency_key="retry-scope-operation-001",
    )
    accepted = kpi_measurement_scope.retry_legacy_recovery(body, actor=_ADMIN)
    operation = kpi_measurement_scope.get_maintenance_operation(accepted.operation_id)
    assert operation.status == "partial_success"
    assert operation.succeeded_count == 1
    assert operation.failed_count == 1
    assert operation.pending_count == 0
    assert {item.target_id: item.result for item in operation.items} == {
        str(success_id): "succeeded",
        str(failure_id): "failed",
    }

    with session_factory() as session:
        success_audit = session.get(KpiLegacyRecoveryAudit, success_id)
        failed_audit = session.get(KpiLegacyRecoveryAudit, failure_id)
        assert success_audit is not None and success_audit.result == "recovered"
        assert success_audit.attempt_count == 1
        assert failed_audit is not None and failed_audit.result == "failed"
        assert failed_audit.attempt_count == 1
        assert failed_audit.error_code == "kpi_recovery_network_element_type_missing"

    duplicate = kpi_measurement_scope.retry_legacy_recovery(body, actor=_ADMIN)
    assert duplicate.operation_id == accepted.operation_id

    with pytest.raises(kpi_measurement_scope.KpiMeasurementScopeError) as exc_info:
        kpi_measurement_scope.retry_legacy_recovery(
            schemas.KpiLegacyRecoveryRetryRequestV6(
                audit_ids=[failure_id],
                idempotency_key=body.idempotency_key,
            ),
            actor=_ADMIN,
        )
    assert exc_info.value.code == "kpi_maintenance_operation_idempotency_conflict"
    assert exc_info.value.status_code == 409


def test_retry_rejects_audits_outside_retryable_states(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        recovered = _audit(
            source_key="recovery:already-complete",
            object_kind="metric",
            result="recovered",
            network_element_type="UMF",
            record_id=seed.metric_resource_ids[0],
            source_table="kpi_measurement_resources",
        )
        session.add(recovered)
        session.commit()
        audit_id = recovered.id

    with pytest.raises(kpi_measurement_scope.KpiMeasurementScopeError) as exc_info:
        kpi_measurement_scope.retry_legacy_recovery(
            schemas.KpiLegacyRecoveryRetryRequestV6(
                audit_ids=[audit_id],
                idempotency_key="retry-scope-invalid-001",
            ),
            actor=_ADMIN,
        )
    assert exc_info.value.code == "kpi_maintenance_target_invalid"
    assert exc_info.value.status_code == 400


def test_binding_single_correction_uses_revision_and_never_batch_confirms(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        candidate = KpiV6MeasurementBinding(
            network_element_type="UMF",
            measurement_unit_id=seed.measurement_unit_id,
            raw_source_name="待人工确认来源列",
            base_source_name="待人工确认来源列",
            metric_resource_id=seed.metric_resource_ids[0],
            binding_state="candidate",
            source_file="scope.csv",
            origin_task_id=seed.task_id,
            revision=3,
            created_at=_NOW,
            updated_at=_NOW,
        )
        conflict = KpiV6MeasurementBinding(
            network_element_type="UMF",
            measurement_unit_id=seed.measurement_unit_id,
            raw_source_name="冲突来源列",
            base_source_name="冲突来源列",
            metric_resource_id=None,
            binding_state="conflict",
            source_file="scope.csv",
            origin_task_id=seed.task_id,
            revision=2,
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add_all([candidate, conflict])
        session.commit()
        candidate_id = candidate.id
        conflict_id = conflict.id

    confirmed = kpi_measurement_scope.correct_measurement_binding(
        "UMF",
        candidate_id,
        _binding_patch(3, "confirmed"),
        actor=_ADMIN,
    )
    assert confirmed.status is schemas.KpiBindingState.CONFIRMED
    assert confirmed.revision == 4

    ignored = kpi_measurement_scope.correct_measurement_binding(
        "UMF",
        conflict_id,
        _binding_patch(2, "ignored"),
        actor=_ADMIN,
    )
    assert ignored.status is schemas.KpiBindingState.IGNORED
    assert ignored.revision == 3

    with pytest.raises(kpi_measurement_scope.KpiMeasurementScopeError) as exc_info:
        kpi_measurement_scope.correct_measurement_binding(
            "UMF",
            candidate_id,
            _binding_patch(4, "ignored"),
            actor=_ADMIN,
        )
    assert exc_info.value.code == "kpi_binding_not_correctable"
    assert exc_info.value.status_code == 400


def test_pending_attribution_stays_out_of_scope_until_resolved(kpi_v6_seed) -> None:
    with session_factory() as session:
        pending = KpiPendingAttribution(
            source_table="kpi_measurement_resources",
            source_record_id="ME_PENDING_MEDIA",
            source_key="pending:kpi_measurement_resources:ME_PENDING_MEDIA",
            source_payload={
                "resource_id": "ME_PENDING_MEDIA",
                "kind": "me",
                "name_zh": "待归属媒体指标",
                "name_en": "Pending Media Metric",
                "enabled": False,
                "origin_task_id": None,
            },
            candidate_network_element_types=["UMF", "CSP"],
            reason="ambiguous_product",
            resolution_state="pending",
            attempt_count=0,
            last_error=None,
            idempotency_key="pending-migration-key-001",
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(pending)
        session.commit()
        pending_id = pending.id

    before = kpi_measurement_scope.list_pending_attributions(page=1, page_size=20)
    assert before.total == 1
    assert before.items[0].assigned_network_element_type is None
    assert all(
        item.metric_resource_id != "ME_PENDING_MEDIA" for item in kpi_measurement_scope.resolve_measurement_scope("UMF")
    )

    accepted = kpi_measurement_scope.resolve_pending_attribution(
        pending_id,
        schemas.KpiPendingAttributionResolveRequestV6(
            network_element_type="UMF",
            idempotency_key="resolve-pending-operation-001",
        ),
        actor=_ADMIN,
    )
    operation = kpi_measurement_scope.get_maintenance_operation(accepted.operation_id)
    assert operation.status == "succeeded"
    assert operation.succeeded_count == 1

    with session_factory() as session:
        stored = session.get(KpiPendingAttribution, pending_id)
        assert stored is not None
        assert stored.resolution_state == "materialized"
        assert stored.assigned_network_element_type == "UMF"
        assert stored.attempt_count == 1
        materialized = (
            session.query(KpiV6MeasurementResource)
            .filter_by(network_element_type="UMF", resource_id="ME_PENDING_MEDIA")
            .one()
        )
        assert materialized.kind == "me"


def test_confirmed_base_metric_excludes_conflicting_derived_definition(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    with session_factory() as session:
        session.add(
            KpiV6MeasurementDerived(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=metric_id,
                numerator_metric_id=seed.metric_resource_ids[0],
                denominator_metric_id=seed.metric_resource_ids[1],
                template="success_rate",
                definition_state="defined",
                revision=1,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    listed = kpi_measurement_scope.get_measurement_unit("UMF", seed.measurement_unit_id)
    assert listed.base_metric_count == 20
    assert listed.derived_metric_count == 0

    resolved = [
        item for item in kpi_measurement_scope.resolve_measurement_scope("UMF") if item.metric_resource_id == metric_id
    ]
    assert resolved == [
        kpi_measurement_scope.MeasurementScopeItem(
            measurement_unit_id=seed.measurement_unit_id,
            metric_resource_id=metric_id,
            metric_kind="base",
        )
    ]


def test_pending_derived_definition_cannot_shadow_confirmed_base_metric(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    with session_factory() as session:
        pending = KpiPendingAttribution(
            source_table="kpi_measurement_derived",
            source_record_id="legacy-derived-media-rate",
            source_key="pending:kpi_measurement_derived:legacy-derived-media-rate",
            source_payload={
                "measurement_unit_id": seed.measurement_unit_id,
                "metric_resource_id": metric_id,
                "numerator_metric_id": seed.metric_resource_ids[0],
                "denominator_metric_id": seed.metric_resource_ids[1],
                "template": "success_rate",
            },
            candidate_network_element_types=["UMF"],
            reason="ambiguous_product",
            resolution_state="pending",
            attempt_count=0,
            last_error=None,
            idempotency_key="pending-derived-media-rate-key",
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(pending)
        session.commit()
        pending_id = pending.id

    accepted = kpi_measurement_scope.resolve_pending_attribution(
        pending_id,
        schemas.KpiPendingAttributionResolveRequestV6(
            network_element_type="UMF",
            idempotency_key="resolve-derived-media-rate-operation",
        ),
        actor=_ADMIN,
    )
    operation = kpi_measurement_scope.get_maintenance_operation(accepted.operation_id)

    assert operation.status == "failed"
    assert operation.failed_count == 1
    assert operation.items[0].error_code == "kpi_pending_materialization_failed"
    assert operation.items[0].error_message == "派生指标不能覆盖已确认的源包指标"
    with session_factory() as session:
        assert (
            session.query(KpiV6MeasurementDerived)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=metric_id,
            )
            .count()
            == 0
        )


def test_scope_requires_unique_unit_identity_and_does_not_create_public_scope(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(network_element_type="UMF", measurement_unit_id=seed.measurement_unit_id)
            .one()
        )
        csp_unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(network_element_type="CSP", measurement_unit_id=unit.measurement_unit_id)
            .one()
        )
        csp_unit.name_zh = "同名 CSP 测量单元"
        csp_unit.name_en = "Same ID CSP Unit"
        session.query(KpiV6MeasurementBinding).filter_by(
            network_element_type="CSP",
            measurement_unit_id=csp_unit.measurement_unit_id,
        ).delete(synchronize_session=False)
        session.commit()

    umf = kpi_measurement_scope.get_measurement_unit("UMF", seed.measurement_unit_id)
    csp = kpi_measurement_scope.get_measurement_unit("CSP", seed.measurement_unit_id)
    assert umf.name_zh == "媒体与数据通道呼叫统计"
    assert csp.name_zh == "同名 CSP 测量单元"
    assert umf.base_metric_count == 20
    assert csp.base_metric_count == 0

    with pytest.raises(kpi_measurement_scope.KpiMeasurementScopeError) as exc_info:
        kpi_measurement_scope.get_measurement_unit("PUBLIC", seed.measurement_unit_id)
    assert exc_info.value.code == "kpi_measurement_unit_not_found"
    assert exc_info.value.status_code == 404


def test_measurement_scope_api_wires_status_codes_location_and_domain_errors(kpi_v6_seed) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    seed = kpi_v6_seed.umf
    client = TestClient(app)

    listed = client.get(
        "/api/v6/kpi/measurement-units",
        params={"network_element_type": "UMF", "page_size": 20},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    unit = listed.json()["items"][0]

    disabled = client.patch(
        f"/api/v6/kpi/measurement-units/UMF/{seed.measurement_unit_id}",
        json={"expected_revision": unit["revision"], "inspection_enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["inspection_enabled"] is False

    stale = client.patch(
        f"/api/v6/kpi/measurement-units/UMF/{seed.measurement_unit_id}",
        json={"expected_revision": unit["revision"], "inspection_enabled": True},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "kpi_measurement_unit_revision_conflict"

    with session_factory() as session:
        audit = _audit(
            source_key="recovery:api-location",
            object_kind="metric",
            result="failed",
            network_element_type="UMF",
            record_id=seed.metric_resource_ids[0],
            source_table="kpi_measurement_resources",
        )
        session.add(audit)
        session.commit()
        audit_id = audit.id

    retried = client.post(
        "/api/v6/kpi/legacy-recovery-audits/retry",
        json={"audit_ids": [audit_id], "idempotency_key": "api-retry-location-001"},
    )
    assert retried.status_code == 202
    operation_id = retried.json()["operation_id"]
    assert retried.headers["Location"] == f"/api/v6/kpi/maintenance-operations/{operation_id}"
    operation = client.get(f"/api/v6/kpi/maintenance-operations/{operation_id}")
    assert operation.status_code == 200
    assert operation.json()["status"] == "succeeded"
