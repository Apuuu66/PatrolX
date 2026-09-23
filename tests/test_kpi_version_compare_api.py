"""KPI 版本对比 API 契约测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.kpi_history import write_history_index
from app.services.store import save_task_meta
from tests.baseline_helpers import setup_env
from tests.test_kpi_device_history import _meta


def _prepare(env, task_id: str, *, version: str | None, device_id: str = "device-a") -> None:
    meta = _meta(task_id)
    meta.system.customer["device_id"] = device_id
    meta.system.version = version
    save_task_meta(env.output, meta)
    (env.task_dir(task_id) / "rules").mkdir(parents=True, exist_ok=True)
    (env.task_dir(task_id) / "rules" / "kpi.measurement_units.json").write_text("{}", encoding="utf-8")
    write_history_index(
        task_id,
        [
            {
                "task_id": task_id,
                "measurement_unit_id": "MU",
                "metric_resource_id": "ME",
                "object_key": "pod-a",
                "period_minutes": 15,
                "measured_at": "2026-09-10T08:00:00+00:00",
                "value": 100,
                "source_file": "a.csv",
                "line_number": 1,
            },
            {
                "task_id": task_id,
                "measurement_unit_id": "MU",
                "metric_resource_id": "ME",
                "object_key": "pod-a",
                "period_minutes": 15,
                "measured_at": "2026-09-10T09:00:00+00:00",
                "value": 100,
                "source_file": "a.csv",
                "line_number": 2,
            },
            {
                "task_id": task_id,
                "measurement_unit_id": "MU",
                "metric_resource_id": "ME",
                "object_key": "pod-a",
                "period_minutes": 15,
                "measured_at": "2026-09-10T10:00:00+00:00",
                "value": 100,
                "source_file": "a.csv",
                "line_number": 3,
            },
        ],
        output=env.output,
    )


def test_version_candidates_api_contract(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare(env, "task-version-current", version="V2")
    _prepare(env, "task-version-baseline", version="V1")
    client = TestClient(app)
    response = client.get(
        "/api/v2/tasks/task-version-current/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/version-candidates",
        params={"object_key": "pod-a", "period_minutes": 15},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["device_id"] == "device-a"
    assert body["current_version"] == "V2"
    assert [item["version"] for item in body["items"]] == ["V1"]
    assert body["items"][0]["latest_task_id"] == "task-version-baseline"


def test_version_compare_api_contract_and_errors(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare(env, "task-version-current", version="V2")
    _prepare(env, "task-version-baseline", version="V1")
    client = TestClient(app)
    response = client.get(
        "/api/v2/tasks/task-version-current/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/version-compare",
        params={"baseline_task_id": "task-version-baseline", "object_key": "pod-a", "period_minutes": 15},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["match"]["status"] == "matched"
    assert body["current_version"] == "V2"
    assert body["baseline_version"] == "V1"
    assert body["baseline_task"]["task_id"] == "task-version-baseline"
    assert body["summary"]["direction"] == "flat"

    missing = client.get(
        "/api/v2/tasks/task-version-current/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/version-compare",
        params={"baseline_task_id": "missing", "object_key": "pod-a", "period_minutes": 15},
    )
    assert missing.status_code == 200
    assert missing.json()["match"]["reason_code"] == "baseline_task_not_found"

    validation = client.get(
        "/api/v2/tasks/task-version-current/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/version-compare",
        params={"object_key": "pod-a", "period_minutes": 15},
    )
    assert validation.status_code == 422

    not_found = client.get(
        "/api/v2/tasks/missing/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/version-compare",
        params={"baseline_task_id": "task-version-baseline", "object_key": "pod-a", "period_minutes": 15},
    )
    assert not_found.status_code == 404

    rule_missing = client.get(
        "/api/v2/tasks/task-version-current/rules/not.exists/measurement-units/MU/metrics/ME/version-compare",
        params={"baseline_task_id": "task-version-baseline", "object_key": "pod-a", "period_minutes": 15},
    )
    assert rule_missing.status_code == 404
