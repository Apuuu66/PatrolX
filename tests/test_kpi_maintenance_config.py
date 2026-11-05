"""KPI 指标维护配置、审计与旧库迁移测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    _create_sqlite_engine,
    _ensure_kpi_measurement_constraints,
    init_db,
    session_factory,
)


def _seed_resources(*, derived: bool = False) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add_all(
            [
                KpiMeasurementResource(
                    resource_id="MU_CALL",
                    kind="mu",
                    name_zh="呼叫统计",
                    name_en="Call Statistics",
                    display_order=1,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_RATE",
                    kind="me",
                    name_zh="呼叫成功率",
                    name_en="Call Success Rate",
                    display_order=2,
                    enabled=True,
                    direction="higher_better",
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_SUCCESS",
                    kind="me",
                    name_zh="成功请求次数",
                    name_en="Success Requests",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_TOTAL",
                    kind="me",
                    name_zh="呼叫请求次数",
                    name_en="Call Requests",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        for metric_id in ("ME_RATE", "ME_SUCCESS", "ME_TOTAL"):
            session.add(
                KpiMeasurementBinding(
                    metric_resource_id=metric_id,
                    measurement_unit_id="MU_CALL",
                    raw_source_name=metric_id,
                    base_source_name=metric_id,
                    status="confirmed",
                    enabled=True,
                    task_id="task-1",
                    source_file="call.csv",
                    created_at=now,
                    updated_at=now,
                )
            )
        if derived:
            session.add(
                KpiMeasurementDerived(
                    measurement_unit_id="MU_CALL",
                    metric_resource_id="ME_RATE",
                    numerator_metric_id="ME_SUCCESS",
                    denominator_metric_id="ME_TOTAL",
                    template="success_rate",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()


def test_metric_config_defaults_to_safe_legacy_view() -> None:
    from app.services.kpi_metric_maintenance import get_metric_maintenance_config

    init_db()
    _seed_resources()

    config = get_metric_maintenance_config("MU_CALL", "ME_RATE")

    assert config["role"] == "base"
    assert config["direction"] == "higher_better"
    assert config["daily_aggregation"] == "latest"
    assert config["daily_change_threshold"] is None
    assert config["daily_change_threshold_unit"] == "auto"
    assert config["is_percentage"] is True
    assert config["zero_semantics"] == "unknown"
    assert config["object_match_mode"] == "exact"
    assert config["enabled"] is True
    assert config["config_source"] == "legacy_resource"


def test_metric_config_update_writes_audit_and_effective_values() -> None:
    from app.services.kpi_metric_maintenance import (
        get_metric_maintenance_config,
        list_metric_maintenance_audits,
        update_metric_maintenance_config,
    )

    init_db()
    _seed_resources()

    updated = update_metric_maintenance_config(
        "MU_CALL",
        "ME_RATE",
        {
            "direction": "lower_better",
            "warning_threshold": 99.0,
            "critical_threshold": 95.0,
            "daily_aggregation": "mean",
            "daily_change_threshold": 0.5,
            "daily_change_threshold_unit": "pp",
            "is_percentage": True,
            "zero_semantics": "expected_zero",
            "consistency_tolerance": 0.3,
            "object_match_mode": "exact",
            "enabled": True,
        },
        actor="operator-a",
    )

    assert updated["direction"] == "lower_better"
    assert updated["warning_threshold"] == 99.0
    assert updated["daily_aggregation"] == "mean"
    assert updated["zero_semantics"] == "expected_zero"
    assert updated["config_source"] == "custom"
    assert get_metric_maintenance_config("MU_CALL", "ME_RATE") == updated

    audits = list_metric_maintenance_audits("MU_CALL", "ME_RATE", page=1, page_size=20)
    assert audits["total"] == 1
    audit = audits["items"][0]
    assert audit["actor"] == "operator-a"
    assert set(audit["changed_fields"]) == {
        "direction",
        "warning_threshold",
        "critical_threshold",
        "daily_aggregation",
        "daily_change_threshold",
        "daily_change_threshold_unit",
        "is_percentage",
        "zero_semantics",
        "consistency_tolerance",
        "object_match_mode",
        "enabled",
    }
    assert audit["before_values"]["daily_aggregation"] == "latest"
    assert audit["after_values"]["daily_aggregation"] == "mean"


def test_derived_role_requires_existing_definition() -> None:
    from app.services.kpi_measurement_units import KpiMeasurementError
    from app.services.kpi_metric_maintenance import update_metric_maintenance_config

    init_db()
    _seed_resources()

    with pytest.raises(KpiMeasurementError) as caught:
        update_metric_maintenance_config("MU_CALL", "ME_RATE", {"role": "derived"}, actor="operator-a")

    assert caught.value.status_code == 409
    assert caught.value.code == "kpi_metric_role_requires_derived"


def test_derived_config_can_be_read_and_updated_with_audit() -> None:
    from app.services.kpi_metric_maintenance import (
        get_measurement_derived,
        list_measurement_derived,
        update_measurement_derived,
    )

    init_db()
    _seed_resources(derived=True)
    listed = list_measurement_derived(measurement_unit_id="MU_CALL", page=1, page_size=20)
    assert listed["total"] == 1
    derived_id = listed["items"][0]["id"]
    assert listed["items"][0]["metric_resource_name_zh"] == "呼叫成功率"

    updated = update_measurement_derived(
        derived_id,
        {"template": "reverse_success_rate", "enabled": False},
        actor="operator-b",
    )
    assert updated["template"] == "reverse_success_rate"
    assert updated["enabled"] is False
    assert get_measurement_derived(derived_id) == updated


def test_init_db_deduplicates_legacy_derived_rows_and_adds_unique_index(tmp_path) -> None:
    engine = _create_sqlite_engine(tmp_path / "legacy.db")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE kpi_measurement_derived ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "measurement_unit_id VARCHAR(128) NOT NULL, "
                "metric_resource_id VARCHAR(128) NOT NULL, "
                "numerator_metric_id VARCHAR(128) NOT NULL, "
                "denominator_metric_id VARCHAR(128) NOT NULL, "
                "template VARCHAR(32) NOT NULL DEFAULT 'success_rate', "
                "enabled BOOLEAN NOT NULL DEFAULT 1, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO kpi_measurement_derived "
                "(measurement_unit_id, metric_resource_id, numerator_metric_id, denominator_metric_id, "
                "template, enabled, created_at, updated_at) VALUES "
                "('MU_CALL', 'ME_RATE', 'ME_SUCCESS', 'ME_TOTAL', 'success_rate', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "('MU_CALL', 'ME_RATE', 'ME_SUCCESS', 'ME_TOTAL', 'reverse_success_rate', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    _ensure_kpi_measurement_constraints(engine)

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, template FROM kpi_measurement_derived "
                "WHERE measurement_unit_id='MU_CALL' AND metric_resource_id='ME_RATE'"
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].template == "reverse_success_rate"
    indexes = {item["name"] for item in inspect(engine).get_indexes("kpi_measurement_derived")}
    assert "uq_kpi_measurement_derived_unit_metric" in indexes
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO kpi_measurement_derived "
                    "(measurement_unit_id, metric_resource_id, numerator_metric_id, denominator_metric_id, "
                    "template, enabled, created_at, updated_at) VALUES "
                    "('MU_CALL', 'ME_RATE', 'ME_SUCCESS', 'ME_TOTAL', 'success_rate', 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
