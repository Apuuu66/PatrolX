import threading
import time

from fastapi.testclient import TestClient
from test_api import _upload, _wait

from app.core.config import settings
from app.main import app
from app.models.schemas import TaskStatus
from app.services import store
from app.services.tasks import task_service


def test_delete_running_task_is_rejected_and_does_not_resurrect(monkeypatch) -> None:
    client = TestClient(app)
    task_id = _upload("delete-running.zip")
    _wait(task_id)

    release = threading.Event()
    original = store.load_task_meta(settings.output, task_id)
    assert original is not None

    started = threading.Event()

    def blocked_run(_package, **kwargs):
        started.set()
        release.wait(timeout=3)
        completed = original.model_copy(update={"status": TaskStatus.COMPLETED, "completed_at": None})
        store.save_task_meta(settings.output, completed)
        return completed

    monkeypatch.setattr("app.services.tasks.run_task", blocked_run)
    assert task_service.rerun(task_id, None) is True

    assert started.wait(timeout=2)

    resp = client.delete(f"/api/v2/tasks/{task_id}")
    assert resp.status_code == 409
    release.set()
    time.sleep(0.1)
    assert task_service.get(task_id) is not None


def test_delete_failure_keeps_task_and_restores_meta(monkeypatch) -> None:
    """现场删除失败必须结构化返回，任务仍可列表并保留 task.json。"""
    client = TestClient(app)
    task_id = _upload("delete-failed.zip")
    _wait(task_id)
    task_file = settings.output / task_id / "task.json"
    original_meta = task_file.read_text(encoding="utf-8")

    def failed_rmtree(_path, *args, **kwargs):
        del args, kwargs
        raise OSError(39, "The directory is not empty", str(settings.output / task_id / "kpi"))

    monkeypatch.setattr("app.services.tasks.shutil.rmtree", failed_rmtree)
    resp = client.delete(f"/api/v2/tasks/{task_id}")

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "task_delete_failed"
    assert body["detail"]["task_id"] == task_id
    assert body["detail"]["locations"] == [f"output/{task_id}", f"uploads/{task_id}"]
    assert body["detail"]["failed_path"] == f"{settings.output / task_id / 'kpi'}"
    assert task_file.read_text(encoding="utf-8") == original_meta

    listing = client.get("/api/v2/tasks").json()
    assert any(task["task_id"] == task_id for task in listing["items"])


def test_delete_long_path_failure_includes_limit(monkeypatch) -> None:
    """Windows 路径过长删除失败时返回路径长度和上限。"""
    client = TestClient(app)
    task_id = _upload("delete-long-path.zip")
    _wait(task_id)

    def failed_rmtree(_path, *args, **kwargs):
        del args, kwargs
        raise OSError(206, "Filename or extension is too long", str(settings.output / task_id))

    monkeypatch.setattr("app.services.tasks.shutil.rmtree", failed_rmtree)
    monkeypatch.setattr(
        "app.services.tasks.PathLimitPolicy.current", classmethod(lambda cls: cls(enabled=True, limit=260))
    )
    resp = client.delete(f"/api/v2/tasks/{task_id}")

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["path_length"] == len(str(settings.output / task_id))
    assert detail["path_limit"] == 260


def test_completed_task_without_task_json_falls_back_to_record(monkeypatch) -> None:
    """output 元数据被部分删除时，完成态在线任务仍能从数据库记录列出。"""
    client = TestClient(app)
    task_id = _upload("delete-partial-meta.zip")
    _wait(task_id)
    (settings.output / task_id / "task.json").unlink()

    listing = client.get("/api/v2/tasks").json()
    fallback = next(task for task in listing["items"] if task["task_id"] == task_id)
    assert fallback["status"] == "completed"
    assert fallback["stats"]["total"] == 0
