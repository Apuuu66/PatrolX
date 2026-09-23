"""历史趋势 API 契约测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.kpi_history import write_history_index
from app.services.store import save_task_meta
from tests.baseline_helpers import setup_env
from tests.test_kpi_device_history import _meta


def _prepare_current(env) -> None:
    task_id = "task-history"
    meta = _meta(task_id)
    meta.system.customer["device_id"] = ""
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
                "period_minutes": None,
                "measured_at": "2026-09-10T10:00:00+00:00",
                "value": 10,
                "source_file": "a.csv",
                "line_number": 1,
            }
        ],
        output=env.output,
    )


def test_history_api_contract_and_validation(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _prepare_current(env)
    client = TestClient(app)
    response = client.get(
        "/api/v2/tasks/task-history/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/history-trend",
        params=[("object_key", "pod-a"), ("period_minutes", "")],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == "task-history"
    assert body["period_minutes"] is None
    assert body["match"]["status"] == "degraded"
    assert body["match"]["reason_code"] == "device_id_missing"
    assert body["coverage"]["current_point_count"] == 1

    missing = client.get(
        "/api/v2/tasks/task-history/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/history-trend",
        params={"object_key": "pod-a"},
    )
    assert missing.status_code == 422
    not_found = client.get(
        "/api/v2/tasks/missing/rules/kpi.measurement_units/measurement-units/MU/metrics/ME/history-trend",
        params={"object_key": "pod-a", "period_minutes": 15},
    )
    assert not_found.status_code == 404
    rule_missing = client.get(
        "/api/v2/tasks/task-history/rules/not.exists/measurement-units/MU/metrics/ME/history-trend",
        params={"object_key": "pod-a", "period_minutes": 15},
    )
    assert rule_missing.status_code == 404
