"""US2：留存清理只保留最近 50 个任务现场（034 / T024）。

独立测试口径：保留集合 = 按 ``COALESCE(last_run_at, created_at)`` 倒序的前 50 个任务
∪ 所有 ``pending``/``running`` 任务；清理只删磁盘、不改数据库行；单次删除失败只记录
日志，不影响任务终态。
"""

from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.db import TaskRecord, session_factory
from app.services import retention
from tests.baseline_helpers import Env, setup_env, upload_package, wait_for_task

client = TestClient(app)
BASE = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _seed(
    env: Env,
    *,
    index: int,
    status: str = "completed",
    last_run: bool = True,
) -> str:
    """创建第 index 个任务现场：现场目录 + uploads 包 + 数据库任务行。"""
    task_id = f"task-seed-{index:02d}"
    created_at = BASE + timedelta(minutes=index)
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                name=task_id,
                mode="online",
                status=status,
                trigger="api",
                package_file=f"{task_id}.zip",
                customer={},
                stats={},
                package_kind="inspection",
                created_at=created_at,
                last_run_at=created_at if last_run else None,
                completed_at=created_at if status == "completed" else None,
            )
        )
        session.commit()
    (env.uploads / task_id).mkdir(parents=True, exist_ok=True)
    (env.uploads / task_id / f"{task_id}.zip").write_bytes(b"PK\x03\x04")
    (env.output / task_id).mkdir(parents=True, exist_ok=True)
    (env.output / task_id / "task.json").write_text("{}", encoding="utf-8")
    return task_id


def _disk_task_ids(env: Env) -> set[str]:
    return {path.name for path in env.output.iterdir() if path.is_dir()}


def test_cleanup_keeps_only_the_most_recent_fifty(monkeypatch, tmp_path: Path) -> None:
    """51 个任务清理后磁盘仅保留最近 50 个，数据库行一个都不删。"""
    env = setup_env(tmp_path, monkeypatch)
    ids = [_seed(env, index=index) for index in range(51)]

    result = retention.cleanup()

    assert _disk_task_ids(env) == set(ids[1:]), "磁盘只剩最近 50 个任务现场"
    assert not (env.uploads / ids[0]).exists(), "被清理任务的压缩包现场同时删除"
    assert (env.uploads / ids[-1]).exists()
    assert set(result.removed_directories) >= {
        str(env.output / ids[0]),
        str(env.uploads / ids[0]),
    }
    assert result.retained == set(ids[1:])
    with session_factory() as session:
        assert session.query(TaskRecord).count() == 51, "清理不得删除数据库任务行"


def test_cleanup_is_noop_at_exactly_fifty(monkeypatch, tmp_path: Path) -> None:
    """恰好 50 个任务时不触发任何删除。"""
    env = setup_env(tmp_path, monkeypatch)
    ids = [_seed(env, index=index) for index in range(50)]

    result = retention.cleanup()

    assert result.removed_directories == []
    assert result.removed_packages == []
    assert _disk_task_ids(env) == set(ids)


def _set_status(task_id: str, status: str) -> None:
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        assert record is not None
        record.status = status
        session.commit()


def test_pending_and_running_tasks_are_never_cleaned(monkeypatch, tmp_path: Path) -> None:
    """执行中任务即使最旧也必须保留，其余超出 50 的按最近运行时间清理。"""
    env = setup_env(tmp_path, monkeypatch)
    ids = [_seed(env, index=index) for index in range(55)]
    # 把最旧的两个任务改成执行中：即便排序超出最近 50 也必须豁免清理。
    _set_status(ids[0], "running")
    _set_status(ids[1], "pending")

    result = retention.cleanup()

    assert {ids[0], ids[1]} <= result.retained
    assert (env.output / ids[0]).is_dir() and (env.uploads / ids[0]).is_dir()
    assert (env.output / ids[1]).is_dir() and (env.uploads / ids[1]).is_dir()
    # 保留集合 = 最近 50（seed-05..seed-54）∪ 两个执行中任务 → seed-02..seed-04 被清理
    assert _disk_task_ids(env) == set(ids[5:]) | {ids[0], ids[1]}
    assert not (env.output / ids[2]).exists() and not (env.output / ids[4]).exists()


def test_never_run_tasks_sort_by_created_at(monkeypatch, tmp_path: Path) -> None:
    """从未运行的任务按创建时间参与排序，最旧的被清理。"""
    env = setup_env(tmp_path, monkeypatch)
    ids = [_seed(env, index=index, last_run=False) for index in range(51)]

    retention.cleanup()

    assert not (env.output / ids[0]).exists()
    assert (env.output / ids[1]).is_dir()
    assert (env.uploads / ids[0]).exists() is False


def test_cleanup_failure_is_logged_and_other_removals_continue(monkeypatch, tmp_path: Path, capsys) -> None:
    """单个目录删除失败只记录日志并留待下次重试，不影响其他任务的清理。"""
    env = setup_env(tmp_path, monkeypatch)
    ids = [_seed(env, index=index) for index in range(52)]
    failing = env.output / ids[0]
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path: str | Path, *args, **kwargs) -> None:
        if Path(path) == failing:
            raise OSError("模拟删除失败")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(retention.shutil, "rmtree", flaky_rmtree)

    result = retention.cleanup()

    assert result.failed_paths == [str(failing)]
    assert failing.is_dir(), "删除失败的任务现场保留，等待下次清理重试"
    assert not (env.output / ids[1]).exists(), "其他超期任务继续清理"
    assert not (env.uploads / ids[1]).exists()
    captured = capsys.readouterr()
    assert "scene_cleanup_failed" in captured.out + captured.err, "删除失败必须留日志"


def test_terminal_task_triggers_retention_cleanup(monkeypatch, tmp_path: Path) -> None:
    """任务终态发布后自动执行留存清理，无需人工干预。"""
    from app.services.retention import CleanupResult

    env = setup_env(tmp_path, monkeypatch)
    calls: list[dict] = []

    def spy(**kwargs) -> CleanupResult:
        calls.append(kwargs)
        return CleanupResult()

    monkeypatch.setattr(retention, "cleanup", spy)
    task_id = upload_package(env, client, name="终态触发清理")
    wait_for_task(client, task_id)

    deadline = time.time() + 10
    while not calls and time.time() < deadline:
        time.sleep(0.02)

    assert calls, "任务终态必须触发留存清理"
    assert calls[0]["uploads"] == env.uploads
    assert calls[0]["output"] == env.output


def test_cleanup_failure_never_changes_task_terminal_state(monkeypatch, tmp_path: Path) -> None:
    """清理自身异常只记日志，不改任务终态、不阻塞发布。"""
    env = setup_env(tmp_path, monkeypatch)

    def boom(**kwargs):
        raise RuntimeError("模拟清理异常")

    monkeypatch.setattr(retention, "cleanup", boom)
    task_id = upload_package(env, client, name="清理异常不阻断")
    task = wait_for_task(client, task_id)

    assert task["status"] == "completed"
    assert task["completed_at"] is not None and task["duration_ms"] >= 0


def test_cleanup_never_deletes_unknown_directories_or_unconsumed_packages(monkeypatch, tmp_path: Path) -> None:
    """安全不变式：不属于任何已知任务的目录与未消费散包不删除（data-model 留存与恢复）。"""
    env = setup_env(tmp_path, monkeypatch)
    _seed(env, index=0)

    orphan_output = env.output / "task-manual-orphan"
    orphan_output.mkdir(parents=True, exist_ok=True)
    (orphan_output / "task.json").write_text("{}", encoding="utf-8")
    orphan_upload = env.uploads / "task-manual-orphan"
    orphan_upload.mkdir(parents=True, exist_ok=True)

    stray_package = env.uploads / "manual-drop.zip"
    stray_package.write_bytes(b"PK\x03\x04")

    result = retention.cleanup()

    assert orphan_output.is_dir()
    assert orphan_upload.is_dir()
    assert stray_package.is_file()
    assert str(orphan_output) in result.skipped_unknown
    assert result.removed_directories == []
    assert result.removed_packages == []
