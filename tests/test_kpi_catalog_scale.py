"""KPI 资源全集规模回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.inspectors.kpi.catalog import load_kpi_catalog
from app.models.db import init_db
from app.services.kpi_resources import list_resource_metrics
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_split_config
from tools.kpi_catalog import generate_kpi_catalog


def test_generator_catalog_and_pagination_support_1000_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = "".join(f"ME_{number:04d},指标 {number},Metric {number}\n" for number in range(1000)).encode()
    csv_path = tmp_path / "resource.csv"
    data_dir = tmp_path / "kpi"
    payload = kpi_catalog_payload()
    payload["metrics"] = []
    payload["rules"]["metric_rules"] = []
    payload["rules"]["thresholds"] = []
    payload["rules"]["capacity_rules"] = []
    write_kpi_split_config(data_dir, payload)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes("资源id,中文描述,英文描述\n".encode() + rows)
    generate_kpi_catalog(csv_path, data_dir)

    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "kpi.db")
    monkeypatch.setattr(settings, "kpi_data_dir", data_dir)
    init_db()

    catalog = load_kpi_catalog(settings.kpi_data)
    assert len(catalog.metrics) == 1000

    page = list_resource_metrics(page=2, page_size=100)
    assert page.total == 1000
    assert page.page == 2
    assert len(page.items) == 100
    assert page.summary["unclassified"] == 1000
    assert page.items[0].key == "me_0100"
