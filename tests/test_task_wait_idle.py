"""在线任务等待辅助必须覆盖终态发布的全部收尾阶段。"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services import retention
from app.services import tasks as tasks_module
from app.services.tasks import task_service
from tests.baseline_helpers import setup_env, upload_package, wait_for_task

client = TestClient(app)


def test_wait_for_task_waits_until_terminal_cleanup_releases_execution_lock(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """任务已 completed 时，后台线程仍可能镜像 KPI；等待辅助不得提前返回。"""
    env = setup_env(tmp_path, monkeypatch, assign_rules_to="UMF")
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    def delayed_cleanup(*, output: Path, uploads: Path) -> None:
        cleanup_started.set()
        assert release_cleanup.wait(5), "测试未及时释放留存清理"
        original_cleanup(output=output, uploads=uploads)

    original_cleanup = retention.cleanup_safely
    monkeypatch.setattr(retention, "cleanup_safely", delayed_cleanup)
    task_id = upload_package(env, client, name="等待收尾", product="UMF")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v2/tasks/{task_id}")
        if response.status_code == 200 and response.json()["status"] == "completed":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("任务未进入 completed")

    assert cleanup_started.wait(5), "后台任务未进入终态清理"
    result: dict[str, Any] = {}
    waiter = threading.Thread(target=lambda: result.setdefault("task", wait_for_task(client, task_id, timeout=5)))
    waiter.start()
    waiter.join(0.2)
    try:
        assert waiter.is_alive(), "wait_for_task 在终态清理完成前提前返回"
    finally:
        release_cleanup.set()
        waiter.join(5)
        monkeypatch.setattr(retention, "cleanup_safely", original_cleanup)

    assert not waiter.is_alive()
    assert result["task"]["status"] == "completed"


def test_worker_continues_after_task_finalization_failure(monkeypatch: Any) -> None:
    """单任务失败收尾异常不得杀死常驻 worker，后续排队任务仍须执行。"""
    executed: list[str] = []
    recovered = threading.Event()

    def fail_execution(task_id: str) -> None:
        executed.append(task_id)
        if task_id == "task-broken":
            raise RuntimeError("任务执行失败")
        recovered.set()

    def fail_finalization(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("失败收尾也失败")

    monkeypatch.setattr(task_service, "_execute", fail_execution)
    monkeypatch.setattr(task_service, "_finish_run", fail_finalization)
    monkeypatch.setattr(tasks_module, "append_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks_module.logger, "exception", lambda *_args, **_kwargs: None)

    task_service._queue.put("task-broken")
    task_service._queue.put("task-recovered")

    assert recovered.wait(2), "worker 在失败收尾异常后停止消费队列"
    assert executed == ["task-broken", "task-recovered"]
    assert task_service._worker.is_alive()
