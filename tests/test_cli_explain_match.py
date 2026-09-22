"""规则匹配诊断命令测试。"""

from tests.baseline_helpers import SAMPLE, setup_env


def test_explain_match_reports_catalog_pattern_and_extraction_state(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.cli import explain_match

    report = explain_match("log.umf_acc", package=SAMPLE, task_id="task-explain-match")

    assert report["task_id"] == "task-explain-match"
    assert report["package_file"] == SAMPLE.name
    assert report["rule"]["enabled"] is True
    assert report["source_patterns"]
    assert any(path.startswith("logs/") for path in report["catalog_paths"])
    assert report["matched_files"]
    assert report["manifest"]["main"]["count"] > 0
    assert all(
        report["pattern_matches"][pattern]
        for pattern in report["source_patterns"]
        if pattern in report["pattern_matches"]
    )
