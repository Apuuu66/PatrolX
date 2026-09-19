"""KPI 资源 CSV 离线生成器测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.kpi_helpers import KPI_SPLIT_FILES, kpi_catalog_payload, write_kpi_split_config
from tools.kpi_catalog import KpiCatalogGeneratorError, generate_kpi_catalog


def _csv(
    rows: list[tuple[str, str, str]] | None = None,
    header: str = "资源id,中文描述,英文描述\n",
) -> bytes:
    if rows is None:
        rows = [(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]]
        rows.append(("UNIT_1", "次", "times"))
    return (header + "".join(f"{a},{b},{c}\n" for a, b, c in rows)).encode()


def test_generator_is_deterministic_and_parses_units(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv())
    generate_kpi_catalog(csv_path, data_dir)
    first = (data_dir / "base/metrics.json").read_bytes()
    generate_kpi_catalog(csv_path, data_dir)
    assert first == (data_dir / "base/metrics.json").read_bytes()
    data = json.loads(first)
    assert [item["key"] for item in data["metrics"]] == sorted(item["key"] for item in data["metrics"])
    assert all(item["unit_key"] is None for item in data["metrics"])
    units = json.loads((data_dir / "base/units.json").read_text(encoding="utf-8"))
    assert units["units"] == [{"resource_id": "UNIT_1", "key": "unit_1", "name_zh": "次", "name_en": "times"}]
    assert data["source_csv_sha256"] == hashlib.sha256(_csv()).hexdigest()


@pytest.mark.parametrize(
    ("rows", "header", "match"),
    [
        ([], "resource,description\n", "表头"),
        ([("BAD_1", "中", "en")], None, "BAD_1"),
        ([("ME_1", "", "en")], None, "ME_1"),
        ([("ME_1", "中", "en"), ("ME_1", "中", "en")], None, "重复"),
        ([("NEW_1", "中", "en")], None, "NEW_1"),
    ],
)
def test_generator_rejects_invalid_input_without_output(
    tmp_path: Path,
    rows: list[tuple[str, str, str]],
    header: str | None,
    match: str,
) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv(rows, header or "资源id,中文描述,英文描述\n"))
    with pytest.raises(KpiCatalogGeneratorError, match=match):
        generate_kpi_catalog(csv_path, data_dir)
    assert (data_dir / "base/metrics.json").read_text(encoding="utf-8").startswith('{\n  "schema_version"')


def test_generator_preserves_rule_file_bytes(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    before = {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES[2:]}
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv())
    generate_kpi_catalog(csv_path, data_dir)
    assert {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES[2:]} == before
