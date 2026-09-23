"""在线模式 API 集成测试（TestClient + 后台任务队列）。"""

import io
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.kpi_measurement_units import import_resource_csv

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
client = TestClient(app)


def _upload(package_name: str = "sample.zip") -> str:
    with SAMPLE.open("rb") as fh:
        resp = client.post(
            "/api/v2/tasks",
            files={"package_file": (package_name, fh, "application/zip")},
            data={"name": "API 样例任务"},
        )
    assert resp.status_code == 202, resp.text
    return resp.json()["task_id"]


def _wait(task_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/v2/tasks/{task_id}").json()
        if task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.1)
    raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内完成")


def test_upload_list_system_rules_report_logs_delete() -> None:
    task_id = _upload()
    task = _wait(task_id)
    assert task["status"] == "completed"
    assert task["stats"]["fail"] >= 1

    system = client.get(f"/api/v2/tasks/{task_id}/system").json()
    assert system["summary"]["total"] >= 10

    rule = client.get(f"/api/v2/tasks/{task_id}/rules/log.error_density").json()
    assert rule["code"] == "log.error_density"
    assert rule["status"] in ("pass", "warn", "fail")

    report = client.get(f"/api/v2/tasks/{task_id}/report")
    assert report.status_code == 200 and "PatrolX" in report.text

    logs = client.get(f"/api/v2/tasks/{task_id}/logs").json()
    assert logs["entries"]

    listing = client.get("/api/v2/tasks").json()
    assert listing["total"] >= 1

    assert client.delete(f"/api/v2/tasks/{task_id}").status_code == 204
    assert client.get(f"/api/v2/tasks/{task_id}").status_code == 404


def test_rerun_single_rule() -> None:
    task_id = _upload("rerun-api.zip")
    _wait(task_id)
    resp = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202
    task = _wait(task_id)
    assert task["status"] == "completed"
    rule = client.get(f"/api/v2/tasks/{task_id}/rules/log.error_density").json()
    assert rule["code"] == "log.error_density"


def test_dicts_api() -> None:
    resp = client.get("/api/v2/dicts")
    assert resp.status_code == 200
    assert resp.json()["province"]


def test_inspectors_metadata() -> None:
    resp = client.get("/api/v2/inspectors")
    assert resp.status_code == 200
    codes = {item["code"] for item in resp.json()}
    assert {"kpi.measurement_units", "alarm.stat", "resource.check"} <= codes
    assert all(item["description"] and item["recommendation"] for item in resp.json())


def test_task_preparation_status_is_exposed() -> None:
    """任务列表和详情都返回数据准备摘要，普通规则统计保持不变。"""
    task_id = _upload()
    task = _wait(task_id)
    stats = task["stats"]

    detail = client.get(f"/api/v2/tasks/{task_id}").json()
    assert detail["preparation"] is not None
    preparation = detail["preparation"]
    assert preparation["status"] in ("pass", "warn", "fail", "error")
    assert [item["category"] for item in preparation["items"]] == [
        "main",
        "logs",
        "kpi",
        "traffic",
        "alarm",
        "config",
        "resource",
        "other",
    ]
    main = preparation["items"][0]
    assert main["code"] == "pkg.extract.main"
    assert main["total_count"] >= 1
    assert main["extracted_count"] == main["total_count"]
    assert detail["stats"] == stats

    listing = client.get("/api/v2/tasks", params={"page_size": 100}).json()
    item = next(task for task in listing["items"] if task["task_id"] == task_id)
    assert item["preparation"] is not None
    assert item["stats"] == stats

    assert client.delete(f"/api/v2/tasks/{task_id}").status_code == 204


def test_kpi_rule_supports_summary_and_metric_detail() -> None:
    """KPI 首屏使用摘要；完整趋势与行观察只在指标详情接口返回。"""
    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Session API Statistics\n"))
    task_id = _upload("kpi-lazy-api.zip")
    try:
        _wait(task_id)
        summary = client.get(
            f"/api/v2/tasks/{task_id}/rules/kpi.measurement_units",
            params={"exclude_records": True},
        )
        assert summary.status_code == 200, summary.text
        payload = summary.json()
        assert payload["metrics"] == []
        assert payload["findings"] == []
        units = payload["metadata"]["measurement_units"]
        assert units
        assert all("objects" not in unit for unit in units)
        for unit in units:
            assert unit["metrics"]
            for metric in unit["metrics"]:
                assert "trends" not in metric
                assert "observations" not in metric
                assert len(metric["trend_points"]) <= 30
                assert metric["trend_point_count"] >= len(metric["trend_points"])

        unit = units[0]
        metric = unit["metrics"][0]
        detail = client.get(
            f"/api/v2/tasks/{task_id}/rules/kpi.measurement_units"
            f"/measurement-units/{unit['measurement_unit_id']}"
            f"/metrics/{metric['metric_resource_id']}"
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload["task_id"] == task_id
        assert detail_payload["rule_code"] == "kpi.measurement_units"
        assert detail_payload["measurement_unit_id"] == unit["measurement_unit_id"]
        assert detail_payload["metric"]["metric_resource_id"] == metric["metric_resource_id"]
        assert len(detail_payload["metric"]["trend_points"]) == metric["trend_point_count"]
        assert "observations" in detail_payload["metric"]

        missing = client.get(
            f"/api/v2/tasks/{task_id}/rules/kpi.measurement_units"
            f"/measurement-units/{unit['measurement_unit_id']}/metrics/ME_MISSING"
        )
        assert missing.status_code == 404
        assert missing.json()["code"] == "not_found"
    finally:
        client.delete(f"/api/v2/tasks/{task_id}")
