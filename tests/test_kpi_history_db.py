"""KPI 历史点入库、DB 优先读取与现场清理后可查测试（034 US1 / T016）。"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from app.models.schemas import InspectionTask, RuleResult, RuleStatus, Summary, SystemInspection, TaskStats
from app.services import store, task_db
from app.services.kpi_history import (
    get_history_trend,
    get_version_candidates,
    get_version_compare,
    iter_history_index,
    write_history_index,
)
from tests.baseline_helpers import setup_env

KPI_CODE = "kpi.measurement_units"
COMPLETED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)


def _meta(task_id: str, *, completed_at: datetime, version: str = "V1", device_id: str = "device-a") -> InspectionTask:
    rule = RuleResult(
        code=KPI_CODE,
        name="测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status=RuleStatus.PASS,
        severity="medium",
        executed_at=completed_at,
    )
    summary = Summary.model_validate({"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0})
    stats = TaskStats.model_validate({**summary.model_dump(by_alias=True), "systems": 1})
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="local",
        status="completed",
        trigger="api",
        created_at=completed_at,
        completed_at=completed_at,
        last_run_at=completed_at,
        duration_ms=60_000,
        stats=stats,
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            package_checksum="d" * 64,
            version=version,
            status="completed",
            summary=summary,
            rules=[rule],
            customer={"device_id": device_id} if device_id else {},
        ),
    )


def _record(
    task_id: str,
    *,
    value: float,
    measured_at: str = "2026-09-10T09:00:00+00:00",
    object_key: str = "pod-a",
    period_minutes: int | None = 15,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "measurement_unit_id": "MU",
        "metric_resource_id": "ME",
        "object_key": object_key,
        "period_minutes": period_minutes,
        "measured_at": measured_at,
        "value": value,
        "source_file": "data/metrics.csv",
        "line_number": 1,
    }


def _publish(env, task: InspectionTask, records: list[dict[str, object]]) -> None:
    """模拟任务终态发布：先写现场索引，再整批入库。"""
    store.save_task_meta(env.output, task)
    write_history_index(task.task_id, records, output=env.output)
    task_db.publish_from_scene(task, output=env.output)


def test_kpi_points_mirror_scene_index_file(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task = _meta("task-kpi-mirror", completed_at=COMPLETED_AT)
    records = [
        _record(task.task_id, value=10),
        {**_record(task.task_id, value=12), "measured_at": "2026-09-10T10:00:00+00:00"},
    ]
    _publish(env, task, records)

    index_file = env.task_dir(task.task_id) / "kpi" / "history" / "index.jsonl"
    file_records = [json.loads(line) for line in index_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    db_points = task_db.list_kpi_points(task.task_id)
    assert len(db_points) == len(file_records) == 2
    for point, raw in zip(db_points, file_records, strict=True):
        assert point["task_id"] == raw["task_id"]
        assert point["measurement_unit_id"] == raw["measurement_unit_id"]
        assert point["metric_resource_id"] == raw["metric_resource_id"]
        assert point["object_key"] == raw["object_key"]
        assert point["period_minutes"] == raw["period_minutes"]
        assert point["measured_at"] == datetime.fromisoformat(raw["measured_at"])
        assert point["value"] == float(raw["value"])
        assert point["source_file"] == raw["source_file"]
        assert point["line_number"] == raw["line_number"]

    indexed = list(iter_history_index(task.task_id, output=env.output))
    assert [point["value"] for point in indexed] == [10.0, 12.0]
    assert [point["measured_at"].isoformat() for point in indexed] == [raw["measured_at"] for raw in file_records]


def test_history_queries_survive_scene_removal(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    current = _meta("task-kpi-current", completed_at=COMPLETED_AT, version="V2")
    baseline = _meta("task-kpi-baseline", completed_at=datetime(2026, 9, 9, 12, tzinfo=UTC), version="V1")
    _publish(env, baseline, [_record(baseline.task_id, value=100)])
    _publish(env, current, [_record(current.task_id, value=120)])

    def snapshot() -> tuple[object, ...]:
        trend = get_history_trend(
            current.task_id,
            rule_code=KPI_CODE,
            measurement_unit_id="MU",
            metric_resource_id="ME",
            object_key="pod-a",
            period_minutes=15,
            output=env.output,
        )
        candidates = get_version_candidates(
            current.task_id,
            rule_code=KPI_CODE,
            measurement_unit_id="MU",
            metric_resource_id="ME",
            object_key="pod-a",
            period_minutes=15,
            output=env.output,
        )
        compare = get_version_compare(
            current.task_id,
            rule_code=KPI_CODE,
            measurement_unit_id="MU",
            metric_resource_id="ME",
            object_key="pod-a",
            period_minutes=15,
            baseline_task_id=baseline.task_id,
            output=env.output,
        )
        return (
            trend.model_dump(mode="json"),
            candidates.model_dump(mode="json"),
            compare.model_dump(mode="json"),
            list(iter_history_index(current.task_id, output=env.output)),
        )

    before = snapshot()
    trend_before = before[0]
    assert trend_before["match"]["status"] == "matched"
    assert trend_before["coverage"]["history_point_count"] == 1
    assert before[2]["match"]["status"] == "matched"
    assert [item["version"] for item in before[1]["items"]] == ["V1"]

    shutil.rmtree(env.task_dir(current.task_id))
    shutil.rmtree(env.task_dir(baseline.task_id))
    assert not env.task_dir(current.task_id).exists()

    after = snapshot()
    assert after == before


def test_iter_history_index_falls_back_to_scene_file_for_legacy_task(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task = _meta("task-kpi-legacy", completed_at=COMPLETED_AT)
    store.save_task_meta(env.output, task)
    write_history_index(task.task_id, [_record(task.task_id, value=42)], output=env.output)

    indexed = list(iter_history_index(task.task_id, output=env.output))
    assert [point["value"] for point in indexed] == [42.0]
