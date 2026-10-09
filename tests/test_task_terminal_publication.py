"""终态发布一致性：任务对读方可见为终态前，报告、收尾日志与数据库记录必须已就绪。

回归背景：在线任务曾在收尾（台账归档 / 报告渲染 / 收尾日志）之前就写出 completed
的 ``task.json``，导致读方看到完成态后立刻读报告、删除任务或按数据库记录兜底列表时
命中尚未收敛的状态（CI 上表现为 tests/test_delete_race.py、tests/test_observability.py 偶发失败）。
"""

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from test_api import _upload

from app.core.config import settings
from app.main import app
from app.models.db import TaskRecord, session_factory
from app.models.schemas import TaskStatus
from app.services import store

TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def _wait_terminal(client: TestClient, task_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/v2/tasks/{task_id}").json()
        if task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.01)
    raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内进入终态")


def test_terminal_status_not_visible_before_artifacts(monkeypatch) -> None:
    """收尾阶段尚未完成时，任务不得对外显示终态；终态可见时报告与收尾日志已就绪。"""
    import app.cli as cli

    started = threading.Event()
    release = threading.Event()
    original = cli.render_report

    def blocked_render(*args, **kwargs):
        started.set()
        assert release.wait(timeout=20), "收尾阻塞未被释放"
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "render_report", blocked_render)
    client = TestClient(app)
    task_id = _upload("terminal-publication.zip")
    assert started.wait(timeout=20)

    try:
        visible = client.get(f"/api/v2/tasks/{task_id}").json()
        assert visible["status"] not in ("completed", "failed"), "报告尚未生成就不应对外暴露终态"
        assert visible["status"] == "running"
    finally:
        release.set()

    task = _wait_terminal(client, task_id)
    assert task["status"] == "completed"
    assert (settings.output / task_id / "report.html").is_file(), "终态可见时报告必须已生成"
    log_text = (settings.output / task_id / "execution.log").read_text(encoding="utf-8")
    assert "任务完成" in log_text, "终态可见时收尾日志必须已写入"


def test_terminal_record_converges_before_task_file(monkeypatch) -> None:
    """终态 task.json 发布的瞬间，SQLite 记录必须已是终态，兜底列表不得回退为运行中。"""
    observed: dict[str, str | None] = {}
    original = store.save_task_meta

    def spy(output: Path, task) -> None:
        if task.status in TERMINAL:
            with session_factory() as session:
                record = session.get(TaskRecord, task.task_id)
            observed.setdefault("record_status", record.status if record else None)
        original(output, task)

    monkeypatch.setattr(store, "save_task_meta", spy)
    client = TestClient(app)
    task_id = _upload("terminal-record.zip")
    task = _wait_terminal(client, task_id)

    assert task["status"] == "completed"
    assert observed.get("record_status") == "completed", "文件发布终态前数据库记录必须已收敛"
