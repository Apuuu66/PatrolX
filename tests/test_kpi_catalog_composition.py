"""KPI 基础资源加载与领域组合测试。"""

from __future__ import annotations

from pathlib import Path

from app.inspectors.kpi.catalog import build_kpi_config_from_catalog, load_kpi_catalog
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_split_config


def test_load_and_combine_base_catalog(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    catalog = load_kpi_catalog(data_dir)
    assert catalog.base_data_version.startswith("sha256:")
    config = build_kpi_config_from_catalog(catalog, {"me_call_attempts": "call"}, 3)
    assert set(config.domains["call"].metrics) == {"me_call_attempts"}


def test_unclassified_metric_is_not_combined(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    catalog = load_kpi_catalog(data_dir)
    config = build_kpi_config_from_catalog(catalog, {}, 1)
    assert all(not domain.metrics for domain in config.domains.values())
    assert set(catalog.metrics) == {item["key"] for item in kpi_catalog_payload()["metrics"]}
