"""KPI 分类数据库服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import init_db
from app.services.kpi_resources import classify_resource_metrics, list_classification_audits


@pytest.fixture()
def initialized_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "test.db")
    init_db()
    return tmp_path


def test_classification_is_atomic_and_audited(initialized_db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        "units": [],
        "rules": {
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 10, "max_records": 20}},
            "metric_rules": [],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        },
    }
    catalog_path = tmp_path / "kpi_catalog.json"
    catalog_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings, "kpi_catalog_path", catalog_path)
    result = classify_resource_metrics(["me_1", "me_2"], domain="call", operator="alice")
    assert result["classification_version"] == 1
    assert result["audited_count"] == 2
    audits = list_classification_audits(page_size=10)
    assert audits.total == 2
    assert {item.operator for item in audits.items} == {"alice"}
    assert all(item.from_domain == "unclassified" and item.to_domain == "call" for item in audits.items)
