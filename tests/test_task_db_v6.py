"""v6 任务快照与 KPI 结果的持久化边界测试（041 T012）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.db import TaskRecord, session_factory
from app.services import task_db
from tests.baseline_helpers import setup_env

NOW = datetime(2026, 11, 5, 8, tzinfo=UTC)
LATER = datetime(2026, 11, 5, 9, tzinfo=UTC)
TASK_ID = "task-v6-db"
NETWORK_TYPE = "UMF"


def _task_record(task_id: str = TASK_ID) -> None:
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                name=task_id,
                mode="local",
                status="completed",
                trigger="api",
                package_file=f"{task_id}.zip",
                customer={"product": NETWORK_TYPE},
                package_kind="inspection",
                stats={},
                created_at=NOW,
            )
        )
        session.commit()


def _rule_snapshot(task_id: str = TASK_ID) -> task_db.RuleScopeSnapshotData:
    return task_db.RuleScopeSnapshotData(
        task_id=task_id,
        network_element_type=NETWORK_TYPE,
        assignment_revision=3,
        registry_fingerprint="a" * 64,
        trigger="api",
        source="task_service",
        frozen_at=NOW,
        snapshot_state="frozen",
        items=(
            task_db.RuleScopeItemData(
                rule_code="kpi.measurement_units",
                rule_version="1.0.0",
                category="kpi",
                priority=1,
                execution_order=10,
                assignment_snapshot={"network_element_types": [NETWORK_TYPE]},
            ),
        ),
    )


def _kpi_snapshot(task_id: str = TASK_ID) -> task_db.KpiScopeSnapshotData:
    return task_db.KpiScopeSnapshotData(
        task_id=task_id,
        network_element_type=NETWORK_TYPE,
        team_focus_revision=2,
        config_fingerprint="b" * 64,
        data_date=date(2026, 11, 5),
        frozen_at=NOW,
        snapshot_payload={"enabled_measurement_unit_ids": ["MU-1"]},
        items=(
            task_db.KpiScopeItemData(
                measurement_unit_id="MU-1",
                metric_resource_id="ME-SUCCESS-RATE",
                metric_kind="base",
                config_snapshot={
                    "name_zh": "媒体资源创建成功率",
                    "role": "base",
                    "raw_source_names": [
                        "Media Resource Creation Success Rate(%)",
                        "Media Resource Creation Requests Success Rate(%)",
                    ],
                },
                scope_status="ready",
            ),
            task_db.KpiScopeItemData(
                measurement_unit_id="MU-1",
                metric_resource_id="ME-REQUEST-COUNT",
                metric_kind="base",
                config_snapshot={"name_zh": "媒体资源创建请求数", "role": "base"},
                scope_status="ready",
            ),
            task_db.KpiScopeItemData(
                measurement_unit_id="MU-2",
                metric_resource_id="ME-OTHER",
                metric_kind="base",
                config_snapshot={"name_zh": "其他指标", "role": "base"},
                scope_status="ready",
            ),
        ),
    )


def _result(
    *,
    task_id: str = TASK_ID,
    measurement_unit_id: str = "MU-1",
    metric_resource_id: str = "ME-SUCCESS-RATE",
    source_rule_code: str = "kpi.measurement_units",
    fingerprint: str = "c" * 64,
    value: float | None = 98.5,
    published_at: datetime = NOW,
) -> task_db.KpiMetricResultData:
    return task_db.KpiMetricResultData(
        task_id=task_id,
        network_element_type=NETWORK_TYPE,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        source_rule_code=source_rule_code,
        decision="pass",
        special_state=None,
        yesterday_trend="stable",
        needs_attention_group=None,
        today_value=value,
        yesterday_value=97.9,
        change=0.6,
        unit="%",
        importance="P1",
        reason="来源成功率正常",
        effective_point_count=4,
        result_payload={"metric_role": "base", "formula": None},
        result_fingerprint=fingerprint,
        published_at=published_at,
    )


def _point(
    *,
    task_id: str = TASK_ID,
    measurement_unit_id: str = "MU-1",
    metric_resource_id: str = "ME-SUCCESS-RATE",
    source_rule_code: str = "kpi.measurement_units",
    fingerprint: str = "d" * 64,
    value: float | None = 98.5,
    measured_at: datetime = NOW,
) -> task_db.KpiPointData:
    return task_db.KpiPointData(
        task_id=task_id,
        network_element_type=NETWORK_TYPE,
        source_rule_code=source_rule_code,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        object_key="__all__",
        period_minutes=15,
        measured_at=measured_at,
        value=value,
        source_file="data/metrics.csv",
        line_number=12,
        point_fingerprint=fingerprint,
    )


def test_v6_scope_snapshots_round_trip_with_explicit_network_scope(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    rule_snapshot = _rule_snapshot()
    kpi_snapshot = _kpi_snapshot()

    task_db.save_task_scope_snapshots(rule_snapshot=rule_snapshot, kpi_snapshot=kpi_snapshot)

    assert task_db.get_rule_scope_snapshot(TASK_ID, network_element_type=NETWORK_TYPE) == rule_snapshot
    loaded = task_db.get_kpi_scope_snapshot(TASK_ID, network_element_type=NETWORK_TYPE)
    assert loaded is not None
    assert loaded.items == tuple(
        sorted(kpi_snapshot.items, key=lambda item: (item.measurement_unit_id, item.metric_resource_id))
    )
    assert loaded == replace(kpi_snapshot, items=loaded.items)
    assert task_db.get_kpi_scope_snapshot(TASK_ID, network_element_type="CSP") is None
    assert task_db.get_kpi_scope_snapshot("old-task", network_element_type=NETWORK_TYPE) is None


def test_v6_publish_rolls_back_results_and_points_together(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    task_db.save_task_scope_snapshots(rule_snapshot=_rule_snapshot(), kpi_snapshot=_kpi_snapshot())
    task = task_db.get_task(TASK_ID)
    assert task is not None
    task_db.publish_kpi_v6_snapshot(
        task,
        metric_results=[_result()],
        metric_points=[_point()],
    )

    with pytest.raises(IntegrityError):
        task_db.publish_kpi_v6_snapshot(
            task,
            metric_results=[
                _result(fingerprint="e" * 64, value=99.0),
                _result(fingerprint="e" * 64, value=99.1),
            ],
            metric_points=[_point(fingerprint="f" * 64, value=99.0)],
        )

    results = task_db.list_kpi_metric_results_v6(TASK_ID, network_element_type=NETWORK_TYPE)
    points = task_db.list_kpi_points_v6(TASK_ID, network_element_type=NETWORK_TYPE)
    assert [result["today_value"] for result in results] == [98.5]
    assert [point["value"] for point in points] == [98.5]


def test_v6_publish_can_replace_only_one_source_rule_atomically(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    task_db.save_task_scope_snapshots(rule_snapshot=_rule_snapshot(), kpi_snapshot=_kpi_snapshot())
    task = task_db.get_task(TASK_ID)
    assert task is not None
    task_db.publish_kpi_v6_snapshot(
        task,
        metric_results=[
            _result(metric_resource_id="ME-SUCCESS-RATE", fingerprint="1" * 64, value=98.0),
            _result(
                measurement_unit_id="MU-2",
                metric_resource_id="ME-OTHER",
                source_rule_code="rule.other",
                fingerprint="2" * 64,
                value=7.0,
            ),
        ],
        metric_points=[
            _point(metric_resource_id="ME-SUCCESS-RATE", fingerprint="3" * 64, value=98.0),
            _point(
                measurement_unit_id="MU-2",
                metric_resource_id="ME-OTHER",
                source_rule_code="rule.other",
                fingerprint="4" * 64,
                value=7.0,
            ),
        ],
    )

    task_db.publish_kpi_v6_snapshot(
        task,
        metric_results=[_result(metric_resource_id="ME-SUCCESS-RATE", fingerprint="5" * 64, value=99.0)],
        metric_points=[_point(metric_resource_id="ME-SUCCESS-RATE", fingerprint="6" * 64, value=99.0)],
        replace_source_rule_codes={"kpi.measurement_units"},
    )

    results = task_db.list_kpi_metric_results_v6(TASK_ID, network_element_type=NETWORK_TYPE)
    points = task_db.list_kpi_points_v6(TASK_ID, network_element_type=NETWORK_TYPE)
    assert {(row["metric_resource_id"], row["today_value"]) for row in results} == {
        ("ME-SUCCESS-RATE", 99.0),
        ("ME-OTHER", 7.0),
    }
    assert {(row["metric_resource_id"], row["value"]) for row in points} == {
        ("ME-SUCCESS-RATE", 99.0),
        ("ME-OTHER", 7.0),
    }


def test_v6_publish_rejects_metric_outside_frozen_kpi_scope(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    task_db.save_task_scope_snapshots(rule_snapshot=_rule_snapshot(), kpi_snapshot=_kpi_snapshot())
    task = task_db.get_task(TASK_ID)
    assert task is not None
    task_db.publish_kpi_v6_snapshot(task, metric_results=[_result()], metric_points=[_point()])

    with pytest.raises(task_db.KpiV6DataError) as exc_info:
        task_db.publish_kpi_v6_snapshot(
            task,
            metric_results=[_result(metric_resource_id="ME-NOT-IN-SCOPE", fingerprint="7" * 64, value=1.0)],
            metric_points=[],
        )

    assert exc_info.value.code == "kpi_result_scope_mismatch"
    assert [
        row["metric_resource_id"]
        for row in task_db.list_kpi_metric_results_v6(TASK_ID, network_element_type=NETWORK_TYPE)
    ] == ["ME-SUCCESS-RATE"]


def test_v6_publish_without_snapshot_requires_rebuild(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    task = task_db.get_task(TASK_ID)
    assert task is not None

    with pytest.raises(task_db.KpiV6DataError) as exc_info:
        task_db.publish_kpi_v6_snapshot(task, metric_results=[], metric_points=[])

    assert exc_info.value.code == "task_result_requires_rebuild"
    assert exc_info.value.status_code == 409


def test_v6_metric_and_point_reads_are_scoped_and_filterable(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _task_record()
    task_db.save_task_scope_snapshots(rule_snapshot=_rule_snapshot(), kpi_snapshot=_kpi_snapshot())
    task = task_db.get_task(TASK_ID)
    assert task is not None
    task_db.publish_kpi_v6_snapshot(
        task,
        metric_results=[_result()],
        metric_points=[
            _point(fingerprint="8" * 64, value=97.0, measured_at=NOW),
            _point(fingerprint="9" * 64, value=98.0, measured_at=LATER),
        ],
    )

    result = task_db.get_kpi_metric_result_v6(
        TASK_ID,
        network_element_type=NETWORK_TYPE,
        measurement_unit_id="MU-1",
        metric_resource_id="ME-SUCCESS-RATE",
    )
    points = task_db.list_kpi_points_v6(
        TASK_ID,
        network_element_type=NETWORK_TYPE,
        measurement_unit_id="MU-1",
        metric_resource_id="ME-SUCCESS-RATE",
        start_at=NOW,
        end_at=LATER,
    )

    assert result is not None and result["result_payload"] == {"metric_role": "base", "formula": None}
    assert [point["value"] for point in points] == [97.0]
    assert task_db.list_kpi_points_v6(TASK_ID, network_element_type="CSP") == []
