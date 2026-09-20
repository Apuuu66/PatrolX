"""KPI 指标库 API v3 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.db import init_db
from tests.kpi_helpers import write_kpi_split_config

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
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "db.sqlite")
    init_db()
    return data_dir


def test_v3_list_classify_and_retire_v2(v3_env: Path) -> None:
    page = client.get("/api/v3/kpi/resource-metrics", params={"page_size": 1})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["summary"] == {"unclassified": 2, "call": 0, "api": 0, "media": 0, "reserved": 0}
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


def test_kpi_resource_has_no_runtime_csv_import(v3_env: Path) -> None:
    openapi = json.loads(Path("docs/api/openapi.yaml").read_text(encoding="utf-8")) if False else None
    # YAML 依赖不引入：用文本检查足够验证路径集合没有导入端点。
    text = Path("docs/api/openapi.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("  /api/v3/kpi/"):
            assert "import" not in line and "upload" not in line and "csv" not in line.lower()
    assert openapi is None
    web_text = "\n".join(path.read_text(encoding="utf-8") for path in Path("web/src").rglob("*.tsx"))
    assert "resource-metrics/csv" not in web_text
    assert "resource-metrics/import" not in web_text
