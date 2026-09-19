"""KPI 拆分配置契约、目录加载与内容指纹测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import Settings, settings
from app.inspectors.kpi.catalog import KpiCatalogError, load_kpi_catalog
from tests.kpi_helpers import KPI_SPLIT_FILES, kpi_catalog_payload, write_kpi_split_config


def test_settings_use_fixed_kpi_split_paths() -> None:
    assert settings.kpi_data_dir == Path("deploy/data/kpi")
    assert settings.kpi_metrics_file == settings.base_dir / "deploy/data/kpi/base/metrics.json"
    assert settings.kpi_units_file == settings.base_dir / "deploy/data/kpi/base/units.json"
    assert settings.kpi_rule_file("common") == settings.base_dir / "deploy/data/kpi/rules/common.json"
    assert settings.kpi_rule_file("display") == settings.base_dir / "deploy/data/kpi/rules/display-rules.json"


def test_settings_env_override_keeps_split_layout() -> None:
    configured = Settings(kpi_data_dir="/tmp/kpi-data")
    assert configured.kpi_metrics_file == Path("/tmp/kpi-data/base/metrics.json")
    assert configured.kpi_rule_file("metric") == Path("/tmp/kpi-data/rules/metric-rules.json")


def test_load_valid_split_catalog(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    catalog = load_kpi_catalog(data_dir)
    assert len(catalog.metrics) == 7
    assert catalog.units == {}
    assert set(catalog.rules.metric_rules) == {item["key"] for item in kpi_catalog_payload()["rules"]["metric_rules"]}
    assert catalog.base_data_version.startswith("sha256:")


@pytest.mark.parametrize("relative", KPI_SPLIT_FILES)
def test_missing_file_fails(tmp_path: Path, relative: str) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    (data_dir / relative).unlink()
    with pytest.raises(KpiCatalogError, match=relative):
        load_kpi_catalog(data_dir)


def test_invalid_json_and_duplicate_fields_fail(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    (data_dir / "base/units.json").write_text('{"schema_version":1,"units":[],"units":[]}', encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="重复"):
        load_kpi_catalog(data_dir)

    data_dir = write_kpi_split_config(tmp_path)
    (data_dir / "rules/common.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="rules/common.json"):
        load_kpi_catalog(data_dir)


def test_unknown_fields_and_schema_fail(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    metrics_path = data_dir / "base/metrics.json"
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    data["unexpected"] = True
    metrics_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="base/metrics.json"):
        load_kpi_catalog(data_dir)

    data_dir = write_kpi_split_config(tmp_path)
    path = data_dir / "rules/thresholds.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="schema_version"):
        load_kpi_catalog(data_dir)


def test_cross_file_references_and_cycles_fail(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    path = data_dir / "rules/thresholds.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["thresholds"][0]["metric_key"] = "missing"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="missing"):
        load_kpi_catalog(data_dir)

    data_dir = write_kpi_split_config(tmp_path)
    path = data_dir / "rules/metric-rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for rule in data["metric_rules"]:
        if rule.get("formula"):
            rule["formula"] = {
                "kind": "ratio",
                "numerator": rule["key"],
                "denominator": rule["key"],
                "scale": 100,
            }
            rule["source_type"] = "derived"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match="循环"):
        load_kpi_catalog(data_dir)


def test_base_data_version_is_fixed_order_content_fingerprint(tmp_path: Path) -> None:
    first = write_kpi_split_config(tmp_path / "first")
    catalog = load_kpi_catalog(first)
    combined = b"".join(
        relative.encode("utf-8") + b"\x00" + (first / relative).read_bytes() + b"\x00" for relative in KPI_SPLIT_FILES
    )
    assert catalog.base_data_version == "sha256:" + hashlib.sha256(combined).hexdigest()

    second = write_kpi_split_config(tmp_path / "second")
    common_path = second / "rules/common.json"
    common_path.write_text(common_path.read_text(encoding="utf-8").rstrip() + "  \n", encoding="utf-8")
    changed = load_kpi_catalog(second)
    assert changed.base_data_version != catalog.base_data_version


def test_error_locations_for_cross_file_rules(tmp_path: Path) -> None:
    data_dir = write_kpi_split_config(tmp_path)
    path = data_dir / "base/metrics.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    duplicate = {"resource_id": "ME_DUP", "key": "me_dup", "name_zh": "x", "name_en": "y", "unit_key": None}
    data["metrics"].append(duplicate)
    data["metrics"].append({**duplicate, "resource_id": "ME_DUP2"})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match=r"base/metrics\.json.*metrics\[\d+\]"):
        load_kpi_catalog(data_dir)

    data_dir = write_kpi_split_config(tmp_path)
    path = data_dir / "rules/thresholds.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["thresholds"][1]["metric_key"] = "missing"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(KpiCatalogError, match=r"thresholds\[1\]\.metric_key"):
        load_kpi_catalog(data_dir)


def test_reserved_unit_does_not_change_rules(tmp_path: Path) -> None:
    payload = kpi_catalog_payload()
    payload["units"] = [{"resource_id": "UNIT_SEC", "key": "unit_sec", "name_zh": "秒", "name_en": "second"}]
    catalog = load_kpi_catalog(write_kpi_split_config(tmp_path, payload))
    assert catalog.units["unit_sec"].resource_id == "UNIT_SEC"
    assert catalog.rules.thresholds == kpi_catalog_payload()["rules"]["thresholds"]

    payload["metrics"][0]["unit_key"] = "unit_sec"
    with pytest.raises(KpiCatalogError, match="unit_key"):
        load_kpi_catalog(write_kpi_split_config(tmp_path / "invalid", payload))
