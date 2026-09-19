"""KPI 拆分配置加载与组合测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.inspectors.kpi.catalog import KpiCatalogError, build_kpi_config_from_catalog, load_kpi_catalog
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_split_config


def test_load_and_combine_catalog(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    catalog = load_kpi_catalog(data_dir)
    assert catalog.base_data_version.startswith("sha256:")
    config = build_kpi_config_from_catalog(catalog, {"me_call_attempts": "call"}, 3)
    assert set(config.domains["call"].metrics) == {"me_call_attempts"}


def test_load_rejects_invalid_catalog(tmp_path: Path) -> None:
    payload = kpi_catalog_payload()
    payload["metrics"].append(dict(payload["metrics"][0], resource_id="ME_DUP"))
    data_dir = write_kpi_split_config(tmp_path, payload)
    with pytest.raises(KpiCatalogError, match="稳定 key"):
        load_kpi_catalog(data_dir)

    payload = kpi_catalog_payload()
    payload["rules"]["metric_rules"][0]["key"] = "missing"
    data_dir = write_kpi_split_config(tmp_path, payload)
    with pytest.raises(KpiCatalogError, match="missing"):
        load_kpi_catalog(data_dir)
