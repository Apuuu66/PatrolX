"""真实富化样例的 KPI 在线链路验证。"""

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import setup_env, upload_package, wait_for_task


def test_enriched_sample_kpi_api_remains_stable(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)

    task_id = upload_package(env, client, name="富化 KPI 样例")
    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"

    rule = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call", params={"exclude_records": "true"}).json()
    assert rule["status"] != "error"
    assert rule["metadata"]["version"] >= 2
    assert rule["metadata"]["metric_catalog"]
    assert rule["metadata"]["kpi_results"]
    assert not any(file.get("records") for file in rule["metadata"]["kpi_files"])

    records_url = f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records"
    first = client.get(records_url, params={"page": 1, "page_size": 50})
    assert first.status_code == 200
    first_page = first.json()
    assert first_page["total"] > 0
    assert len(first_page["items"]) <= 50

    second = client.get(records_url, params={"page": 2, "page_size": 50})
    assert second.status_code == 200
    second_page = second.json()
    assert second_page["total"] == first_page["total"]
    first_ids = {(item["metric_key"], item["source_file"], item["line_number"]) for item in first_page["items"]}
    second_ids = {(item["metric_key"], item["source_file"], item["line_number"]) for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)

    filtered = client.get(
        records_url,
        params={"metric_key": "call_success_rate", "source_file": "kpi/kpi-call-5.csv", "period_minutes": 5},
    )
    assert filtered.status_code == 200
    for item in filtered.json()["items"]:
        assert item["metric_key"] == "call_success_rate"
        assert item["source_file"] == "kpi/kpi-call-5.csv"
        assert item["period_minutes"] == 5
