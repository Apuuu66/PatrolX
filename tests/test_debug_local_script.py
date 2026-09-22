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
