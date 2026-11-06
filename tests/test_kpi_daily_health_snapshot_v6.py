"""v6 测量单元口径的日健康快照范围测试。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    TaskRecord,
    session_factory,
)
from app.services.kpi_daily_health_snapshot import build_daily_health_snapshot

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def _task(task_id: str, product: str) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        name=f"{product} 快照测试",
        mode="online",
        status="completed",
        trigger="api",
        package_file=f"{task_id}.zip",
        customer={"product": product},
        stats={},
        created_at=NOW,
        completed_at=NOW,
        last_run_at=NOW,
    )


def _unit(
    network_element_type: str,
    measurement_unit_id: str,
    *,
    inspection_enabled: bool,
) -> KpiV6MeasurementUnit:
    return KpiV6MeasurementUnit(
        network_element_type=network_element_type,
        measurement_unit_id=measurement_unit_id,
        name_zh=f"{measurement_unit_id} 中文名",
        name_en=f"{measurement_unit_id} English",
        inspection_enabled=inspection_enabled,
        revision=1,
        config_fingerprint=hashlib.sha256(f"{network_element_type}:{measurement_unit_id}".encode()).hexdigest(),
        source="preset",
        origin_task_id="source-task",
        created_at=NOW,
        updated_at=NOW,
    )


def _resource(
    network_element_type: str,
    resource_id: str,
    *,
    kind: str = "me",
    display_order: int = 0,
    warning_threshold: float | None = 90.0,
) -> KpiV6MeasurementResource:
    return KpiV6MeasurementResource(
        network_element_type=network_element_type,
        resource_id=resource_id,
        kind=kind,
        name_zh=f"{resource_id} 中文名",
        name_en=f"{resource_id} English",
        display_order=display_order,
        direction="higher_better" if kind == "me" else None,
        importance="P1",
        warning_threshold=warning_threshold,
        critical_threshold=80.0 if kind == "me" else None,
        source="preset",
        origin_task_id="source-task",
        legacy_source_key=f"test:{network_element_type}:{resource_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _binding(
    network_element_type: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    state: str = "confirmed",
) -> KpiV6MeasurementBinding:
    return KpiV6MeasurementBinding(
        network_element_type=network_element_type,
        measurement_unit_id=measurement_unit_id,
        raw_source_name=f"{metric_resource_id} 来源列",
        base_source_name=f"{metric_resource_id} 来源列",
        metric_resource_id=metric_resource_id,
        display_unit="%",
        binding_state=state,
        source_file="PerfResult.csv",
        origin_task_id="source-task",
        revision=1,
        legacy_source_key=f"test:{network_element_type}:{measurement_unit_id}:{metric_resource_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _derived(
    network_element_type: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    state: str = "defined",
) -> KpiV6MeasurementDerived:
    return KpiV6MeasurementDerived(
        network_element_type=network_element_type,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        numerator_metric_id=f"{metric_resource_id}_NUMERATOR",
        denominator_metric_id=f"{metric_resource_id}_DENOMINATOR",
        template="success_rate",
        definition_state=state,
        revision=1,
        legacy_source_key=f"test:{network_element_type}:{measurement_unit_id}:{metric_resource_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _config(
    network_element_type: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    config_state: str = "ready",
    is_percentage: bool = True,
    role: str = "base",
) -> KpiV6MetricMaintenanceConfig:
    return KpiV6MetricMaintenanceConfig(
        network_element_type=network_element_type,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        role=role,
        direction="higher_better" if config_state == "ready" else None,
        warning_threshold=90.0 if config_state == "ready" else None,
        critical_threshold=80.0 if config_state == "ready" else None,
        daily_aggregation="latest",
        daily_change_threshold=0.2,
        daily_change_threshold_unit="pp",
        is_percentage=is_percentage,
        zero_semantics="unknown",
        consistency_tolerance=0.2,
        object_match_mode="exact",
        config_state=config_state,
        revision=1,
        legacy_source_key=f"test:{network_element_type}:{measurement_unit_id}:{metric_resource_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _metric_result(metric_resource_id: str, value: float | None) -> dict[str, object]:
    return {
        "metric_resource_id": metric_resource_id,
        "source_files": ["PerfResult.csv"],
        "time_series": [
            {
                "object_key": "pod-a",
                "period_minutes": 15,
                "time": "2026-11-05T01:00:00+00:00",
                "value": value,
            }
        ],
    }


def _seed_disabled_v5_rows(network_element_type: str, measurement_unit_id: str, metric_ids: tuple[str, ...]) -> None:
    """历史 v5 指标级 enabled 字段不得成为 v6 执行门禁。"""
    with session_factory() as session:
        session.add(
            KpiMeasurementResource(
                resource_id=measurement_unit_id,
                kind="mu",
                name_zh="历史停用测量单元",
                name_en="Legacy Disabled Unit",
                enabled=False,
                display_order=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for metric_id in metric_ids:
            session.add(
                KpiMeasurementResource(
                    resource_id=metric_id,
                    kind="me",
                    name_zh=f"{metric_id} 历史停用指标",
                    name_en=f"{metric_id} Legacy Disabled Metric",
                    enabled=False,
                    display_order=2,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                KpiMeasurementBinding(
                    measurement_unit_id=measurement_unit_id,
                    metric_resource_id=metric_id,
                    raw_source_name=f"{metric_id} 历史来源列",
                    base_source_name=f"{metric_id} 历史来源列",
                    status="confirmed",
                    enabled=False,
                    task_id="legacy-task",
                    source_file="legacy.csv",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.add(
            KpiMeasurementDerived(
                measurement_unit_id=measurement_unit_id,
                metric_resource_id="ME_DERIVED",
                numerator_metric_id="ME_DERIVED_NUMERATOR",
                denominator_metric_id="ME_DERIVED_DENOMINATOR",
                template="success_rate",
                enabled=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            KpiMetricMaintenanceConfig(
                measurement_unit_id=measurement_unit_id,
                metric_resource_id="ME_BASE",
                role="base",
                is_percentage=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def test_v6_enabled_unit_uses_confirmed_base_defined_derived_and_ignores_v5_enabled_gates(
    isolated_db: Path,
) -> None:
    del isolated_db
    task_id = "task-v6-snapshot-enabled"
    unit_id = "MU_MEDIA_SHARED"
    metric_ids = (
        "ME_BASE",
        "ME_INCOMPLETE",
        "ME_DERIVED",
        "ME_DERIVED_NUMERATOR",
        "ME_DERIVED_DENOMINATOR",
        "ME_CANDIDATE",
        "ME_UNDEFINED_DERIVED",
    )
    with session_factory() as session:
        session.add(_task(task_id, " umf "))
        session.add(_unit("UMF", unit_id, inspection_enabled=True))
        for order, metric_id in enumerate(metric_ids):
            session.add(_resource("UMF", metric_id, display_order=order))
        session.add(_binding("UMF", unit_id, "ME_BASE"))
        session.add(_binding("UMF", unit_id, "ME_INCOMPLETE"))
        session.add(_binding("UMF", unit_id, "ME_CANDIDATE", state="candidate"))
        session.add(_derived("UMF", unit_id, "ME_DERIVED"))
        session.add(_derived("UMF", unit_id, "ME_UNDEFINED_DERIVED", state="incomplete"))
        session.add(_config("UMF", unit_id, "ME_BASE"))
        session.add(_config("UMF", unit_id, "ME_INCOMPLETE", config_state="incomplete"))
        session.commit()

    _seed_disabled_v5_rows("UMF", unit_id, ("ME_BASE", "ME_INCOMPLETE"))

    snapshot = build_daily_health_snapshot(
        task_id,
        {
            unit_id: {
                "metric_results": {
                    "base": _metric_result("ME_BASE", 95.0),
                    "incomplete": _metric_result("ME_INCOMPLETE", 92.0),
                    "numerator": _metric_result("ME_DERIVED_NUMERATOR", 9.0),
                    "denominator": _metric_result("ME_DERIVED_DENOMINATOR", 10.0),
                    "candidate": _metric_result("ME_CANDIDATE", 91.0),
                    "undefined": _metric_result("ME_UNDEFINED_DERIVED", 90.0),
                }
            }
        },
        [],
    )

    assert snapshot["scope"]["enabled_measurement_unit_count"] == 1
    assert snapshot["scope"]["confirmed_binding_metric_count"] == 2
    assert snapshot["scope"]["expected_metric_count"] == 3
    assert {item["metric_resource_id"] for item in snapshot["metrics"]} == {
        "ME_BASE",
        "ME_INCOMPLETE",
        "ME_DERIVED",
    }
    assert all(item["measurement_unit_enabled"] is True for item in snapshot["metrics"])
    assert all(item["metric_resource_enabled"] is True for item in snapshot["metrics"])


def test_v6_snapshot_excludes_disabled_units_and_keeps_network_types_isolated(isolated_db: Path) -> None:
    del isolated_db
    task_id = "task-v6-snapshot-umf"
    with session_factory() as session:
        session.add(_task(task_id, "UMF"))
        session.add(_unit("UMF", "MU_UMF_ON", inspection_enabled=True))
        session.add(_unit("UMF", "MU_UMF_OFF", inspection_enabled=False))
        session.add(_unit("CSP", "MU_CSP_ON", inspection_enabled=True))
        session.add_all(
            [
                _resource("UMF", "ME_UMF_VISIBLE", display_order=1),
                _resource("UMF", "ME_UMF_DISABLED_UNIT", display_order=2),
                _resource("CSP", "ME_CSP_MUST_NOT_LEAK", display_order=3),
            ]
        )
        session.add(_binding("UMF", "MU_UMF_ON", "ME_UMF_VISIBLE"))
        session.add(_binding("UMF", "MU_UMF_OFF", "ME_UMF_DISABLED_UNIT"))
        session.add(_binding("CSP", "MU_CSP_ON", "ME_CSP_MUST_NOT_LEAK"))
        session.add(_config("UMF", "MU_UMF_ON", "ME_UMF_VISIBLE"))
        session.add(_config("UMF", "MU_UMF_OFF", "ME_UMF_DISABLED_UNIT"))
        session.add(_config("CSP", "MU_CSP_ON", "ME_CSP_MUST_NOT_LEAK"))
        session.commit()

    snapshot = build_daily_health_snapshot(
        task_id,
        {
            "MU_UMF_ON": {"metric_results": {"visible": _metric_result("ME_UMF_VISIBLE", 96.0)}},
            "MU_UMF_OFF": {"metric_results": {"off": _metric_result("ME_UMF_DISABLED_UNIT", 95.0)}},
            "MU_CSP_ON": {"metric_results": {"csp": _metric_result("ME_CSP_MUST_NOT_LEAK", 94.0)}},
        },
        [],
    )

    assert snapshot["scope"]["enabled_measurement_unit_count"] == 1
    assert snapshot["scope"]["expected_metric_count"] == 1
    assert [item["measurement_unit_id"] for item in snapshot["metrics"]] == ["MU_UMF_ON"]
    assert [item["metric_resource_id"] for item in snapshot["metrics"]] == ["ME_UMF_VISIBLE"]


def test_v6_snapshot_percentage_display_comes_only_from_explicit_config(isolated_db: Path) -> None:
    del isolated_db
    task_id = "task-v6-percentage-config"
    unit_id = "MU_PERCENTAGE"
    base_id = "ME_BASE_PERCENT"
    derived_id = "ME_DERIVED_RATIO"
    derived_without_config_id = "ME_DERIVED_RATIO_WITHOUT_CONFIG"
    numerator_id = "ME_DERIVED_NUM"
    denominator_id = "ME_DERIVED_DEN"
    with session_factory() as session:
        session.add(_task(task_id, "UMF"))
        session.add(_unit("UMF", unit_id, inspection_enabled=True))
        for order, metric_id in enumerate(
            (base_id, derived_id, derived_without_config_id, numerator_id, denominator_id)
        ):
            session.add(_resource("UMF", metric_id, display_order=order))
        session.add(_binding("UMF", unit_id, base_id))
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=unit_id,
                metric_resource_id=derived_id,
                numerator_metric_id=numerator_id,
                denominator_metric_id=denominator_id,
                template="success_rate",
                definition_state="defined",
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            KpiV6MeasurementDerived(
                network_element_type="UMF",
                measurement_unit_id=unit_id,
                metric_resource_id=derived_without_config_id,
                numerator_metric_id=numerator_id,
                denominator_metric_id=denominator_id,
                template="success_rate",
                definition_state="defined",
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(_config("UMF", unit_id, base_id, is_percentage=True))
        session.add(
            _config(
                "UMF",
                unit_id,
                derived_id,
                role="derived",
                is_percentage=False,
            )
        )
        session.commit()

    snapshot = build_daily_health_snapshot(
        task_id,
        {
            unit_id: {
                "metric_results": {
                    "base": _metric_result(base_id, 63.7),
                    "derived": _metric_result(derived_id, 64.5),
                    "derived_without_config": _metric_result(derived_without_config_id, 64.5),
                    "numerator": _metric_result(numerator_id, 129.0),
                    "denominator": _metric_result(denominator_id, 200.0),
                }
            }
        },
        [],
    )

    metrics = {item["metric_resource_id"]: item for item in snapshot["metrics"]}
    assert metrics[base_id]["role"] == "base"
    assert metrics[base_id]["is_percentage"] is True
    assert metrics[base_id]["today_display"] == "63.7%"
    assert metrics[derived_id]["role"] == "derived"
    assert metrics[derived_id]["is_percentage"] is False
    assert metrics[derived_id]["today_display"] == "64.5"
    assert metrics[derived_without_config_id]["role"] == "derived"
    assert metrics[derived_without_config_id]["is_percentage"] is False
    assert metrics[derived_without_config_id]["today_display"] == "64.5"


def test_confirmed_source_success_rate_wins_over_residual_derived_definition(isolated_db: Path) -> None:
    del isolated_db
    task_id = "task-v6-source-rate-precedence"
    unit_id = "MU_SOURCE_RATE_PRECEDENCE"
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    numerator_id = "ME_MEDIA_CREATION_SUCCESS"
    denominator_id = "ME_MEDIA_CREATION_REQUESTS"
    with session_factory() as session:
        session.add(_task(task_id, "UMF"))
        session.add(_unit("UMF", unit_id, inspection_enabled=True))
        session.add(_resource("UMF", metric_id))
        session.add(_binding("UMF", unit_id, metric_id))
        session.add(_derived("UMF", unit_id, metric_id))
        session.add(_config("UMF", unit_id, metric_id, role="base", is_percentage=True))
        session.commit()

    snapshot = build_daily_health_snapshot(
        task_id,
        {
            unit_id: {
                "metric_results": {
                    "source_rate": _metric_result(metric_id, 63.7),
                    "numerator": _metric_result(numerator_id, 129.0),
                    "denominator": _metric_result(denominator_id, 200.0),
                }
            }
        },
        [],
    )

    media_metrics = [item for item in snapshot["metrics"] if item["metric_resource_id"] == metric_id]
    assert len(media_metrics) == 1
    media = media_metrics[0]
    assert media["role"] == "base"
    assert media["today_value"] == 63.7
    assert media["today_display"] == "63.7%"
    assert media["daily_aggregation"] == "latest"
    assert media["objects"][0]["numerator"] is None
    assert media["objects"][0]["denominator"] is None


def test_missing_confirmed_source_rate_is_not_backfilled_from_residual_derived_inputs(
    isolated_db: Path,
) -> None:
    del isolated_db
    task_id = "task-v6-source-rate-missing-precedence"
    unit_id = "MU_SOURCE_RATE_MISSING_PRECEDENCE"
    metric_id = "ME_MEDIA_CREATION_SUCCESS_RATE"
    numerator_id = "ME_MEDIA_CREATION_SUCCESS"
    denominator_id = "ME_MEDIA_CREATION_REQUESTS"
    with session_factory() as session:
        session.add(_task(task_id, "UMF"))
        session.add(_unit("UMF", unit_id, inspection_enabled=True))
        session.add(_resource("UMF", metric_id))
        session.add(_binding("UMF", unit_id, metric_id))
        session.add(_derived("UMF", unit_id, metric_id))
        session.add(_config("UMF", unit_id, metric_id, role="base", is_percentage=True))
        session.commit()

    snapshot = build_daily_health_snapshot(
        task_id,
        {
            unit_id: {
                "metric_results": {
                    "source_rate": _metric_result(metric_id, None),
                    "numerator": _metric_result(numerator_id, 129.0),
                    "denominator": _metric_result(denominator_id, 200.0),
                }
            }
        },
        [],
    )

    media_metrics = [item for item in snapshot["metrics"] if item["metric_resource_id"] == metric_id]
    assert len(media_metrics) == 1
    media = media_metrics[0]
    assert media["role"] == "base"
    assert media["today_value"] is None
    assert media["today_display"] is None
    assert media["daily_aggregation"] == "latest"
    assert media["objects"][0]["numerator"] is None
    assert media["objects"][0]["denominator"] is None
