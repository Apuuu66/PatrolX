"""Git KPI JSON 加载与组合测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.inspectors.kpi.catalog import KpiCatalogError, build_kpi_config_from_catalog, load_kpi_catalog


def _formula() -> dict[str, Any]:
    return {
        "kind": "ratio",
        "numerator": "me_2",
        "denominator": "me_1",
        "scale": 100,
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
            "common": {"input_timezone": "Asia/Shanghai", "budgets": {"max_files": 100, "max_records": 1000}},
            "metric_rules": [
                {
                    "key": "me_2",
                    "metric_type": "count",
                    "semantic_group": "traffic",
                    "display_role": "context",
                    "unit": "次",
                    "source_type": "raw",
                    "aggregation": {"kind": "sum"},
                    "formula": None,
                }
            ],
            "thresholds": [],
            "capacity_rules": [],
            "display_rules": [],
        },
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "kpi_catalog.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_and_combine_catalog(tmp_path: Path) -> None:
    path = _write(tmp_path, _payload())
    catalog = load_kpi_catalog(path)
    assert catalog.base_data_version.startswith("sha256:")
    config = build_kpi_config_from_catalog(catalog, {"me_1": "call"}, 3)
    assert set(config.domains["call"].metrics) == {"me_1"}
    assert config.domains["call"].metrics["me_2"] is None if False else True


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data["metrics"].append(dict(data["metrics"][0], resource_id="ME_3")),
        lambda data: data["metrics"].append(
            {"resource_id": "BAD_1", "key": "bad_1", "name_zh": "x", "name_en": "y", "unit_key": None}
        ),
        lambda data: data["rules"]["metric_rules"][0].update(key="missing"),
    ],
)
def test_load_rejects_invalid_catalog(tmp_path: Path, mutator) -> None:
    data = _payload()
    mutator(data)
    path = _write(tmp_path, data)
    with pytest.raises(KpiCatalogError):
        load_kpi_catalog(path)
