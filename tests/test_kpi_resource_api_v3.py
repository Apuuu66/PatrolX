"""KPI 指标库 API v3 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.db import init_db

client = TestClient(app)


@pytest.fixture()
def v3_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    payload = {
        "schema_version": 1,
        "source_csv_sha256": "a" * 64,
        "metrics": [
            {
                "resource_id": "ME_1",
                "key": "me_1",
                "name_zh": "呼叫请求次数",
                "name_en": "Call Attempts",
                "unit_key": None,
            },
            {
                "resource_id": "ME_2",
                "key": "me_2",
                "name_zh": "呼叫请求成功次数",
                "name_en": "Call Success Count",
                "unit_key": None,
            },
        ],
        "units": [{"resource_id": "UNIT_1", "key": "unit_1", "name_zh": "次", "name_en": "times"}],
        "rules": {
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 10, "max_records": 20}},
            "metric_rules": [],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        },
    }
    path = tmp_path / "kpi_catalog.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "kpi_catalog_path", path)
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "db.sqlite")
    init_db()
    return path


def test_v3_list_classify_and_retire_v2(v3_env: Path) -> None:
    page = client.get("/api/v3/kpi/resource-metrics", params={"page_size": 1})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["summary"] == {"unclassified": 2, "call": 0, "api": 0, "media": 0}
    result = client.put(
        "/api/v3/kpi/resource-metrics/classification",
        json={"metric_keys": ["me_1"], "domain": "call", "operator": "alice"},
    )
    assert result.status_code == 200
    assert result.json()["classification_version"] == 1
    page = client.get("/api/v3/kpi/resource-metrics").json()
    assert page["items"][0]["domain"] == "call"
    assert client.get("/api/v2/kpi/resource-metrics").status_code == 404
    assert client.post("/api/v2/kpi/resource-metrics").status_code == 404
    assert client.put("/api/v2/kpi/resource-metrics/classification").status_code == 404
