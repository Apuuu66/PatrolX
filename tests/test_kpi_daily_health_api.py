"""KPI 日健康详情与维护配置 API 集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import (
    AuthSession,
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    TaskKpiPoint,
    TaskRecord,
    TaskRuleResult,
    init_db,
    session_factory,
)
from app.models.schemas import (
    InspectionTask,
    RuleResult,
    Summary,
    SystemInspection,
    TaskStats,
    TaskStatus,
)
from app.services import task_db
from app.services.auth import get_current_user

KPI_RULE_CODE = "kpi.measurement_units"
TASK_ID = "task-kpi-daily-api"
HISTORY_TASK_ID = "task-kpi-daily-api-history"
DEVICE_ID = "device-kpi-daily-api"
ANCHOR = datetime(2026, 11, 1, 2, tzinfo=UTC)  # UTC+8 10:00


def _client() -> TestClient:
    return TestClient(app)


def _cleanup() -> None:
    init_db()
    with session_factory() as session:
        session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id.in_([TASK_ID, HISTORY_TASK_ID])).delete(
            synchronize_session=False
        )
        session.query(TaskRuleResult).filter(TaskRuleResult.task_id.in_([TASK_ID, HISTORY_TASK_ID])).delete(
            synchronize_session=False
        )
        session.query(TaskRecord).filter(TaskRecord.task_id.in_([TASK_ID, HISTORY_TASK_ID])).delete(
            synchronize_session=False
        )
        session.query(KpiMetricMaintenanceConfig).delete()
        session.commit()


def _seed_resources() -> None:
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
                    warning_threshold=99.0,
                    critical_threshold=98.0,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_SUCCESS",
                    kind="me",
                    name_zh="成功请求次数",
                    name_en="Success Requests",
                    display_order=3,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
                KpiMeasurementResource(
                    resource_id="ME_TOTAL",
                    kind="me",
                    name_zh="呼叫请求次数",
                    name_en="Call Requests",
                    display_order=4,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        for metric_id in ("ME_RATE", "ME_SUCCESS", "ME_TOTAL"):
            session.add(
                KpiMeasurementBinding(
                    metric_resource_id=metric_id,
                    measurement_unit_id="MU_CALL",
                    raw_source_name=metric_id,
                    base_source_name=metric_id,
                    status="confirmed",
                    enabled=True,
                    task_id=TASK_ID,
                    source_file="call.csv",
                    created_at=now,
                    updated_at=now,
                )
            )
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


def _rule(*, include_daily_health: bool = True) -> RuleResult:
    metadata: dict[str, object] = {
        "measurement_units": [
            {
                "measurement_unit_id": "MU_CALL",
                "measurement_unit_name_zh": "呼叫统计",
                "metrics": [
                    {
                        "metric_resource_id": "ME_RATE",
                        "metric_resource_name_zh": "呼叫成功率",
                        "role": "derived",
                    }
                ],
            }
        ]
    }
    if include_daily_health:
        metadata["daily_health"] = {
            "schema_version": 1,
            "timezone": "Asia/Shanghai",
            "data_date": "2026-11-01",
            "previous_date": "2026-10-31",
            "current_counts": {
                "normal": 0,
                "warn": 1,
                "fail": 0,
                "pending_config": 0,
                "unable_to_judge": 0,
                "not_applicable": 0,
            },
            "trend_counts": {
                "improved": 0,
                "stable": 0,
                "worsened": 1,
                "observe": 0,
                "no_baseline": 0,
            },
            "scope": {},
            "metrics": [
                {
                    "measurement_unit_id": "MU_CALL",
                    "measurement_unit_name_zh": "呼叫统计",
                    "metric_resource_id": "ME_RATE",
                    "metric_resource_name_zh": "呼叫成功率",
                    "role": "derived",
                }
            ],
        }
    return RuleResult(
        code=KPI_RULE_CODE,
        name="KPI 测量单元巡检",
        category="kpi",
        priority=1,
        execution_order=1,
        status="warn",
        severity="medium",
        executed_at=ANCHOR,
        metadata=metadata,
    )


def _task(task_id: str, *, device_id: str = DEVICE_ID, completed_at: datetime = ANCHOR) -> InspectionTask:
    rule = _rule()
    summary = Summary(total=1, pass_=0, warn=1, fail=0, error=0, skip=0)
    stats = TaskStats.model_validate({**summary.model_dump(by_alias=True), "systems": 1})
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="local",
        status=TaskStatus.COMPLETED,
        trigger="api",
        created_at=completed_at - timedelta(minutes=10),
        completed_at=completed_at,
        last_run_at=completed_at,
        stats=stats,
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            package_checksum="a" * 64,
            status="completed",
            summary=summary,
            rules=[rule],
            customer={"device_id": device_id},
        ),
    )


def _point(
    task_id: str,
    metric_id: str,
    measured_at: datetime,
    value: float,
    *,
    object_key: str = "pod-a",
    period_minutes: int = 15,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "rule_code": KPI_RULE_CODE,
        "measurement_unit_id": "MU_CALL",
        "metric_resource_id": metric_id,
        "object_key": object_key,
        "period_minutes": period_minutes,
        "measured_at": measured_at.isoformat(),
        "value": value,
        "source_file": "call.csv",
        "line_number": 1,
    }


def _publish_current() -> None:
    points = [
        _point(TASK_ID, "ME_SUCCESS", ANCHOR, 15),
        _point(TASK_ID, "ME_TOTAL", ANCHOR, 20),
        _point(TASK_ID, "ME_RATE", ANCHOR, 75),
        _point(TASK_ID, "ME_SUCCESS", ANCHOR - timedelta(days=1), 8),
        _point(TASK_ID, "ME_TOTAL", ANCHOR - timedelta(days=1), 10),
        _point(TASK_ID, "ME_RATE", ANCHOR - timedelta(days=1), 80),
    ]
    task_db.publish_snapshot(_task(TASK_ID), rule_results=[_rule()], kpi_points=points)


def test_daily_health_detail_uses_daily_denominator_and_filtered_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _cleanup()
    _seed_resources()
    _publish_current()

    def fail_full_scan(*args: object, **kwargs: object) -> object:
        raise AssertionError("日健康详情不得调用 list_kpi_points 全量扫描")

    monkeypatch.setattr(task_db, "list_kpi_points", fail_full_scan)
    with _client() as client:
        response = client.get(f"/api/v2/tasks/{TASK_ID}/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_RATE")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metric"]["daily_aggregation"] == "formula"
    assert payload["metric"]["formula"] == "numerator_sum / denominator_sum * 100"
    assert payload["groups"][0]["today"]["numerator"] == 15
    assert payload["groups"][0]["today"]["denominator"] == 20
    assert payload["groups"][0]["today"]["value"] == 75.0
    assert payload["groups"][0]["yesterday"]["value"] == 80.0
    assert len(payload["seven_day_trend"]) == 7


def test_daily_health_detail_recomputes_status_and_trend_from_maintenance_config() -> None:
    _cleanup()
    _seed_resources()
    _publish_current()

    detail_url = f"/api/v2/tasks/{TASK_ID}/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_RATE"
    config_url = "/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE"
    with _client() as client:
        before = client.get(detail_url)
        updated = client.patch(
            config_url,
            json={
                "critical_threshold": 60.0,
                "warning_threshold": 70.0,
                "daily_change_threshold": 10.0,
                "daily_change_threshold_unit": "pp",
            },
        )
        after = client.get(detail_url)
        audits = client.get(f"{config_url}/audits")

    assert before.status_code == 200, before.text
    assert before.json()["metric"]["current_status"] == "fail"
    assert before.json()["metric"]["trend_status"] == "worsened"
    assert updated.status_code == 200, updated.text
    assert after.status_code == 200, after.text
    payload = after.json()
    assert payload["metric"]["current_status"] == "normal"
    assert payload["metric"]["trend_status"] == "stable"
    assert payload["metric"]["current_threshold"] == {
        "direction": "higher_better",
        "warning_threshold": 70.0,
        "critical_threshold": 60.0,
        "source": "custom",
    }
    assert payload["metric"]["change_threshold"] == {
        "value": 10.0,
        "unit": "pp",
        "source": "custom",
    }
    assert audits.status_code == 200, audits.text
    assert set(audits.json()["items"][0]["changed_fields"]) == {
        "critical_threshold",
        "warning_threshold",
        "daily_change_threshold",
        "daily_change_threshold_unit",
    }


def test_daily_health_detail_falls_back_to_same_device_previous_task() -> None:
    _cleanup()
    _seed_resources()
    points = [
        _point(TASK_ID, "ME_SUCCESS", ANCHOR, 15),
        _point(TASK_ID, "ME_TOTAL", ANCHOR, 20),
    ]
    history_points = [
        _point(HISTORY_TASK_ID, "ME_SUCCESS", ANCHOR - timedelta(days=1), 8),
        _point(HISTORY_TASK_ID, "ME_TOTAL", ANCHOR - timedelta(days=1), 10),
    ]
    task_db.publish_snapshot(_task(TASK_ID), rule_results=[_rule()], kpi_points=points)
    task_db.publish_snapshot(
        _task(HISTORY_TASK_ID, completed_at=ANCHOR - timedelta(days=1)),
        rule_results=[_rule()],
        kpi_points=history_points,
    )

    with _client() as client:
        response = client.get(f"/api/v2/tasks/{TASK_ID}/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_RATE")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["groups"][0]["today"]["value"] == 75.0
    assert payload["groups"][0]["yesterday"]["value"] == 80.0


def test_daily_health_detail_returns_explicit_not_available_for_legacy_result() -> None:
    _cleanup()
    _seed_resources()
    task_db.publish_snapshot(_task(TASK_ID), rule_results=[_rule(include_daily_health=False)], kpi_points=[])

    with _client() as client:
        response = client.get(f"/api/v2/tasks/{TASK_ID}/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_RATE")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "kpi_daily_health_not_available"


def test_daily_health_detail_not_found_boundaries() -> None:
    _cleanup()
    _seed_resources()
    _publish_current()

    with _client() as client:
        missing_task = client.get(f"/api/v2/tasks/missing/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_RATE")
        missing_rule = client.get(f"/api/v2/tasks/{TASK_ID}/rules/missing/daily-health/MU_CALL/ME_RATE")
        missing_metric = client.get(f"/api/v2/tasks/{TASK_ID}/rules/{KPI_RULE_CODE}/daily-health/MU_CALL/ME_MISSING")

    assert missing_task.status_code == 404
    assert missing_rule.status_code == 404
    assert missing_metric.status_code == 404
    assert missing_metric.json()["code"] == "kpi_daily_health_metric_not_found"


def test_metric_maintenance_config_list_patch_and_audit() -> None:
    _cleanup()
    _seed_resources()

    with _client() as client:
        listed = client.get("/api/v5/kpi/metric-maintenance-configs", params={"measurement_unit_id": "MU_CALL"})
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        assert payload["total"] == 3
        assert [item["metric_resource_id"] for item in payload["items"]] == ["ME_RATE", "ME_SUCCESS", "ME_TOTAL"]

        patched = client.patch(
            "/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE",
            json={
                "daily_aggregation": "mean",
                "daily_change_threshold": 0.2,
                "daily_change_threshold_unit": "pp",
                "zero_semantics": "business_not_triggered",
                "consistency_tolerance": 0.1,
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["daily_aggregation"] == "mean"
        assert patched.json()["config_source"] == "custom"

        audits = client.get("/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE/audits")
        assert audits.status_code == 200, audits.text
        audit = audits.json()["items"][0]
        assert audit["actor"] == "integration-admin"
        assert "daily_aggregation" in audit["changed_fields"]


def test_metric_maintenance_config_validation_and_permissions() -> None:
    _cleanup()
    _seed_resources()

    with _client() as client:
        empty = client.patch("/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE", json={})
        invalid = client.patch(
            "/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE",
            json={"consistency_tolerance": -1},
        )
        conflict = client.patch(
            "/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_SUCCESS",
            json={"role": "derived"},
        )

        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="viewer-token", username="viewer", role="viewer"
        )
        try:
            forbidden = client.patch(
                "/api/v5/kpi/metric-maintenance-configs/MU_CALL/ME_RATE",
                json={"enabled": False},
            )
        finally:
            app.dependency_overrides[get_current_user] = lambda: AuthSession(
                token="integration-test-token",
                username="integration-admin",
                role="admin",
            )

    assert empty.status_code == 400
    assert empty.json()["code"] == "kpi_metric_config_empty_update"
    assert invalid.status_code == 422
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "kpi_metric_role_requires_derived"
    assert forbidden.status_code == 403


def test_measurement_derived_list_detail_and_patch() -> None:
    _cleanup()
    _seed_resources()

    with _client() as client:
        listed = client.get("/api/v5/kpi/measurement-derived", params={"measurement_unit_id": "MU_CALL"})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        derived_id = listed.json()["items"][0]["id"]

        detail = client.get(f"/api/v5/kpi/measurement-derived/{derived_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["metric_resource_name_zh"] == "呼叫成功率"

        patched = client.patch(
            f"/api/v5/kpi/measurement-derived/{derived_id}",
            json={"template": "reverse_success_rate", "enabled": False},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["template"] == "reverse_success_rate"
        assert patched.json()["enabled"] is False

        missing = client.get("/api/v5/kpi/measurement-derived/999999")
        assert missing.status_code == 404
        assert missing.json()["code"] == "kpi_measurement_derived_not_found"
