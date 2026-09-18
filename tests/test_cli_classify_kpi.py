"""CLI KPI 分类命令测试。"""

from pathlib import Path

from sqlalchemy import select

from app.cli import main
from app.models.db import KpiClassification, session_factory
from tests.kpi_helpers import kpi_catalog_payload, write_kpi_catalog


def test_cli_classifies_single_kpi_metric(tmp_path: Path, monkeypatch, capsys) -> None:
    payload = kpi_catalog_payload()
    payload["metrics"] = [
        {
            "resource_id": "ME_CLI_METRIC",
            "key": "me_cli_metric",
            "name_zh": "CLI 指标",
            "name_en": "CLI Metric",
            "unit_key": None,
        }
    ]
    payload["rules"]["metric_rules"] = []
    payload["rules"]["thresholds"] = []
    payload["rules"]["capacity_rules"] = []
    write_kpi_catalog(tmp_path, monkeypatch, payload)

    main(["classify-kpi", "--metric-key", "me_cli_metric", "--domain", "api"])

    with session_factory() as session:
        record = session.scalar(select(KpiClassification).where(KpiClassification.metric_key == "me_cli_metric"))
        assert record is not None
        assert record.domain == "api"

    assert "me_cli_metric" in capsys.readouterr().out
