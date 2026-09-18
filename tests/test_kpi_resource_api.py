"""KPI 资源指标在线 API 测试。"""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def _config_dir(tmp_path: Path, monkeypatch) -> Path:
    config_dir = tmp_path / "config" / "kpi"
    shutil.copytree(Path("deploy/config/kpi"), config_dir)
    monkeypatch.setattr(settings, "config_dir", config_dir.parent)
    return config_dir


def _csv_bytes() -> bytes:
    return (
        "资源id,中文描述,英文描述\n"
        "UNIT_1,次,times\n"
        "ME_21002,创建媒体资源请求次数(次),Create Media Resource Request Count\n"
        "ME_21003,媒体成功率,对应英文\n"
    ).encode()


def test_resource_metrics_list_and_import(tmp_path: Path, monkeypatch) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)
    response = client.post(
        "/api/v2/kpi/resource-metrics",
        files={"resource_csv": ("resource.csv", BytesIO(_csv_bytes()), "text/csv")},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["summary"]["new_metrics"] == 2
    assert report["summary"]["skipped_units"] == 1
    assert report["revision"] == 1

    page = client.get("/api/v2/kpi/resource-metrics", params={"search": "21002"}).json()
    assert page["total"] == 1
    assert page["items"][0]["key"] == "me_21002"
    assert page["items"][0]["domain"] == "unclassified"
    assert page["summary"] == {"unclassified": 2, "call": 0, "api": 0, "media": 0}
    assert (config_dir / "resource_metrics.yaml").exists()


def test_resource_metrics_import_rejects_bad_csv(tmp_path: Path, monkeypatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    response = client.post(
        "/api/v2/kpi/resource-metrics",
        files={"resource_csv": ("resource.csv", BytesIO(b"resource,description\n"), "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_resource_csv"


def test_resource_metrics_classification(tmp_path: Path, monkeypatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    client.post(
        "/api/v2/kpi/resource-metrics",
        files={"resource_csv": ("resource.csv", BytesIO(_csv_bytes()), "text/csv")},
    )

    response = client.put(
        "/api/v2/kpi/resource-metrics/classification",
        json={"metric_keys": ["me_21002", "me_21003"], "domain": "media", "expected_revision": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2

    page = client.get("/api/v2/kpi/resource-metrics", params={"domain": "media"}).json()
    assert page["total"] == 2
    assert {item["key"] for item in page["items"]} == {"me_21002", "me_21003"}

    conflict = client.put(
        "/api/v2/kpi/resource-metrics/classification",
        json={"metric_keys": ["me_21002"], "domain": "api", "expected_revision": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "resource_revision_conflict"


def test_resource_metrics_classification_reports_missing_metric(tmp_path: Path, monkeypatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    client.post(
        "/api/v2/kpi/resource-metrics",
        files={"resource_csv": ("resource.csv", BytesIO(_csv_bytes()), "text/csv")},
    )
    response = client.put(
        "/api/v2/kpi/resource-metrics/classification",
        json={"metric_keys": ["missing"], "domain": "media", "expected_revision": 1},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_metric_not_found"
