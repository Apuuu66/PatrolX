"""KPI 资源 CSV 基础配置导入边界测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.db import init_db
from tests.kpi_helpers import KPI_BASE_FILES, configure_kpi_catalog, kpi_catalog_payload, write_kpi_split_config
from tools import kpi_catalog
from tools.kpi_catalog import (
    DEFAULT_DATA_DIR,
    DEFAULT_RESOURCE_DIR,
    PROJECT_ROOT,
    KpiCatalogGeneratorError,
    generate_kpi_catalog,
    main,
)


def _csv(rows: list[tuple[str, str, str]] | None = None) -> bytes:
    if rows is None:
        rows = [(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]]
        rows.append(("UNIT_SEC", "秒", "second"))
    return ("资源id,中文描述,英文描述\n" + "".join(f"{a},{b},{c}\n" for a, b, c in rows)).encode()


def _base_hashes(data_dir: Path) -> dict[str, bytes]:
    return {relative: (data_dir / relative).read_bytes() for relative in KPI_BASE_FILES}


def test_import_writes_only_base_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "kpi.db")
    init_db()
    data_dir = write_kpi_split_config(tmp_path)
    before = _base_hashes(data_dir)
    csv_path = tmp_path / "resource.csv"
    rows = [(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]]
    rows.append(("ME_NEW", "新指标", "New Metric"))
    rows.append(("UNIT_SEC", "秒", "second"))
    csv_path.write_bytes(_csv(rows))
    generate_kpi_catalog(csv_path, data_dir)
    assert _base_hashes(data_dir) != before
    assert not (data_dir / "rules").exists()

    metrics = json.loads((data_dir / "base/metrics.json").read_text(encoding="utf-8"))
    units = json.loads((data_dir / "base/units.json").read_text(encoding="utf-8"))
    assert "ME_NEW" in {item["resource_id"] for item in metrics["metrics"]}
    assert [item["resource_id"] for item in units["units"]] == ["UNIT_SEC"]
    assert metrics["metrics"][0]["unit_key"] is None
    assert metrics["source_csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_removed_referenced_metric_is_rejected_without_changes(tmp_path: Path, monkeypatch) -> None:
    configure_kpi_catalog(tmp_path, monkeypatch)
    data_dir = settings.kpi_data
    before = _base_hashes(data_dir)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv([]))
    with pytest.raises(
        KpiCatalogGeneratorError,
        match="SQLite 动态配置仍引用基础指标: me_call_attempts",
    ):
        generate_kpi_catalog(csv_path, data_dir)
    assert _base_hashes(data_dir) == before


def test_non_matching_row_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "kpi.db")
    init_db()
    data_dir = write_kpi_split_config(tmp_path)
    before = _base_hashes(data_dir)
    csv_path = tmp_path / "resource.csv"
    csv_path.write_bytes(_csv([("ME_BAD!", "坏名称", "Bad")]))
    generate_kpi_catalog(csv_path, data_dir)
    metrics = json.loads((data_dir / "base/metrics.json").read_text(encoding="utf-8"))
    assert metrics["metrics"] == []
    assert _base_hashes(data_dir) != before


def test_default_paths_are_fixed() -> None:
    assert DEFAULT_RESOURCE_DIR == PROJECT_ROOT / "local_run/resource_metrics"
    assert DEFAULT_DATA_DIR == PROJECT_ROOT / "deploy/data/kpi"


def test_cli_without_arguments_uses_fixed_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """零参调用只校验默认路径装配，不触碰仓库默认数据。"""
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        kpi_catalog,
        "generate_kpi_catalog",
        lambda csv, data_dir: calls.append((csv, data_dir)),
    )

    assert main([]) == 0
    assert calls == [(DEFAULT_RESOURCE_DIR, DEFAULT_DATA_DIR)]


def test_cli_with_explicit_resource_dir_updates_base_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真实执行统一通过显式输入目录和输出目录指向临时路径。"""
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "kpi.db")
    init_db()
    resource_dir = tmp_path / "resource_metrics"
    resource_dir.mkdir()
    csv_path = resource_dir / "any-name.csv"
    data_dir = write_kpi_split_config(tmp_path / "kpi")
    csv_path.write_bytes(
        _csv([(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]])
    )

    assert main(["generate", "--input", str(resource_dir), "--data-dir", str(data_dir)]) == 0

    metrics = json.loads((data_dir / "base/metrics.json").read_text(encoding="utf-8"))
    assert metrics["source_csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_cli_rejects_clear_rules_option(tmp_path: Path) -> None:
    resource_dir = tmp_path / "resource_metrics"
    resource_dir.mkdir()
    (resource_dir / "resource.csv").write_bytes(_csv())
    with pytest.raises(SystemExit) as exc_info:
        main(["generate", "--input", str(resource_dir), "--data-dir", str(tmp_path / "kpi"), "--clear-rules"])
    assert exc_info.value.code == 2
