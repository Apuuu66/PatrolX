"""local_run 任务调试脚本测试。"""

import json
from pathlib import Path

from app.core.config import settings
from scripts.debug_local import build_report, select_task
from tests.manifest_helpers import write_catalog_manifest


def _write_task(output: Path, task_id: str, *, mode: str, completed_at: str) -> Path:
    task_dir = output / task_id
    task_dir.mkdir(parents=True)
    task = {
        "task_id": task_id,
        "mode": mode,
        "trigger": "cli" if mode == "local" else "api",
        "status": "completed",
        "created_at": "2026-01-01T00:00:00Z",
        "completed_at": completed_at,
        "system": {
            "package_file": f"{task_id}.zip",
            "summary": {"total": 1},
            "rules": [
                {
                    "code": "sample.rule",
                    "status": "skip",
                    "summary": "未发现匹配源文件",
                    "skip_reason": "KPI CSV 未匹配到任何已启用测量单元",
                }
            ],
        },
    }
    (task_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")
    return task_dir


def test_select_task_defaults_to_latest_local_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    _write_task(tmp_path, "task-online", mode="online", completed_at="2026-01-02T00:00:00Z")
    _write_task(tmp_path, "task-local-old", mode="local", completed_at="2026-01-01T00:00:00Z")
    _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")

    task = select_task(settings.output)

    assert task["task_id"] == "task-local-new"


def test_build_report_matches_rule_from_existing_task_site(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")
    (task_dir / "kpi").mkdir()
    (task_dir / "kpi" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    write_catalog_manifest(task_dir, ["kpi/stat.csv"])
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    report = build_report(task_dir, task, rule_code="kpi.measurement_units")

    assert report["task_id"] == "task-local-new"
    assert report["rule"]["code"] == "kpi.measurement_units"
    assert report["matched_files"] == ["kpi/stat.csv"]
    assert report["catalog_paths"] == ["kpi/stat.csv"]


def test_build_report_lists_extraction_entries_and_all_rule_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")
    (task_dir / "kpi").mkdir()
    (task_dir / "kpi" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    write_catalog_manifest(
        task_dir,
        ["kpi/stat.csv"],
        ignored=[
            {
                "source_relative": "source/ignored.bin",
                "member_relative": None,
                "route_id": "ignore.test",
                "product": "UMF",
                "category": None,
                "original_target": None,
                "target": None,
                "action": "ignore",
                "status": "ignored",
                "reason": "not_required",
                "error_code": None,
            }
        ],
        failures=[
            {
                "source_relative": "source/broken.zip",
                "member_relative": None,
                "route_id": "route.archive",
                "category": "other",
                "action": "expand",
                "error_code": "archive_corrupt",
                "reason": "压缩包损坏",
            }
        ],
    )
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    report = build_report(task_dir, task)

    assert report["manifest"]["entries"] == [
        {
            "source": "source/0.bin",
            "member": None,
            "target": "kpi/stat.csv",
            "category": "kpi",
            "route_id": "route.test",
            "action": "copy",
            "status": "landed",
            "reason": None,
            "error_code": None,
        },
        {
            "source": "source/ignored.bin",
            "member": None,
            "target": None,
            "category": None,
            "route_id": "ignore.test",
            "action": "ignore",
            "status": "ignored",
            "reason": "not_required",
            "error_code": None,
        },
        {
            "source": "source/broken.zip",
            "member": None,
            "target": None,
            "category": "other",
            "route_id": "route.archive",
            "action": "expand",
            "status": "failed",
            "reason": "压缩包损坏",
            "error_code": "archive_corrupt",
        },
    ]
    assert report["manifest"]["summary"]["counts"]["catalog"] == 1
    assert report["manifest"]["catalog_paths"] == ["kpi/stat.csv"]
    assert report["catalog_paths"] == ["kpi/stat.csv"]
    match = next(item for item in report["rule_matches"] if item["code"] == "kpi.measurement_units")
    assert match["matched_files"] == ["kpi/stat.csv"]


def test_human_report_shows_extraction_entries_and_rule_hits(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")
    (task_dir / "kpi").mkdir()
    (task_dir / "kpi" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    write_catalog_manifest(task_dir, ["kpi/stat.csv"])
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    report = build_report(task_dir, task)

    from scripts.debug_local import _print_human

    _print_human(report)
    output = capsys.readouterr().out

    assert "解压条目" in output
    assert "landed kpi/stat.csv <- source/0.bin" in output
    assert "规则命中" in output
    assert "HIT kpi/stat.csv" in output


def test_tree_lines_groups_files_by_top_level_directory() -> None:
    from scripts.debug_local import _tree_lines

    lines = _tree_lines(["traffic/stat.csv", "logs/service/a.log", "kpi/a.csv"])

    assert "traffic/" in lines
    assert "  stat.csv" in lines
    assert "logs/service/" in lines
    assert "  a.log" in lines
    assert "kpi/" in lines
