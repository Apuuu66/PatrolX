"""KPI 分类数据库服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import init_db
from app.services.kpi_resources import (
    KpiResourceError,
    classify_resource_metrics,
    list_classification_audits,
    list_resource_metrics,
)
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_split_config


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
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    result = classify_resource_metrics(["me_1", "me_2"], domain="call", operator="alice")
    assert result["classification_version"] == 1
    assert result["audited_count"] == 2
    audits = list_classification_audits(page_size=10)
    assert audits.total == 2
    assert {item.operator for item in audits.items} == {"alice"}
    assert all(item.from_domain == "unclassified" and item.to_domain == "call" for item in audits.items)


def test_reimport_same_key_preserves_classification_and_audits(
    initialized_db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools.kpi_catalog import generate_kpi_catalog

    payload = kpi_catalog_payload()
    payload["metrics"] = [
        {"resource_id": "ME_REIMPORT", "key": "me_reimport", "name_zh": "旧名称", "name_en": "Old", "unit_key": None}
    ]
    payload["rules"]["metric_rules"] = []
    payload["rules"]["thresholds"] = []
    payload["rules"]["capacity_rules"] = []
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    classify_resource_metrics(["me_reimport"], domain="call", operator="alice")

    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes("资源id,中文描述,英文描述\nME_REIMPORT,新名称,New\n".encode())
    generate_kpi_catalog(csv_path, data_dir)
    page = list_resource_metrics(page_size=10)
    assert page.items[0].name_zh == "新名称"
    assert page.items[0].domain == "call"
    assert page.classification_version == 1
    audits = list_classification_audits(page_size=10)
    assert audits.total == 1


def test_invalid_domain_does_not_change_state(initialized_db) -> None:
    with pytest.raises(KpiResourceError) as exc_info:
        classify_resource_metrics(["me_1"], domain="network", operator="alice")
    assert exc_info.value.code == "invalid_domain"
    assert list_classification_audits(page_size=10).total == 0


def test_failed_classification_does_not_save_partial_records(
    initialized_db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = kpi_catalog_payload()
    payload["rules"]["metric_rules"] = []
    payload["rules"]["thresholds"] = []
    payload["rules"]["capacity_rules"] = []
    data_dir = tmp_path / "kpi"
    write_kpi_split_config(data_dir, payload)
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    with pytest.raises(KpiResourceError) as exc_info:
        classify_resource_metrics(["me_1", "missing"], domain="call", operator="alice")
    assert exc_info.value.code == "metric_not_found"
    page = list_resource_metrics(include_missing=True, page_size=10)
    assert all(item.domain == "unclassified" for item in page.items)
    assert list_classification_audits(page_size=10).total == 0
