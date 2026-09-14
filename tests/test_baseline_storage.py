"""基线存储分层契约测试。"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.models.schemas import InspectionTask, TaskMode, TaskStats, TaskStatus, TaskTrigger
from app.services.store import save_task_meta
from tests.baseline_helpers import SAMPLE, Env, load_rule, load_task, setup_env


def test_task_record_has_no_business_evidence_columns() -> None:
    from sqlalchemy import inspect

    from app.models.db import TaskRecord

    columns = {column.name for column in inspect(TaskRecord).columns}
    forbidden = {"findings", "metrics", "rule_results", "report_html", "execution_log"}
    assert not forbidden & columns
    assert "system_id" not in columns


def test_file_storage_layout_is_single_task_directory(tmp_path: Path, monkeypatch) -> None:
    from app.cli import run_task

    env: Env = setup_env(tmp_path, monkeypatch)
    task = run_task(SAMPLE, task_id="task-sample")

    assert task.task_id == "task-sample"
    task_dir = env.task_dir("task-sample")
    expected_files = {
        "task.json",
        "system.json",
        "report.html",
        "execution.log",
        ".patrolx-extracted.json",
    }
    for name in expected_files:
        assert (task_dir / name).is_file(), f"缺少 {name}"
    assert (task_dir / "rules" / "log.error_density.json").is_file()
    assert load_rule(env, "task-sample", "log.error_density")["code"] == "log.error_density"
    assert load_task(env, "task-sample")["task_id"] == "task-sample"
    for category in {"logs", "kpi", "traffic", "alarm", "config", "resource", "other"}:
        assert (task_dir / category).is_dir(), f"缺少类别目录 {category}"

    for path in task_dir.rglob("*"):
        relative = path.relative_to(task_dir).as_posix()
        assert not relative.startswith("system_id/"), relative
        assert "/system_id/" not in relative, relative
        assert not relative.startswith("artifacts/"), relative
        assert "/artifacts/" not in relative, relative


def test_task_json_write_is_atomic_for_readers(tmp_path: Path) -> None:
    """并发重写 task.json 时，读者不应读到空文件。"""
    now = datetime.now(UTC)
    task = InspectionTask(
        task_id="task-atomic",
        name="原子写入",
        mode=TaskMode.LOCAL,
        status=TaskStatus.COMPLETED,
        trigger=TaskTrigger.CLI,
        created_at=now,
        completed_at=now,
        stats=TaskStats(total=0, pass_=0, warn=0, fail=0, error=0, skip=0, systems=1),
        system=None,
    )
    task_dir = tmp_path / task.task_id
    path = task_dir / "task.json"
    save_task_meta(tmp_path, task)
    assert json.loads(path.read_text(encoding="utf-8"))["task_id"] == task.task_id
    assert not any(item.name.startswith(".task.json.") for item in task_dir.iterdir())


def test_init_db_rebuilds_legacy_database_without_system_id(tmp_path: Path, monkeypatch) -> None:
    """旧版 SQLite 重建后不得保留 system_id，且任务元数据不丢失。"""
    import sqlite3

    from app.core.config import settings
    from app.models.db import init_db

    db_path = tmp_path / "legacy-patrolx.db"
    monkeypatch.setattr(settings, "sqlite_path", db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(256) NOT NULL,
                mode VARCHAR(16) NOT NULL,
                status VARCHAR(16) NOT NULL,
                trigger VARCHAR(16) NOT NULL,
                system_id VARCHAR(128) NOT NULL,
                package_file VARCHAR(512) NOT NULL,
                customer JSON NOT NULL,
                version VARCHAR(64),
                stats JSON NOT NULL,
                created_at DATETIME NOT NULL,
                completed_at DATETIME
            )
            """
        )
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, name, mode, status, trigger, system_id, package_file,
                customer, version, stats, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-legacy",
                "旧版任务",
                "online",
                "completed",
                "api",
                "legacy-system",
                "sample.zip",
                "{}",
                None,
                "{}",
                "2026-01-01 00:00:00.000000+00:00",
                "2026-01-01 00:01:00.000000+00:00",
            ),
        )

    init_db()

    with sqlite3.connect(db_path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(tasks)")]
        row = connection.execute(
            "SELECT task_id, name, customer, stats FROM tasks WHERE task_id = 'task-legacy'"
        ).fetchone()

    assert "system_id" not in columns
    assert row == ("task-legacy", "旧版任务", "{}", "{}")
