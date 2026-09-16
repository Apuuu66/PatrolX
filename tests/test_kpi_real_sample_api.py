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


def test_enriched_sample_kpi_payloads_remain_bounded(tmp_path, monkeypatch) -> None:
    """规则详情与最大分页记录响应必须保持前端可消费的体积。"""
    import time

    env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)
    task_id = upload_package(env, client, name="KPI payload smoke")
    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"

    rule_response = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call",
        params={"exclude_records": "true"},
    )
    assert rule_response.status_code == 200
    assert len(rule_response.content) < 2_000_000

    records_response = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"page_size": 200},
    )
    assert records_response.status_code == 200
    assert len(records_response.content) < 200_000

    started = time.monotonic()
    filtered_response = client.get(
        f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records",
        params={"metric_key": "call_success_rate", "page_size": 200},
    )
    elapsed = time.monotonic() - started
    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] > 0
    # 宽松性能烟测：避免 CI 波动，只拦截明显的同步全量膨胀问题。
    assert elapsed < 5.0


def test_kpi_records_stay_readable_during_single_rule_rerun(tmp_path, monkeypatch) -> None:
    """单规则重跑期间 records 查询不得返回 5xx 或空态污染。"""
    from concurrent.futures import ThreadPoolExecutor

    env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)
    task_id = upload_package(env, client, name="KPI rerun concurrency")
    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"
    records_url = f"/api/v2/tasks/{task_id}/rules/kpi.call/kpi/records"

    rerun_response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["kpi.call"]},
    )
    assert rerun_response.status_code == 202, rerun_response.text

    def query_records(page: int) -> tuple[int, int, int]:
        response = client.get(records_url, params={"page": page, "page_size": 50})
        body = response.json() if response.status_code == 200 else {}
        return response.status_code, body.get("total", 0), len(body.get("items", []))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(query_records, range(1, 13)))

    for page, (status_code, total, item_count) in enumerate(results, start=1):
        assert status_code == 200, (page, status_code)
        assert total > 0, (page, total, item_count)
        assert item_count == 50, (page, total, item_count)

    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"
    rule = client.get(f"/api/v2/tasks/{task_id}/rules/kpi.call", params={"exclude_records": "true"}).json()
    assert rule["status"] != "error"
    final_response = client.get(records_url, params={"page_size": 50})
    assert final_response.status_code == 200
    assert final_response.json()["total"] > 0
