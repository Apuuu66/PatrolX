"""041 US6：任务启动时冻结 KPI 有效范围。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.models.db import (
    KpiTeamFocusItem,
    KpiTeamFocusRevision,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    session_factory,
)
from app.services import task_db
from app.services.kpi_scope import KpiScopeResolver

_NOW = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
_DATA_DATE = date(2026, 11, 5)


def _resolve_snapshot(seed: Any) -> task_db.KpiScopeSnapshotData:
    return KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        data_date=_DATA_DATE,
        now=_NOW,
    )


def _rule_snapshot(seed: Any) -> task_db.RuleScopeSnapshotData:
    return task_db.RuleScopeSnapshotData(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        assignment_revision=3,
        registry_fingerprint="a" * 64,
        trigger="api",
        source="task_service",
        frozen_at=_NOW,
        snapshot_state="frozen",
        items=(
            task_db.RuleScopeItemData(
                rule_code="kpi.measurement_units",
                rule_version="1.2.0",
                category="kpi",
                priority=1,
                execution_order=20,
                assignment_snapshot={"network_element_types": [seed.network_element_type]},
            ),
        ),
    )


def test_resolve_freezes_enabled_confirmed_base_metrics(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf

    snapshot = KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        data_date=_DATA_DATE,
        now=_NOW,
    )

    assert snapshot.task_id == seed.task_id
    assert snapshot.network_element_type == "UMF"
    assert snapshot.data_date == _DATA_DATE
    assert snapshot.team_focus_revision == seed.team_focus_revision
    assert snapshot.snapshot_payload["enabled_measurement_unit_ids"] == [seed.measurement_unit_id]
    assert snapshot.snapshot_payload["metric_count"] == 20
    assert snapshot.snapshot_payload["base_metric_count"] == 20
    assert snapshot.snapshot_payload["derived_metric_count"] == 0
    assert len(snapshot.items) == 20
    assert {item.metric_kind for item in snapshot.items} == {"base"}
    assert {item.metric_resource_id for item in snapshot.items} == set(seed.metric_resource_ids)
    assert {item.scope_status for item in snapshot.items} == {"ready"}
    assert all(item.measurement_unit_id == seed.measurement_unit_id for item in snapshot.items)
    assert all(item.config_snapshot["raw_source_names"] for item in snapshot.items)
    assert all(isinstance(item.config_snapshot["config_fingerprint"], str) for item in snapshot.items)


def test_resolve_freezes_defined_derived_metric_with_its_formula(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    numerator, denominator = seed.metric_resource_ids[:2]
    with session_factory() as session:
        session.add(
            KpiV6MeasurementResource(
                network_element_type="UMF",
                resource_id="ME_SCOPE_DERIVED",
                kind="me",
                name_zh="范围派生指标",
                name_en="Scope Derived",
                importance="P1",
                source="manual",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_SCOPE_DERIVED",
                numerator_metric_id=numerator,
                denominator_metric_id=denominator,
                template="success_rate",
                definition_state="defined",
                revision=3,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MetricMaintenanceConfig(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_SCOPE_DERIVED",
                role="derived",
                daily_aggregation="latest",
                is_percentage=True,
                config_state="ready",
                revision=4,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    snapshot = KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        data_date=_DATA_DATE,
        now=_NOW,
    )

    derived = next(item for item in snapshot.items if item.metric_resource_id == "ME_SCOPE_DERIVED")
    assert derived.metric_kind == "derived"
    assert derived.config_snapshot["role"] == "derived"
    assert derived.config_snapshot["numerator_metric_id"] == numerator
    assert derived.config_snapshot["denominator_metric_id"] == denominator
    assert derived.config_snapshot["template"] == "success_rate"
    assert derived.config_snapshot["definition_revision"] == 3
    assert derived.config_snapshot["formula"] == "numerator_sum / denominator_sum * 100"
    assert snapshot.snapshot_payload["base_metric_count"] == 20
    assert snapshot.snapshot_payload["derived_metric_count"] == 1
    assert snapshot.snapshot_payload["metric_count"] == 21


def test_resolve_defaults_derived_percentage_to_false_without_explicit_config(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    numerator, denominator = seed.metric_resource_ids[:2]
    with session_factory() as session:
        base_percentage_row = (
            session.query(KpiV6MetricMaintenanceConfig.metric_resource_id)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                is_percentage=True,
            )
            .order_by(KpiV6MetricMaintenanceConfig.metric_resource_id)
            .first()
        )
    base_percentage_metric_id = base_percentage_row[0] if base_percentage_row is not None else None
    assert base_percentage_metric_id is not None
    with session_factory() as session:
        session.add(
            KpiV6MeasurementResource(
                network_element_type="UMF",
                resource_id="ME_SCOPE_DERIVED_NO_PERCENT_CONFIG",
                kind="me",
                name_zh="未配置百分比的派生指标",
                name_en="Derived Ratio Without Percentage Config",
                importance="P1",
                source="manual",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_SCOPE_DERIVED_NO_PERCENT_CONFIG",
                numerator_metric_id=numerator,
                denominator_metric_id=denominator,
                template="success_rate",
                definition_state="defined",
                revision=1,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    snapshot = _resolve_snapshot(seed)

    base = next(item for item in snapshot.items if item.metric_resource_id == base_percentage_metric_id)
    derived = next(item for item in snapshot.items if item.metric_resource_id == "ME_SCOPE_DERIVED_NO_PERCENT_CONFIG")
    assert base.metric_kind == "base"
    assert base.config_snapshot["is_percentage"] is True
    assert derived.metric_kind == "derived"
    assert derived.config_snapshot["role"] == "derived"
    assert derived.config_snapshot["is_percentage"] is False
    assert derived.config_snapshot["display_units"] == []


def test_resolve_uses_measurement_unit_inspection_switch_as_only_scope_gate(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    enabled_snapshot = _resolve_snapshot(seed)
    with session_factory() as session:
        unit = (
            session.query(KpiV6MeasurementUnit)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
            )
            .one()
        )
        unit.inspection_enabled = False
        session.commit()

    snapshot = KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        data_date=_DATA_DATE,
        now=_NOW,
    )

    assert snapshot.items == ()
    assert snapshot.snapshot_payload["enabled_measurement_unit_ids"] == []
    assert snapshot.snapshot_payload["metric_count"] == 0
    assert snapshot.config_fingerprint != enabled_snapshot.config_fingerprint


def test_resolve_excludes_unconfirmed_conflicting_and_undefined_metrics(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        for metric_id, state in (
            ("ME_SCOPE_CANDIDATE", "candidate"),
            ("ME_SCOPE_CONFLICT", "conflict"),
            ("ME_SCOPE_IGNORED", "ignored"),
        ):
            session.add(
                KpiV6MeasurementResource(
                    network_element_type="UMF",
                    resource_id=metric_id,
                    kind="me",
                    name_zh=metric_id,
                    name_en=metric_id,
                    source="discovered",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            session.add(
                KpiV6MeasurementBinding(
                    network_element_type="UMF",
                    measurement_unit_id=seed.measurement_unit_id,
                    raw_source_name=f"{metric_id}_RAW",
                    base_source_name=f"{metric_id}_RAW",
                    metric_resource_id=metric_id,
                    binding_state=state,
                    source_file="unconfirmed.csv",
                    origin_task_id=seed.task_id,
                    revision=0,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
        session.add(
            KpiV6MeasurementResource(
                network_element_type="UMF",
                resource_id="ME_SCOPE_DRAFT_DERIVED",
                kind="me",
                name_zh="草稿派生指标",
                name_en="Draft Derived",
                source="manual",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_SCOPE_DRAFT_DERIVED",
                numerator_metric_id=seed.metric_resource_ids[0],
                denominator_metric_id=seed.metric_resource_ids[1],
                template="success_rate",
                definition_state="draft",
                revision=0,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    snapshot = KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        now=_NOW,
    )

    assert {item.metric_resource_id for item in snapshot.items} == set(seed.metric_resource_ids)
    assert snapshot.snapshot_payload["metric_count"] == 20


def test_media_resource_success_rate_remains_source_backed_base_metric(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf

    snapshot = KpiScopeResolver().resolve(
        task_id=seed.task_id,
        network_element_type=seed.network_element_type,
        now=_NOW,
    )

    item = next(item for item in snapshot.items if item.metric_resource_id == "ME_MEDIA_CREATION_SUCCESS_RATE")
    assert item.metric_kind == "base"
    assert item.config_snapshot["role"] == "base"
    assert item.config_snapshot["raw_source_names"] == [
        "Media Resource Creation Requests Success Rate(%)",
        "Media Resource Creation Success Rate(%)",
    ]
    assert item.config_snapshot.get("formula") is None
    assert item.config_snapshot.get("numerator_metric_id") is None
    assert item.config_snapshot.get("denominator_metric_id") is None


def test_confirmed_source_metric_takes_precedence_over_conflicting_derived_definition(
    kpi_v6_seed,
) -> None:
    seed = kpi_v6_seed.umf
    with session_factory() as session:
        session.add(
            KpiV6MeasurementDerived(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id="ME_MEDIA_CREATION_SUCCESS_RATE",
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

    snapshot = _resolve_snapshot(seed)

    media_items = [item for item in snapshot.items if item.metric_resource_id == "ME_MEDIA_CREATION_SUCCESS_RATE"]
    assert len(media_items) == 1
    item = media_items[0]
    assert item.metric_kind == "base"
    assert item.config_snapshot["role"] == "base"
    assert item.config_snapshot.get("formula") is None
    assert item.config_snapshot.get("numerator_metric_id") is None
    assert item.config_snapshot.get("denominator_metric_id") is None
    assert snapshot.snapshot_payload["base_metric_count"] == 20
    assert snapshot.snapshot_payload["derived_metric_count"] == 0


def test_incomplete_maintenance_config_remains_in_scope_as_needs_config(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    metric_id = seed.metric_resource_ids[0]
    with session_factory() as session:
        config = (
            session.query(KpiV6MetricMaintenanceConfig)
            .filter_by(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=metric_id,
            )
            .one()
        )
        config.config_state = "incomplete"
        config.revision += 1
        session.commit()

    snapshot = _resolve_snapshot(seed)

    item = next(item for item in snapshot.items if item.metric_resource_id == metric_id)
    assert item.config_snapshot["config_state"] == "incomplete"
    assert item.scope_status == "needs_config"


def test_config_fingerprint_is_stable_for_unchanged_configuration(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf

    first = _resolve_snapshot(seed)
    second = _resolve_snapshot(seed)

    assert first.config_fingerprint == second.config_fingerprint
    assert first.items == second.items


def test_saved_snapshot_is_unchanged_after_live_configuration_changes(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    metric_id = seed.metric_resource_ids[0]
    frozen = _resolve_snapshot(seed)
    task_db.save_task_scope_snapshots(
        rule_snapshot=_rule_snapshot(seed),
        kpi_snapshot=frozen,
    )

    with session_factory() as session:
        config = (
            session.query(KpiV6MetricMaintenanceConfig)
            .filter_by(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=metric_id,
            )
            .one()
        )
        config.warning_threshold = 77.7
        config.revision += 1
        session.commit()

    loaded = task_db.get_kpi_scope_snapshot(
        seed.task_id,
        network_element_type=seed.network_element_type,
    )
    current = _resolve_snapshot(seed)

    assert loaded == frozen
    current_item = next(item for item in current.items if item.metric_resource_id == metric_id)
    assert current_item.config_snapshot["warning_threshold"] == 77.7
    assert current.config_fingerprint != frozen.config_fingerprint


def test_config_fingerprint_changes_when_binding_or_maintenance_configuration_changes(
    kpi_v6_seed,
) -> None:
    seed = kpi_v6_seed.umf
    binding_metric_id = seed.metric_resource_ids[0]
    maintenance_metric_id = seed.metric_resource_ids[1]
    initial = _resolve_snapshot(seed)

    with session_factory() as session:
        binding = (
            session.query(KpiV6MeasurementBinding)
            .filter_by(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=binding_metric_id,
            )
            .first()
        )
        assert binding is not None
        binding.binding_state = "candidate"
        binding.revision += 1
        config = (
            session.query(KpiV6MetricMaintenanceConfig)
            .filter_by(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
                metric_resource_id=maintenance_metric_id,
            )
            .one()
        )
        config.warning_threshold = 88.8
        config.revision += 1
        session.commit()

    changed = _resolve_snapshot(seed)

    assert changed.config_fingerprint != initial.config_fingerprint
    assert binding_metric_id not in {item.metric_resource_id for item in changed.items}
    maintenance_item = next(item for item in changed.items if item.metric_resource_id == maintenance_metric_id)
    assert maintenance_item.config_snapshot["warning_threshold"] == 88.8


def test_team_focus_changes_do_not_change_task_execution_scope_or_fingerprint(kpi_v6_seed) -> None:
    seed = kpi_v6_seed.umf
    initial = _resolve_snapshot(seed)

    with session_factory() as session:
        removed = (
            session.query(KpiTeamFocusItem)
            .filter_by(
                network_element_type=seed.network_element_type,
                measurement_unit_id=seed.measurement_unit_id,
            )
            .order_by(KpiTeamFocusItem.metric_resource_id)
            .first()
        )
        assert removed is not None
        session.delete(removed)
        revision = session.get(KpiTeamFocusRevision, seed.network_element_type)
        assert revision is not None
        revision.revision += 1
        session.commit()

    changed = _resolve_snapshot(seed)

    assert changed.config_fingerprint == initial.config_fingerprint
    assert changed.items == initial.items
    assert {item.metric_resource_id for item in changed.items} == {item.metric_resource_id for item in initial.items}
    assert changed.team_focus_revision == initial.team_focus_revision + 1
    assert changed.snapshot_payload["team_focus_count"] == initial.snapshot_payload["team_focus_count"] - 1


def test_resolve_without_network_element_type_returns_empty_scope(kpi_v6_seed) -> None:
    snapshot = KpiScopeResolver().resolve(
        task_id="log-supplement-task",
        network_element_type=None,
        data_date=_DATA_DATE,
        now=_NOW,
    )

    assert snapshot.network_element_type is None
    assert snapshot.items == ()
    assert snapshot.snapshot_payload["metric_count"] == 0
    assert snapshot.snapshot_payload["enabled_measurement_unit_ids"] == []


@pytest.mark.parametrize("network_element_type", ["COMMON", "PUBLIC", "UNKNOWN"])
def test_resolve_rejects_public_or_unknown_network_element_type(network_element_type: str) -> None:
    from app.services.kpi_scope import KpiScopeError

    with pytest.raises(KpiScopeError) as error:
        KpiScopeResolver().resolve(
            task_id="invalid-scope-task",
            network_element_type=network_element_type,
            now=_NOW,
        )

    assert error.value.code == "invalid_network_element_type"
