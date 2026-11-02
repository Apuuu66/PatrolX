"""规则匹配诊断命令测试。"""

import json
from pathlib import Path

import pytest

from app import cli
from app.services import extraction
from app.services.executor import RuleContext
from tests.baseline_helpers import SAMPLE, setup_env


def test_explain_match_reports_catalog_pattern_and_extraction_state(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.cli import explain_match

    report = explain_match("kpi.measurement_units", package=SAMPLE, task_id="task-explain-match")

    assert report["task_id"] == "task-explain-match"
    assert report["package_file"] == SAMPLE.name
    assert report["rule"]["enabled"] is True
    assert report["source_patterns"]
    assert any(path.startswith("kpi/") for path in report["catalog_paths"])
    assert report["matched_files"]
    assert any(report["pattern_matches"].get(pattern) for pattern in report["source_patterns"])
    assert any(path.startswith("kpi/") for path in report["matched_files"])
    assert report["manifest"]["main"]["count"] > 0


def _manifest() -> dict:
    return {
        "version": 4,
        "main": {"checksum": "a" * 64, "count": 1, "evidence_path": ".main", "reused": False},
        "files": [
            {
                "source": ".main/KPI/kpi.csv",
                "category": "kpi",
                "target": "kpi/kpi.csv",
                "depth": 1,
                "status": "extracted",
            }
        ],
        "subpackages": [],
        "log_gz": [],
        "rejected": [],
    }


def test_explain_match_blocks_corrupt_manifest_with_structured_classification_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """manifest 损坏时 classification 门禁必须先失败，不能继续返回匹配结果。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-corrupt-manifest"
    task_dir = env.task_dir(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / extraction.MANIFEST_NAME).write_bytes(b"\xff")

    with pytest.raises(ValueError) as caught:
        cli.explain_match("kpi.measurement_units", package=tmp_path / "missing.zip", task_id=task_id)

    error = caught.value
    assert getattr(error, "code", None) == "classification_error"
    detail = getattr(error, "detail", {})
    assert detail["failed_units"] == ["pkg.extract.classification"]
    assert "分类清单无法读取或解析" in detail["classification"]["summary"]
    assert "utf-8" in detail["classification"]["metadata"]["error"].lower()


def test_explain_match_blocks_catalog_build_failure_with_structured_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """catalog 构建失败必须保留 classification 失败原因并阻断诊断输出。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-explain-catalog-failure"
    task_dir = env.task_dir(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / extraction.MANIFEST_NAME).write_text(json.dumps(_manifest()), encoding="utf-8")

    def fail_catalog(_ctx: RuleContext):
        raise ValueError("catalog 注入失败")

    monkeypatch.setattr(RuleContext, "ensure_catalog", fail_catalog)

    with pytest.raises(ValueError) as caught:
        cli.explain_match("kpi.measurement_units", package=tmp_path / "missing.zip", task_id=task_id)

    error = caught.value
    assert getattr(error, "code", None) == "classification_error"
    detail = getattr(error, "detail", {})
    assert detail["failed_units"] == ["pkg.extract.classification"]
    assert "catalog 构建失败" in detail["classification"]["summary"]
    assert detail["classification"]["metadata"]["error"] == "catalog 注入失败"


def test_explain_match_cli_prints_stable_dependency_error(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI 遇到分类门禁失败时返回非零并给出稳定错误码与结构化详情。"""
    env = setup_env(tmp_path, monkeypatch)
    package = tmp_path / "missing.zip"
    task_id = "task-explain-cli-error"
    task_dir = env.task_dir(task_id)
    task_dir.mkdir(parents=True)
    (task_dir / extraction.MANIFEST_NAME).write_bytes(b"\xff")
    monkeypatch.setattr(cli, "find_packages", lambda root=None: [package])

    result = cli.main(
        [
            "explain-match",
            "--rule",
            "kpi.measurement_units",
            "--task-id",
            task_id,
            "--product",
            "CSP",
        ]
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "classification_error" in output
    assert "pkg.extract.classification" in output
    assert "分类清单无法读取或解析" in output
