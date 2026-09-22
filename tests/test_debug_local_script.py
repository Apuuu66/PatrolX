"""local_run 任务调试脚本测试。"""

import json
from pathlib import Path

from app.core.config import settings
from scripts.debug_local import build_report, select_task


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
                    "skip_reason": "source_patterns 未匹配到文件: ^traffic/.*$",
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
    (task_dir / "traffic").mkdir()
    (task_dir / "traffic" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (task_dir / ".patrolx-extracted.json").write_text(
        json.dumps({"version": 4, "main": {"count": 1}, "files": []}),
        encoding="utf-8",
    )
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    report = build_report(task_dir, task, rule_code="traffic.stat")

    assert report["task_id"] == "task-local-new"
    assert report["rule"]["code"] == "traffic.stat"
    assert report["matched_files"] == ["traffic/stat.csv"]
    assert report["catalog_paths"] == ["traffic/stat.csv"]


def test_build_report_lists_extraction_entries_and_all_rule_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")
    (task_dir / "traffic").mkdir()
    (task_dir / "traffic" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (task_dir / ".patrolx-extracted.json").write_text(
        json.dumps(
            {
                "version": 4,
                "main": {"count": 1},
                "files": [
                    {
                        "source": "stat.csv",
                        "target": "traffic/stat.csv",
                        "category": "traffic",
                        "status": "extracted",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    report = build_report(task_dir, task)

    assert report["manifest"]["entries"] == [
        {
            "source": "stat.csv",
            "target": "traffic/stat.csv",
            "category": "traffic",
            "status": "extracted",
        }
    ]
    assert report["catalog_paths"] == ["traffic/stat.csv"]
    match = next(item for item in report["rule_matches"] if item["code"] == "traffic.stat")
    assert match["matched_files"] == ["traffic/stat.csv"]


def test_human_report_shows_extraction_entries_and_rule_hits(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    task_dir = _write_task(tmp_path, "task-local-new", mode="local", completed_at="2026-01-03T00:00:00Z")
    (task_dir / "traffic").mkdir()
    (task_dir / "traffic" / "stat.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (task_dir / ".patrolx-extracted.json").write_text(
        json.dumps(
            {
                "version": 4,
                "main": {"count": 1},
                "files": [
                    {
                        "source": "stat.csv",
                        "target": "traffic/stat.csv",
                        "category": "traffic",
                        "status": "extracted",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    report = build_report(task_dir, task)

    from scripts.debug_local import _print_human

    _print_human(report)
    output = capsys.readouterr().out

    assert "解压条目" in output
    assert "traffic/stat.csv <- stat.csv" in output
    assert "规则命中" in output
    assert "HIT traffic/stat.csv" in output


def test_tree_lines_groups_files_by_top_level_directory() -> None:
    from scripts.debug_local import _tree_lines

    lines = _tree_lines(["traffic/stat.csv", "logs/service/a.log", "kpi/a.csv"])

    assert "traffic/" in lines
    assert "  stat.csv" in lines
    assert "logs/service/" in lines
    assert "  a.log" in lines
    assert "kpi/" in lines
