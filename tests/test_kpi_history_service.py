"""跨任务历史趋势服务测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.schemas import InspectionTask, RuleResult, RuleStatus, Summary, SystemInspection, TaskStats
from app.services.kpi_history import get_history_trend, write_history_index
from app.services.store import save_task_meta


def _meta(task_id: str, completed_at: datetime, device_id: str | None = "device-a") -> InspectionTask:
    rule = RuleResult(
        code="kpi.measurement_units",
        name="测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status=RuleStatus.PASS,
        severity="medium",
    )
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="local",
        status="completed",
        trigger="api",
        created_at=completed_at - timedelta(days=1),
        completed_at=completed_at,
        stats=TaskStats.model_validate(
            {"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1}
        ),
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            status="completed",
            summary=Summary.model_validate({"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0}),
            rules=[rule],
            customer={"device_id": device_id} if device_id else {},
        ),
    )


def _task(env, task_id: str, completed_at: datetime, device_id: str | None) -> None:
    save_task_meta(env.output, _meta(task_id, completed_at, device_id))


def _write(env, task_id: str, at: datetime, value: float) -> None:
    write_history_index(
        task_id,
        [
            {
                "task_id": task_id,
                "measurement_unit_id": "MU",
                "metric_resource_id": "ME",
                "object_key": "pod-a",
                "period_minutes": 15,
                "measured_at": at.isoformat(),
                "value": value,
                "source_file": "data.csv",
                "line_number": 1,
            }
        ],
        output=env.output,
    )


def _query(env, task_id: str, **kwargs):
    return get_history_trend(
        task_id,
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU",
        metric_resource_id="ME",
        object_key=kwargs.get("object_key", "pod-a"),
        period_minutes=kwargs.get("period_minutes", 15),
        output=env.output,
    )


def test_history_matches_only_same_device_and_dimension(tmp_path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    completed = datetime(2026, 9, 10, 12, tzinfo=UTC)
    _task(env, "current", completed, "device-a")
    _write(env, "current", datetime(2026, 9, 10, 10, tzinfo=UTC), 10)
    _task(env, "same", completed - timedelta(days=1), "device-a")
    _write(env, "same", datetime(2026, 9, 9, 10, tzinfo=UTC), 11)
    _task(env, "device", completed - timedelta(days=1), "device-b")
    _write(env, "device", datetime(2026, 9, 9, 10, tzinfo=UTC), 99)
    _task(env, "object", completed - timedelta(days=1), "device-a")
    _write(env, "object", datetime(2026, 9, 9, 10, tzinfo=UTC), 99)
    result = _query(env, "current")
    assert result.match.status == "matched"
    assert result.source_tasks == ["same"]
    assert result.coverage.history_point_count == 1


def test_history_window_and_latest_completion_conflict(tmp_path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    at = datetime(2026, 9, 10, 10, tzinfo=UTC)
    _task(env, "current", datetime(2026, 9, 10, 12, tzinfo=UTC), "device-a")
    _write(env, "current", at, 10)
    _task(env, "old", datetime(2026, 9, 8, 12, tzinfo=UTC), "device-a")
    _write(env, "old", at, 1)
    _task(env, "new", datetime(2026, 9, 9, 12, tzinfo=UTC), "device-a")
    _write(env, "new", at, 2)
    result = _query(env, "current")
    assert result.window.start_date == "2026-09-04"
    assert result.window.end_date == "2026-09-10"
    assert result.source_tasks == ["new"]
    assert result.history_series[0].points[0].value == 2


def test_baseline_median_mad_and_insufficient(tmp_path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    completed = datetime(2026, 9, 10, 12, tzinfo=UTC)
    _task(env, "current", completed, "device-a")
    _write(env, "current", datetime(2026, 9, 10, 10, tzinfo=UTC), 30)
    for index, value in enumerate((10, 12, 14), start=7):
        task_id = f"base-{index}"
        _task(env, task_id, datetime(2026, 9, index, 12, tzinfo=UTC), "device-a")
        _write(env, task_id, datetime(2026, 9, index, 10, tzinfo=UTC), value)
    result = _query(env, "current")
    baseline = result.baseline_points[0]
    assert baseline.baseline_value == 12
    assert baseline.significance == "higher"
    assert baseline.deviation == 18
    assert baseline.deviation_ratio == 1.5
    assert baseline.sample_count == 3
    assert baseline.date_count == 3

    _task(env, "insufficient", datetime(2026, 9, 9, 12, tzinfo=UTC), "device-a")
    _write(env, "insufficient", datetime(2026, 9, 9, 11, tzinfo=UTC), 1)
    _write(env, "current", datetime(2026, 9, 10, 11, tzinfo=UTC), 30)
    result = _query(env, "current")
    insufficient = next(item for item in result.baseline_points if item.time_label == "11:00")
    assert insufficient.significance == "insufficient"


def test_missing_device_or_index_degrades(tmp_path, monkeypatch) -> None:
    from tests.baseline_helpers import setup_env

    env = setup_env(tmp_path, monkeypatch)
    completed = datetime(2026, 9, 10, 12, tzinfo=UTC)
    _task(env, "no-device", completed, None)
    _write(env, "no-device", datetime(2026, 9, 10, 10, tzinfo=UTC), 1)
    result = _query(env, "no-device")
    assert result.match.status == "degraded"
    assert result.match.reason_code == "device_id_missing"

    _task(env, "no-index", completed, "device-a")
    result = _query(env, "no-index")
    assert result.match.status == "degraded"
    assert result.match.reason_code == "history_index_missing"
