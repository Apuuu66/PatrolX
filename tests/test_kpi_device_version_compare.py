"""KPI 同设备版本对比服务测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.db import KpiMeasurementResource, session_factory
from app.services.kpi_history import get_version_candidates, get_version_compare, write_history_index
from app.services.store import save_task_meta
from tests.baseline_helpers import setup_env
from tests.test_kpi_device_history import _meta


def _version_meta(
    task_id: str,
    *,
    device_id: str = "device-a",
    version: str | None = "V2",
    completed_offset_hours: int = 0,
    status: str = "completed",
):
    meta = _meta(task_id, status=status)
    if meta.completed_at:
        meta.completed_at = meta.completed_at + timedelta(hours=completed_offset_hours)
    meta.system.customer["device_id"] = device_id
    meta.system.version = version
    return meta


def _record(
    task_id: str,
    *,
    value: int,
    measured_at: str,
    object_key: str = "pod-a",
    period_minutes: int | None = 15,
    metric_resource_id: str = "ME_CALL",
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "measurement_unit_id": "MU_CALL",
        "metric_resource_id": metric_resource_id,
        "object_key": object_key,
        "period_minutes": period_minutes,
        "measured_at": measured_at,
        "value": value,
        "source_file": "call.csv",
        "line_number": 1,
    }


def _prepare_pair(env, *, baseline_version: str | None = "V1") -> None:
    save_task_meta(env.output, _version_meta("task-version-current", version="V2"))
    baseline = _version_meta("task-version-baseline", version=baseline_version, completed_offset_hours=-24)
    save_task_meta(env.output, baseline)
    write_history_index(
        "task-version-current",
        [
            _record("task-version-current", value=120, measured_at="2026-09-10T08:00:00+00:00"),
            _record("task-version-current", value=140, measured_at="2026-09-10T09:00:00+00:00"),
        ],
        output=env.output,
    )
    write_history_index(
        "task-version-baseline",
        [
            _record("task-version-baseline", value=100, measured_at="2026-09-01T08:00:00+00:00"),
            _record("task-version-baseline", value=110, measured_at="2026-09-01T09:00:00+00:00"),
            _record("task-version-baseline", value=120, measured_at="2026-09-01T10:00:00+00:00"),
        ],
        output=env.output,
    )


def test_version_candidates_filter_device_and_select_latest(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    save_task_meta(env.output, _version_meta("task-version-current-old", version="V2", completed_offset_hours=-48))
    save_task_meta(env.output, _version_meta("task-version-other-device", device_id="device-b", version="V0"))
    save_task_meta(env.output, _version_meta("task-version-unknown", version=None))

    result = get_version_candidates(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        output=env.output,
    )

    assert result.device_id == "device-a"
    assert result.current_version == "V2"
    versions = {item.version: item for item in result.items}
    assert set(versions) == {"V1", "V2", None}
    assert versions["V1"].latest_task_id == "task-version-baseline"
    assert versions["V1"].task_count == 1
    assert versions["V2"].latest_task_id == "task-version-current-old"
    assert versions["V2"].task_count == 1
    assert versions[None].version_known is False
    assert versions[None].latest_task_id == "task-version-unknown"


def test_version_compare_matches_same_dimension_and_builds_mean_summary(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    result = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )

    assert result.match.status == "matched"
    assert result.current_version == "V2"
    assert result.baseline_version == "V1"
    assert result.baseline_task.task_id == "task-version-baseline"
    assert result.current_points[0].task_id == "task-version-current"
    assert result.baseline_points[0].task_id == "task-version-baseline"
    assert result.summary.current_value == 130
    assert result.summary.baseline_value == 110
    assert result.summary.change_ratio == 20 / 110
    assert result.summary.absolute_change == 20
    assert result.summary.direction == "up"
    assert "上涨" in result.summary.message


def test_version_compare_rejects_same_known_version(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    result = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-current",
        output=env.output,
    )
    assert result.match.status == "degraded"
    assert result.match.reason_code == "baseline_same_version"


def test_version_compare_allows_unknown_versions_with_clear_display(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env, baseline_version=None)
    save_task_meta(env.output, _version_meta("task-version-current", version=None))
    result = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )
    assert result.match.status == "matched"
    assert result.current_version is None
    assert result.baseline_version is None
    assert "版本未知" in result.match.message


def test_version_compare_reports_missing_indexes_and_dimension(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    (env.output / "task-version-baseline" / "kpi" / "history" / "index.jsonl").unlink()
    missing_index = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )
    assert missing_index.match.status == "degraded"
    assert missing_index.match.reason_code == "baseline_index_missing"

    _prepare_pair(env)
    dimension = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-b",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )
    assert dimension.match.status == "degraded"
    assert dimension.match.reason_code == "current_metric_dimension_missing"

    write_history_index(
        "task-version-current",
        [
            _record(
                "task-version-current",
                metric_resource_id="ME_OTHER",
                value=1,
                measured_at="2026-09-10T08:00:00+00:00",
            )
        ],
        output=env.output,
    )
    baseline_dimension = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_OTHER",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )
    assert baseline_dimension.match.status == "no_history"
    assert baseline_dimension.match.reason_code == "baseline_object_or_period_mismatch"

    current_missing = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_OTHER",
        metric_resource_id="ME_OTHER",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )
    assert current_missing.match.status == "degraded"
    assert current_missing.match.reason_code == "current_metric_dimension_missing"


def test_version_compare_reports_not_completed_and_device_mismatch(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    save_task_meta(env.output, _version_meta("task-version-current", version="V2"))
    save_task_meta(env.output, _version_meta("task-version-running", status="running", version="V1"))
    running = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-running",
        output=env.output,
    )
    assert running.match.status == "degraded"
    assert running.match.reason_code == "baseline_task_not_completed"

    save_task_meta(env.output, _version_meta("task-version-other-device", device_id="device-b", version="V1"))
    mismatch = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-other-device",
        output=env.output,
    )
    assert mismatch.match.status == "degraded"
    assert mismatch.match.reason_code == "baseline_device_mismatch"


def _set_metric_direction(resource_id: str, direction: str) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            KpiMeasurementResource(
                resource_id=resource_id,
                kind="me",
                name_zh="测试指标",
                name_en="Test Metric",
                enabled=True,
                direction=direction,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_version_compare_explains_lower_better_metric(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    _set_metric_direction("ME_CALL", "lower_better")
    write_history_index(
        "task-version-current",
        [
            _record("task-version-current", value=80, measured_at="2026-09-10T08:00:00+00:00"),
            _record("task-version-current", value=90, measured_at="2026-09-10T09:00:00+00:00"),
            _record("task-version-current", value=100, measured_at="2026-09-10T10:00:00+00:00"),
        ],
        output=env.output,
    )
    write_history_index(
        "task-version-baseline",
        [
            _record("task-version-baseline", value=100, measured_at="2026-09-01T08:00:00+00:00"),
            _record("task-version-baseline", value=110, measured_at="2026-09-01T09:00:00+00:00"),
            _record("task-version-baseline", value=120, measured_at="2026-09-01T10:00:00+00:00"),
        ],
        output=env.output,
    )

    result = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )

    assert result.match.status == "matched"
    assert result.summary.direction == "down"
    assert "下降" in result.summary.message
    assert "越低越好" in result.summary.message
    assert "改善" in result.summary.message


def test_version_compare_reports_insufficient_baseline_samples(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_pair(env)
    write_history_index(
        "task-version-current",
        [
            _record("task-version-current", value=120, measured_at="2026-09-10T08:00:00+00:00"),
            _record("task-version-current", value=130, measured_at="2026-09-10T09:00:00+00:00"),
            _record("task-version-current", value=140, measured_at="2026-09-10T10:00:00+00:00"),
        ],
        output=env.output,
    )
    write_history_index(
        "task-version-baseline",
        [
            _record("task-version-baseline", value=100, measured_at="2026-09-01T08:00:00+00:00"),
            _record("task-version-baseline", value=110, measured_at="2026-09-01T09:00:00+00:00"),
        ],
        output=env.output,
    )

    result = get_version_compare(
        "task-version-current",
        rule_code="kpi.measurement_units",
        measurement_unit_id="MU_CALL",
        metric_resource_id="ME_CALL",
        object_key="pod-a",
        period_minutes=15,
        baseline_task_id="task-version-baseline",
        output=env.output,
    )

    assert result.match.status == "matched"
    assert result.summary.direction == "unknown"
    assert "基线样本不足 3 个" in result.summary.message
    assert "暂不输出" in result.summary.message
