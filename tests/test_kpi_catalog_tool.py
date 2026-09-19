"""KPI 资源 CSV 拆分导入边界测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.tools.kpi_catalog import KpiCatalogGeneratorError, generate_kpi_catalog
from tests.kpi_helpers import KPI_SPLIT_FILES, kpi_catalog_payload, write_kpi_split_config


def _csv(rows: list[tuple[str, str, str]]) -> bytes:
    return ("资源id,中文描述,英文描述\n" + "".join(f"{a},{b},{c}\n" for a, b, c in rows)).encode()


def _rule_hashes(data_dir: Path) -> dict[str, bytes]:
    return {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES[2:]}


def test_import_writes_only_base_files(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    before = _rule_hashes(data_dir)
    csv_path = tmp_path / "resource.csv"
    rows = [(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]]
    rows.append(("ME_NEW", "新指标", "New Metric"))
    rows.append(("UNIT_SEC", "秒", "second"))
    csv_path.write_bytes(_csv(rows))
    generate_kpi_catalog(csv_path, data_dir)
    assert _rule_hashes(data_dir) == before

    metrics = json.loads((data_dir / "base/metrics.json").read_text(encoding="utf-8"))
    units = json.loads((data_dir / "base/units.json").read_text(encoding="utf-8"))
    assert "ME_NEW" in {item["resource_id"] for item in metrics["metrics"]}
    assert [item["resource_id"] for item in units["units"]] == ["UNIT_SEC"]
    assert metrics["metrics"][0]["unit_key"] is None
    assert metrics["source_csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_removed_referenced_metric_is_rejected_without_changes(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    before = {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES}
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv([]))
    with pytest.raises(KpiCatalogGeneratorError, match="校验失败"):
        generate_kpi_catalog(csv_path, data_dir)
    assert {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES} == before


def test_invalid_input_keeps_all_files_unchanged(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    before = {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES}
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv([("ME_BAD!", "坏名称", "Bad")]))
    with pytest.raises(KpiCatalogGeneratorError, match="ME_BAD!"):
        generate_kpi_catalog(csv_path, data_dir)
    assert {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES} == before
