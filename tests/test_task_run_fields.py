"""运行字段生命周期：``last_run_at`` / ``duration_ms`` 由运行开始与终态写入。

覆盖 FR-008：创建时间与最后一次运行时间相互独立；重跑/重建覆盖为最近一次运行；
从未运行两列均为 NULL；运行中不得残留上一次耗时。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from test_api import _upload, _wait

from app.main import app
from app.models.db import TaskRecord, session_factory
from app.services import task_db
from app.services.tasks import task_service
from tests.baseline_helpers import SAMPLE, setup_env

client = TestClient(app)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def test_terminal_task_records_run_fields_and_keeps_created_at() -> None:
    """终态任务必须记录最近一次运行开始时刻与耗时；创建时间保持不变。"""
    task_id = _upload("run-fields-terminal.zip")
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        assert record is not None
        created_at = record.created_at

    task = _wait(task_id)
    assert task["status"] == "completed"

    last_run_at, duration_ms, _ = task_db.get_run_fields(task_id)
    assert last_run_at is not None
    assert duration_ms is not None and duration_ms >= 0
    assert task["last_run_at"] is not None
    assert task["duration_ms"] == duration_ms, "API 摘要必须直接来自任务行"

    completed_at = _parse_time(task["completed_at"])
    assert duration_ms == max(0, int((completed_at - last_run_at).total_seconds() * 1000))

    with session_factory() as session:
        assert session.get(TaskRecord, task_id).created_at == created_at


def test_rerun_refreshes_last_run_at_and_clears_duration_while_running(monkeypatch) -> None:
    """重跑开始即刷新最近运行时间并清空旧耗时，终态写入本次耗时。"""
    task_id = _upload("run-fields-rerun.zip")
    _wait(task_id)
    first_last_run_at, first_duration, _ = task_db.get_run_fields(task_id)
    assert first_last_run_at is not None
    assert first_duration is not None

    started = threading.Event()
    release = threading.Event()

    def blocked_run(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=20), "重跑阻塞未被释放"
        return None

    monkeypatch.setattr("app.services.tasks.run_single_rule", blocked_run)
    response = client.post(
        f"/api/v2/tasks/{task_id}/rerun",
        json={"rule_codes": ["log.error_density"]},
    )
    assert response.status_code == 202
    assert started.wait(timeout=20)
    try:
        running_last, running_duration, _ = task_db.get_run_fields(task_id)
        assert running_last is not None and running_last >= first_last_run_at
        assert running_duration is None, "运行中不得保留上一次耗时"
        running = client.get(f"/api/v2/tasks/{task_id}").json()
        assert running["status"] == "running"
        assert running["duration_ms"] is None
        assert running["last_run_at"] is not None
    finally:
        release.set()

    final = _wait(task_id)
    assert final["status"] == "completed"
    final_last, final_duration, _ = task_db.get_run_fields(task_id)
    assert final_last == running_last, "终态不得回退为上一次运行的开始时刻"
    assert final_duration is not None and final_duration >= 0
    completed_at = _parse_time(final["completed_at"])
    assert final_duration == max(0, int((completed_at - final_last).total_seconds() * 1000))


def test_never_running_task_keeps_run_fields_null(tmp_path, monkeypatch) -> None:
    """从未运行的任务两列均为 NULL；pending 展示不得出现误导性时长。"""
    setup_env(tmp_path, monkeypatch)
    created = task_service.reserve(
        "never-running.zip",
        name="从未运行",
        province="北京",
        operator="移动",
        version="V1",
    )
    last_run_at, duration_ms, _ = task_db.get_run_fields(created.task_id)
    assert last_run_at is None
    assert duration_ms is None

    summary = client.get(f"/api/v2/tasks/{created.task_id}").json()
    assert summary["status"] == "pending"
    assert summary["last_run_at"] is None
    assert summary["duration_ms"] is None


def test_local_cli_run_task_writes_run_fields(tmp_path, monkeypatch) -> None:
    """本地 CLI 终态同样写入运行字段，保证历史回填后展示口径一致。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, name="本地运行字段", customer={"province": "北京", "operator": "移动"})
    assert task.last_run_at is not None
    assert task.duration_ms is not None and task.duration_ms >= 0

    payload = json.loads((env.task_dir(task.task_id) / "task.json").read_text(encoding="utf-8"))
    assert payload["last_run_at"] is not None
    assert payload["duration_ms"] == task.duration_ms

    last_run_at, duration_ms, _ = task_db.get_run_fields(task.task_id)
    assert last_run_at is not None
    assert duration_ms == task.duration_ms


def test_local_cli_single_rule_rerun_refreshes_run_fields(tmp_path, monkeypatch) -> None:
    """``verify-one`` 单规则重跑也要覆盖现场与库内的运行字段。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    task = run_task(SAMPLE, name="本地单规则重跑", customer={"province": "北京", "operator": "移动"})
    first_last_run_at = task.last_run_at
    assert first_last_run_at is not None

    run_single_rule("log.error_density", SAMPLE, task_id=task.task_id)
    payload = json.loads((env.task_dir(task.task_id) / "task.json").read_text(encoding="utf-8"))
    assert payload["last_run_at"] is not None
    assert _parse_time(payload["last_run_at"]) >= first_last_run_at
    assert payload["duration_ms"] is not None and payload["duration_ms"] >= 0
