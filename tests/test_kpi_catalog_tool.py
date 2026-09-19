"""KPI 资源 CSV 拆分导入边界测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.kpi_helpers import KPI_SPLIT_FILES, kpi_catalog_payload, write_kpi_split_config
from tools import kpi_catalog
from tools.kpi_catalog import (
    DEFAULT_DATA_DIR,
    DEFAULT_RESOURCE_DIR,
    PROJECT_ROOT,
    KpiCatalogGeneratorError,
    generate_kpi_catalog,
    main,
)


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


def test_cli_with_explicit_resource_dir_updates_base_files(tmp_path: Path) -> None:
    """真实执行统一通过显式输入目录和输出目录指向临时路径。"""

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


def test_cli_with_gbk_resource_csv_updates_base_files(tmp_path: Path) -> None:
    """GBK 导出使用 GB18030 回退解析，输出仍保持 UTF-8。"""

    resource_dir = tmp_path / "resource_metrics"
    resource_dir.mkdir()
    csv_path = resource_dir / "gbk.csv"
    data_dir = write_kpi_split_config(tmp_path / "kpi")
    rows = [(item["resource_id"], item["name_zh"], item["name_en"]) for item in kpi_catalog_payload()["metrics"]]
    csv_path.write_bytes(_csv(rows).decode("utf-8").encode("gb18030"))

    assert main(["generate", "--input", str(resource_dir), "--data-dir", str(data_dir)]) == 0

    metrics = json.loads((data_dir / "base/metrics.json").read_text(encoding="utf-8"))
    assert metrics["source_csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert metrics["metrics"][0]["name_zh"] == kpi_catalog_payload()["metrics"][0]["name_zh"]


def test_cli_with_multiple_resource_csvs_reports_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    resource_dir = tmp_path / "resource_metrics"
    resource_dir.mkdir()
    (resource_dir / "first.csv").write_bytes(_csv([]))
    (resource_dir / "second.csv").write_bytes(_csv([]))
    data_dir = write_kpi_split_config(tmp_path / "kpi")
    before = {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES}

    assert main(["generate", "--input", str(resource_dir), "--data-dir", str(data_dir)]) == 2

    output = capsys.readouterr().out
    assert "必须且只能包含一个 CSV" in output
    assert "first.csv" in output
    assert "second.csv" in output
    assert {relative: (data_dir / relative).read_bytes() for relative in KPI_SPLIT_FILES} == before


def test_cli_missing_input_reports_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """缺失输入也通过显式参数测试，避免依赖或修改默认路径。"""

    missing_input = tmp_path / "missing-resource-dir"
    data_dir = write_kpi_split_config(tmp_path / "kpi")

    assert main(["generate", "--input", str(missing_input), "--data-dir", str(data_dir)]) == 2

    output = capsys.readouterr().out
    assert "资源输入不存在" in output
    assert str(missing_input) in output
