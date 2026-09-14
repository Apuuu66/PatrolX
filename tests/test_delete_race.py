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
