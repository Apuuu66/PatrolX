"""规则匹配诊断只读取 manifest v5 任务现场的契约测试。"""

import json
from pathlib import Path

import pytest

from app import cli
from tests.baseline_helpers import setup_env
from tests.manifest_helpers import write_catalog_manifest


def _write_file(task_dir: Path, relative: str, content: str) -> None:
    path = task_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_explain_match_reports_manifest_v5_catalog_and_pattern_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-match"
    task_dir = env.task_dir(task_id)
    _write_file(task_dir, "kpi/measurement.csv", "object,value\ncell,1\n")
    manifest = write_catalog_manifest(task_dir, ["kpi/measurement.csv"])

    report = cli.explain_match(
        "kpi.measurement_units",
        task_id=task_id,
        product="UMF",
    )

    assert report["task_id"] == task_id
    assert report["package_file"] is None
    assert "enabled" not in report["rule"]
    assert report["source_patterns"]
    assert report["manifest"]["version"] == 5
    assert report["manifest"]["classification"] == manifest["classification"]
    assert report["manifest"]["summary"] == manifest["summary"]
    assert report["catalog_paths"] == ["kpi/measurement.csv"]
    assert report["matched_files"] == ["kpi/measurement.csv"]
    kpi_pattern = next(pattern for pattern in report["source_patterns"] if pattern.startswith("^kpi/"))
    assert report["pattern_matches"][kpi_pattern] == ["kpi/measurement.csv"]
    assert all(matches == [] for pattern, matches in report["pattern_matches"].items() if pattern != kpi_pattern)


def test_explain_match_returns_audit_and_does_not_scan_legacy_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-v5"
    task_dir = env.task_dir(task_id)
    _write_file(task_dir, "kpi/measurement.csv", "object,value\ncell,1\n")
    _write_file(task_dir, "logs/legacy.log", "must not enter catalog\n")
    ignored = {
        "source_relative": "ignored.txt",
        "member_relative": None,
        "route_id": "umf.ignore",
        "product": "UMF",
        "category": None,
        "original_target": None,
        "target": None,
        "action": "ignore",
        "status": "ignored",
        "reason": "route_ignored",
        "error_code": None,
    }
    failure = {
        "source_relative": "broken.zip",
        "member_relative": None,
        "route_id": "umf.expand",
        "category": None,
        "action": "expand",
        "error_code": "archive_corrupt",
        "reason": "归档损坏",
    }
    manifest = write_catalog_manifest(
        task_dir,
        ["kpi/measurement.csv"],
        ignored=[ignored],
        failures=[failure],
    )

    report = cli.explain_match("kpi.measurement_units", task_id=task_id)

    assert report["manifest"]["classification"]["snapshot"] == manifest["classification"]["snapshot"]
    assert (
        report["manifest"]["classification"]["config_fingerprint"] == manifest["classification"]["config_fingerprint"]
    )
    assert report["manifest"]["route_counts"] == manifest["summary"]["by_route"]
    assert report["manifest"]["category_counts"] == manifest["summary"]["by_category"]
    assert report["manifest"]["action_counts"] == manifest["summary"]["by_action"]
    assert report["manifest"]["status_counts"] == manifest["summary"]["by_status"]
    assert report["manifest"]["ignored"] == [ignored]
    assert report["manifest"]["failures"] == [failure]
    assert report["catalog_paths"] == ["kpi/measurement.csv"]
    assert report["matched_files"] == ["kpi/measurement.csv"]
    assert "logs/legacy.log" not in report["catalog_paths"]


def test_explain_match_blocks_corrupt_manifest_without_requiring_original_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-corrupt-manifest"
    task_dir = env.task_dir(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "manifest.json").write_bytes(b"\xff")

    with pytest.raises(ValueError) as caught:
        cli.explain_match("kpi.measurement_units", task_id=task_id)

    error = caught.value
    assert getattr(error, "code", None) == "classification_error"
    detail = getattr(error, "detail", {})
    assert detail["failed_units"] == ["pkg.extract.classification"]
    classification = detail["classification"]
    assert classification["code"] == "pkg.extract.classification"
    assert classification["status"] == "error"
    assert "分类清单无法读取或解析" in classification["summary"]
    assert "manifest v5" in classification["metadata"]["error"]


def test_explain_match_blocks_catalog_build_failure_with_structured_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-catalog-failure"
    task_dir = env.task_dir(task_id)
    _write_file(task_dir, "kpi/measurement.csv", "object,value\ncell,1\n")
    write_catalog_manifest(task_dir, ["kpi/measurement.csv"])
    (task_dir / "kpi/measurement.csv").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        cli.explain_match("kpi.measurement_units", task_id=task_id)

    error = caught.value
    assert getattr(error, "code", None) == "classification_error"
    detail = getattr(error, "detail", {})
    assert detail["failed_units"] == ["pkg.extract.classification"]
    assert "catalog 构建失败" in detail["classification"]["summary"]
    assert "摘要或大小不一致" in detail["classification"]["metadata"]["error"]


def test_explain_match_cli_uses_existing_task_site_without_package_search(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-cli-v5"
    task_dir = env.task_dir(task_id)
    _write_file(task_dir, "kpi/measurement.csv", "object,value\ncell,1\n")
    write_catalog_manifest(task_dir, ["kpi/measurement.csv"])
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [])

    result = cli.main(["explain-match", "--rule", "kpi.measurement_units", "--task-id", task_id])

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["task_id"] == task_id
    assert report["catalog_paths"] == ["kpi/measurement.csv"]


def test_explain_match_cli_prints_stable_classification_error_without_package(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-cli-error"
    task_dir = env.task_dir(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "manifest.json").write_bytes(b"\xff")
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [])

    result = cli.main(["explain-match", "--rule", "kpi.measurement_units", "--task-id", task_id])

    output = capsys.readouterr().out
    assert result == 1
    assert "classification_error" in output
    assert "pkg.extract.classification" in output
    assert "分类清单无法读取或解析" in output
