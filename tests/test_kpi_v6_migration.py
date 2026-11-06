"""041 KPI v6 表结构、幂等迁移与历史恢复审计。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

import app.models.db as db_module
import app.services.kpi_v6_migration as migration_module
import app.services.task_db as task_db_module
from app.core.config import settings
from app.models.db import (
    KpiLegacyRecoveryAudit,
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    KpiPendingAttribution,
    KpiRuleAssignmentGlobalState,
    KpiRuleAssignmentState,
    KpiTeamFocusItem,
    KpiTeamFocusRevision,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    TaskKpiScopeSnapshot,
    TaskRecord,
    TaskRuleScopeSnapshot,
    init_db,
    session_factory,
)
from app.services.kpi_v6_migration import migrate_kpi_v6

NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
V6_TABLES = {
    "kpi_v6_measurement_resources",
    "kpi_v6_measurement_units",
    "kpi_v6_measurement_bindings",
    "kpi_v6_measurement_derived",
    "kpi_v6_metric_maintenance_configs",
    "kpi_team_focus_revisions",
    "kpi_team_focus_items",
    "kpi_rule_assignment_states",
    "kpi_rule_network_assignments",
    "kpi_rule_assignment_global_state",
    "kpi_rule_assignment_audits",
    "task_rule_scope_snapshots",
    "task_rule_scope_items",
    "task_kpi_scope_snapshots",
    "task_kpi_scope_items",
    "task_kpi_metric_results_v6",
    "task_kpi_points_v6",
    "kpi_legacy_recovery_audits",
    "kpi_pending_attributions",
    "kpi_maintenance_operations",
}


def _task(task_id: str, product: str | None) -> TaskRecord:
    customer = {} if product is None else {"product": product}
    return TaskRecord(
        task_id=task_id,
        name=task_id,
        mode="online",
        status="completed",
        trigger="api",
        package_file=f"{task_id}.zip",
        customer=customer,
        package_kind="inspection",
        stats={},
        created_at=NOW,
    )


def _seed_v5_configuration() -> None:
    with session_factory() as session:
        session.add_all([_task("task-umf", "UMF"), _task("task-csp", "CSP"), _task("task-none", None)])

        unit = KpiMeasurementResource(
            resource_id="MU_CALL",
            kind="mu",
            name_zh="呼叫测量单元",
            name_en="Call Measurement Unit",
            enabled=True,
            source="discovered",
            origin_task_id="task-umf",
            created_at=NOW,
            updated_at=NOW,
        )
        metric = KpiMeasurementResource(
            resource_id="ME_MEDIA_CREATE_RATE",
            kind="me",
            name_zh="媒体资源创建成功率",
            name_en="Media Resource Creation Success Rate",
            enabled=False,
            source="discovered",
            origin_task_id="task-umf",
            created_at=NOW,
            updated_at=NOW,
        )
        ambiguous_metric = KpiMeasurementResource(
            resource_id="ME_AMBIGUOUS",
            kind="me",
            name_zh="跨类型歧义指标",
            name_en="Ambiguous Metric",
            enabled=False,
            source="discovered",
            origin_task_id=None,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([unit, metric, ambiguous_metric])

        session.add_all(
            [
                KpiMeasurementBinding(
                    measurement_unit_id="MU_CALL",
                    metric_resource_id="ME_MEDIA_CREATE_RATE",
                    raw_source_name="Media Resource Creation Requests Success Rate(%)",
                    base_source_name="Media Resource Creation Requests Success Rate(%)",
                    display_unit="%",
                    status="confirmed",
                    enabled=False,
                    task_id="task-umf",
                    source_file="call_kpi.csv",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementBinding(
                    measurement_unit_id="MU_AMBIGUOUS",
                    metric_resource_id="ME_AMBIGUOUS",
                    raw_source_name="Ambiguous UMF Column",
                    base_source_name="Ambiguous UMF Column",
                    status="confirmed",
                    enabled=True,
                    task_id="task-umf",
                    source_file="umf.csv",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementBinding(
                    measurement_unit_id="MU_AMBIGUOUS",
                    metric_resource_id="ME_AMBIGUOUS",
                    raw_source_name="Ambiguous CSP Column",
                    base_source_name="Ambiguous CSP Column",
                    status="confirmed",
                    enabled=True,
                    task_id="task-csp",
                    source_file="csp.csv",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementDerived(
                    measurement_unit_id="MU_CALL",
                    metric_resource_id="ME_LEGACY_DERIVED",
                    numerator_metric_id="ME_SUCCESS",
                    denominator_metric_id="ME_REQUESTS",
                    template="success_rate",
                    enabled=False,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMetricMaintenanceConfig(
                    measurement_unit_id="MU_CALL",
                    metric_resource_id="ME_MEDIA_CREATE_RATE",
                    role="base",
                    daily_aggregation="latest",
                    daily_change_threshold_unit="auto",
                    is_percentage=True,
                    zero_semantics="unknown",
                    consistency_tolerance=0.2,
                    object_match_mode="exact",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()


def test_v6_tables_are_created_idempotently_and_type_scoped_keys_are_unique(isolated_db: Path) -> None:
    init_db()
    engine = session_factory().get_bind()
    table_names = set(inspect(engine).get_table_names())
    assert V6_TABLES <= table_names
    with session_factory() as session:
        revisions = {row.network_element_type: row.revision for row in session.query(KpiTeamFocusRevision).all()}
        assert revisions == {"UMF": 0, "CSP": 0}
        global_state = session.get(KpiRuleAssignmentGlobalState, 1)
        assert global_state is not None
        assert global_state.revision == 0

    with session_factory() as session:
        session.add_all(
            [
                KpiV6MeasurementResource(
                    network_element_type="UMF",
                    resource_id="ME_SHARED",
                    kind="me",
                    name_zh="共享指标",
                    name_en="Shared Metric",
                    source="manual",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiV6MeasurementResource(
                    network_element_type="CSP",
                    resource_id="ME_SHARED",
                    kind="me",
                    name_zh="共享指标",
                    name_en="Shared Metric",
                    source="manual",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

    with session_factory() as session:
        session.add(
            KpiV6MeasurementResource(
                network_element_type="UMF",
                resource_id="ME_SHARED",
                kind="me",
                name_zh="重复指标",
                name_en="Duplicate Metric",
                source="manual",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_migration_maps_only_unique_v5_scope_and_queues_ambiguous_rows(isolated_db: Path) -> None:
    _seed_v5_configuration()
    migrate_kpi_v6()
    migrate_kpi_v6()

    with session_factory() as session:
        umf_bindings = session.query(KpiV6MeasurementResource).filter_by(network_element_type="UMF").all()
        assert {row.resource_id for row in umf_bindings} >= {"MU_CALL", "ME_MEDIA_CREATE_RATE"}
        assert session.query(KpiV6MeasurementResource).filter_by(resource_id="MU_CALL").count() == 1

        binding = (
            session.query(KpiV6MeasurementBinding)
            .filter_by(measurement_unit_id="MU_CALL", metric_resource_id="ME_MEDIA_CREATE_RATE")
            .one()
        )
        assert binding.network_element_type == "UMF"
        assert binding.binding_state == "confirmed"
        assert session.query(KpiV6MeasurementBinding).filter_by(measurement_unit_id="MU_AMBIGUOUS").count() == 0

        maintenance = (
            session.query(KpiV6MetricMaintenanceConfig)
            .filter_by(measurement_unit_id="MU_CALL", metric_resource_id="ME_MEDIA_CREATE_RATE")
            .one()
        )
        assert maintenance.network_element_type == "UMF"
        assert maintenance.role == "base"
        assert maintenance.is_percentage is True

        pending = session.query(KpiPendingAttribution).all()
        assert any(row.source_payload.get("measurement_unit_id") == "MU_AMBIGUOUS" for row in pending)
        assert len(pending) == len({row.source_key for row in pending})


def test_migration_skips_derived_definition_that_shadows_confirmed_base(
    isolated_db: Path,
) -> None:
    _seed_v5_configuration()
    with session_factory() as session:
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id="ME_SUCCESS",
                    kind="me",
                    name_zh="成功响应数",
                    name_en="Successful Responses",
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementResource(
                    resource_id="ME_REQUESTS",
                    kind="me",
                    name_zh="请求数",
                    name_en="Requests",
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementDerived(
                    measurement_unit_id="MU_CALL",
                    metric_resource_id="ME_MEDIA_CREATE_RATE",
                    numerator_metric_id="ME_SUCCESS",
                    denominator_metric_id="ME_REQUESTS",
                    template="success_rate",
                    enabled=True,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

    migrate_kpi_v6()

    with session_factory() as session:
        base_binding = (
            session.query(KpiV6MeasurementBinding)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id="MU_CALL",
                metric_resource_id="ME_MEDIA_CREATE_RATE",
                binding_state="confirmed",
            )
            .one()
        )
        assert base_binding.metric_resource_id == "ME_MEDIA_CREATE_RATE"
        assert (
            session.query(KpiV6MeasurementDerived)
            .filter_by(
                network_element_type="UMF",
                measurement_unit_id="MU_CALL",
                metric_resource_id="ME_MEDIA_CREATE_RATE",
            )
            .count()
            == 0
        )
        audit = (
            session.query(KpiLegacyRecoveryAudit)
            .filter_by(
                source_table="kpi_measurement_derived",
                metric_resource_id="ME_MEDIA_CREATE_RATE",
            )
            .one()
        )
        assert audit.result == "skipped"
        assert audit.error_code == "source_backed_base_conflict"


def test_disabled_legacy_configuration_is_audited_without_becoming_focus_or_rule_state(isolated_db: Path) -> None:
    _seed_v5_configuration()
    migrate_kpi_v6()

    with session_factory() as session:
        assert session.query(KpiTeamFocusItem).count() == 0
        assert session.query(KpiRuleAssignmentState).count() == 0
        audits = (
            session.execute(
                __import__("sqlalchemy").text(
                    "SELECT source_table, object_kind, result, source FROM kpi_legacy_recovery_audits"
                )
            )
            .mappings()
            .all()
        )
        assert audits
        assert {row["source"] for row in audits} == {"migration"}
        assert {row["object_kind"] for row in audits} <= {"metric", "binding", "derived"}
        assert any(row["source_table"] == "kpi_measurement_bindings" for row in audits)
        assert any(row["source_table"] == "kpi_measurement_derived" for row in audits)


def test_legacy_child_recovery_never_changes_measurement_unit_enabled_state(isolated_db: Path) -> None:
    _seed_v5_configuration()
    with session_factory() as session:
        unit_resource = session.query(KpiMeasurementResource).filter_by(resource_id="MU_CALL").one()
        unit_resource.enabled = False
        session.commit()

    migrate_kpi_v6()

    with session_factory() as session:
        unit = session.query(KpiV6MeasurementUnit).filter_by(measurement_unit_id="MU_CALL").one()
        child_audits = (
            session.query(KpiLegacyRecoveryAudit)
            .filter(KpiLegacyRecoveryAudit.object_kind.in_(("metric", "binding", "derived")))
            .all()
        )
        assert child_audits
        assert unit.inspection_enabled is False


def test_repeated_migration_preserves_manually_changed_unit_enabled_state(isolated_db: Path) -> None:
    _seed_v5_configuration()
    migrate_kpi_v6()
    with session_factory() as session:
        unit = session.query(KpiV6MeasurementUnit).filter_by(measurement_unit_id="MU_CALL").one()
        unit.inspection_enabled = False
        unit.revision = 7
        session.commit()

    migrate_kpi_v6()

    with session_factory() as session:
        unit = session.query(KpiV6MeasurementUnit).filter_by(measurement_unit_id="MU_CALL").one()
        assert unit.inspection_enabled is False
        assert unit.revision == 7


def test_init_db_orders_v6_migration_after_columns_and_before_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "startup-order.db")
    calls: list[str] = []

    monkeypatch.setattr(db_module, "_rebuild_legacy_inventory_tables", lambda engine: None)
    monkeypatch.setattr(db_module.Base.metadata, "create_all", lambda engine: calls.append("create_all"))
    monkeypatch.setattr(db_module, "_ensure_task_columns", lambda engine: calls.append("task_columns"))
    monkeypatch.setattr(db_module, "_ensure_kpi_measurement_columns", lambda engine: None)
    monkeypatch.setattr(db_module, "_ensure_kpi_measurement_constraints", lambda engine: None)
    monkeypatch.setattr(db_module, "_ensure_inventory_device_columns", lambda engine: None)
    monkeypatch.setattr(db_module, "_ensure_inventory_observation_columns", lambda engine: None)
    monkeypatch.setattr(migration_module, "migrate_kpi_v6", lambda: calls.append("v6_migration"))
    monkeypatch.setattr(task_db_module, "ensure_backfilled", lambda: calls.append("backfill"))

    db_module.init_db()

    assert calls.index("create_all") < calls.index("task_columns") < calls.index("v6_migration")
    assert calls.index("v6_migration") < calls.index("backfill")
    assert db_module.TaskRecord.__table__.c.rule_network_element_type.nullable is True


def test_migration_isolates_one_failed_resource_and_continues(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        session.add(_task("task-umf", "UMF"))
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id="MU_GOOD",
                    kind="mu",
                    name_zh="可用测量单元",
                    name_en="Good Measurement Unit",
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                KpiMeasurementResource(
                    resource_id="ME_BROKEN",
                    kind="me",
                    name_zh="映射失败指标",
                    name_en="Broken Metric",
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

    original_resource_values = migration_module._resource_values

    def fail_one_resource(row, network_element_type):  # type: ignore[no-untyped-def]
        if row.resource_id == "ME_BROKEN":
            raise ValueError("synthetic mapping failure")
        return original_resource_values(row, network_element_type)

    monkeypatch.setattr(migration_module, "_resource_values", fail_one_resource)

    migrate_kpi_v6()

    with session_factory() as session:
        mapped_ids = {row.resource_id for row in session.query(KpiV6MeasurementResource).all()}
        assert "MU_GOOD" in mapped_ids
        assert "ME_BROKEN" not in mapped_ids
        pending = session.query(KpiPendingAttribution).filter_by(source_record_id="ME_BROKEN").one()
        assert pending.source_table == "kpi_measurement_resources"
        assert pending.reason == "migration_error"
        assert "synthetic mapping failure" in (pending.last_error or "")


def test_migration_reruns_without_duplicate_focus_assignments_audits_or_snapshots(isolated_db: Path) -> None:
    _seed_v5_configuration()
    migrate_kpi_v6()
    migrate_kpi_v6()

    with session_factory() as session:
        first_counts = {
            "focus": session.query(KpiTeamFocusItem).count(),
            "rule_states": session.query(KpiRuleAssignmentState).count(),
            "audits": session.query(KpiLegacyRecoveryAudit).count(),
            "pending": session.query(KpiPendingAttribution).count(),
            "rule_snapshots": session.query(TaskRuleScopeSnapshot).count(),
            "kpi_snapshots": session.query(TaskKpiScopeSnapshot).count(),
        }

    migrate_kpi_v6()

    with session_factory() as session:
        second_counts = {
            "focus": session.query(KpiTeamFocusItem).count(),
            "rule_states": session.query(KpiRuleAssignmentState).count(),
            "audits": session.query(KpiLegacyRecoveryAudit).count(),
            "pending": session.query(KpiPendingAttribution).count(),
            "rule_snapshots": session.query(TaskRuleScopeSnapshot).count(),
            "kpi_snapshots": session.query(TaskKpiScopeSnapshot).count(),
        }

    assert second_counts == first_counts
    assert first_counts["focus"] == first_counts["rule_states"] == 0
    assert first_counts["rule_snapshots"] == first_counts["kpi_snapshots"] == 0
    assert first_counts["audits"] > 0
    assert first_counts["pending"] > 0


def test_migration_isolates_one_failed_binding_and_continues(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        session.add(_task("task-umf", "UMF"))
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id=resource_id,
                    kind=kind,
                    name_zh=resource_id,
                    name_en=resource_id,
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                )
                for resource_id, kind in [
                    ("MU_CALL", "mu"),
                    ("ME_GOOD", "me"),
                    ("ME_BAD", "me"),
                ]
            ]
        )
        good = KpiMeasurementBinding(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_GOOD",
            raw_source_name="Good Column",
            base_source_name="Good Column",
            status="confirmed",
            enabled=True,
            task_id="task-umf",
            source_file="call.csv",
            created_at=NOW,
            updated_at=NOW,
        )
        bad = KpiMeasurementBinding(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_BAD",
            raw_source_name="Bad Column",
            base_source_name="Bad Column",
            status="confirmed",
            enabled=True,
            task_id="task-umf",
            source_file="call.csv",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([good, bad])
        session.commit()
        bad_id = bad.id

    original_binding_values = migration_module._binding_values

    def fail_one_binding(row, network_element_type):  # type: ignore[no-untyped-def]
        if row.metric_resource_id == "ME_BAD":
            raise ValueError("binding mapping failure")
        return original_binding_values(row, network_element_type)

    monkeypatch.setattr(migration_module, "_binding_values", fail_one_binding)
    migrate_kpi_v6()

    with session_factory() as session:
        mapped_metrics = {row.metric_resource_id for row in session.query(KpiV6MeasurementBinding).all()}
        assert mapped_metrics == {"ME_GOOD"}
        pending = session.query(KpiPendingAttribution).filter_by(source_record_id=str(bad_id)).one()
        assert pending.source_table == "kpi_measurement_bindings"
        assert pending.reason == "migration_error"


def test_migration_isolates_one_failed_derived_definition_and_continues(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        session.add(_task("task-umf", "UMF"))
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id=resource_id,
                    kind=kind,
                    name_zh=resource_id,
                    name_en=resource_id,
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                )
                for resource_id, kind in [
                    ("MU_CALL", "mu"),
                    ("ME_GOOD_RATE", "me"),
                    ("ME_BAD_RATE", "me"),
                    ("ME_NUM", "me"),
                    ("ME_DEN", "me"),
                ]
            ]
        )
        good = KpiMeasurementDerived(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_GOOD_RATE",
            numerator_metric_id="ME_NUM",
            denominator_metric_id="ME_DEN",
            template="success_rate",
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
        bad = KpiMeasurementDerived(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_BAD_RATE",
            numerator_metric_id="ME_NUM",
            denominator_metric_id="ME_DEN",
            template="success_rate",
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([good, bad])
        session.commit()
        bad_id = bad.id

    original_derived_values = migration_module._derived_values

    def fail_one_derived(row, network_element_type):  # type: ignore[no-untyped-def]
        if row.metric_resource_id == "ME_BAD_RATE":
            raise ValueError("derived mapping failure")
        return original_derived_values(row, network_element_type)

    monkeypatch.setattr(migration_module, "_derived_values", fail_one_derived)
    migrate_kpi_v6()

    with session_factory() as session:
        mapped_metrics = {row.metric_resource_id for row in session.query(KpiV6MeasurementDerived).all()}
        assert mapped_metrics == {"ME_GOOD_RATE"}
        pending = session.query(KpiPendingAttribution).filter_by(source_record_id=str(bad_id)).one()
        assert pending.source_table == "kpi_measurement_derived"
        assert pending.reason == "migration_error"


def test_migration_isolates_one_failed_maintenance_config_and_continues(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        session.add(_task("task-umf", "UMF"))
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id=resource_id,
                    kind=kind,
                    name_zh=resource_id,
                    name_en=resource_id,
                    enabled=True,
                    source="discovered",
                    origin_task_id="task-umf",
                    created_at=NOW,
                    updated_at=NOW,
                )
                for resource_id, kind in [
                    ("MU_CALL", "mu"),
                    ("ME_GOOD", "me"),
                    ("ME_BAD", "me"),
                ]
            ]
        )
        good = KpiMetricMaintenanceConfig(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_GOOD",
            role="base",
            daily_aggregation="latest",
            daily_change_threshold_unit="auto",
            is_percentage=False,
            zero_semantics="unknown",
            consistency_tolerance=0.2,
            object_match_mode="exact",
            created_at=NOW,
            updated_at=NOW,
        )
        bad = KpiMetricMaintenanceConfig(
            measurement_unit_id="MU_CALL",
            metric_resource_id="ME_BAD",
            role="base",
            daily_aggregation="latest",
            daily_change_threshold_unit="auto",
            is_percentage=False,
            zero_semantics="unknown",
            consistency_tolerance=0.2,
            object_match_mode="exact",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all([good, bad])
        session.commit()
        bad_id = bad.id

    original_maintenance_values = migration_module._maintenance_values

    def fail_one_maintenance(row, *, network_element_type, metric_resource):  # type: ignore[no-untyped-def]
        if row.metric_resource_id == "ME_BAD":
            raise ValueError("maintenance mapping failure")
        return original_maintenance_values(
            row,
            network_element_type=network_element_type,
            metric_resource=metric_resource,
        )

    monkeypatch.setattr(migration_module, "_maintenance_values", fail_one_maintenance)
    migrate_kpi_v6()

    with session_factory() as session:
        mapped_metrics = {row.metric_resource_id for row in session.query(KpiV6MetricMaintenanceConfig).all()}
        assert mapped_metrics == {"ME_GOOD"}
        pending = session.query(KpiPendingAttribution).filter_by(source_record_id=str(bad_id)).one()
        assert pending.source_table == "kpi_metric_maintenance_configs"
        assert pending.reason == "migration_error"
