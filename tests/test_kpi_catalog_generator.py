"""KPI 资源 CSV 离线生成器测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.tools.kpi_catalog import KpiCatalogGeneratorError, generate_kpi_catalog


def _csv(
    rows: list[tuple[str, str, str]] | None = None,
    header: str = "资源id,中文描述,英文描述\n",
) -> bytes:
    if rows is None:
        rows = [
            ("ME_2", "媒体成功率", "Media Success Rate"),
            ("ME_1", "呼叫请求次数", "Call Attempts"),
            ("UNIT_1", "次", "times"),
        ]
    return (header + "".join(f"{a},{b},{c}\n" for a, b, c in rows)).encode()


def test_generator_is_deterministic_and_parses_units(tmp_path: Path) -> None:
    csv_path = tmp_path / "resource.csv"
    output = tmp_path / "kpi_catalog.json"
    csv_path.write_bytes(_csv())
    generate_kpi_catalog(csv_path, output)
    first = output.read_bytes()
    generate_kpi_catalog(csv_path, output)
    assert first == output.read_bytes()
    data = json.loads(first)
    assert [item["key"] for item in data["metrics"]] == ["me_1", "me_2"]
    assert all(item["unit_key"] is None for item in data["metrics"])
    assert data["units"] == [{"resource_id": "UNIT_1", "key": "unit_1", "name_zh": "次", "name_en": "times"}]
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
    csv_path = tmp_path / "resource.csv"
    output = tmp_path / "kpi_catalog.json"
    csv_path.write_bytes(_csv(rows, header or "资源id,中文描述,英文描述\n"))
    with pytest.raises(KpiCatalogGeneratorError, match=match):
        generate_kpi_catalog(csv_path, output)
    assert not output.exists()


def test_generator_preserves_existing_rules(tmp_path: Path) -> None:
    csv_path = tmp_path / "resource.csv"
    output = tmp_path / "kpi_catalog.json"
    csv_path.write_bytes(_csv())
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_csv_sha256": "0" * 64,
                "metrics": [],
                "units": [],
                "rules": {
                    "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 10, "max_records": 20}},
                    "metric_rules": [],
                    "thresholds": [],
                    "capacity_rules": [],
                    "display_rules": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generate_kpi_catalog(csv_path, output)
    assert json.loads(output.read_text(encoding="utf-8"))["rules"]["common"]["budgets"] == {
        "max_files": 10,
        "max_records": 20,
    }
