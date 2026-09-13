"""重跑状态可见性回归测试。"""

import time

from fastapi.testclient import TestClient
from test_api import _upload, _wait

from app.main import app
from app.services.tasks import task_service


def test_rerun_marks_output_task_pending_before_queueing(monkeypatch) -> None:
    client = TestClient(app)
    task_id = _upload("rerun-pending.zip")
    _wait(task_id)

    # 阻断队列，保证断言发生在 rerun 受理阶段，而不是依赖 worker 完成速度。
    monkeypatch.setattr(task_service._queue, "put", lambda _task_id: None)
    resp = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202

    task = task_service.get(task_id)
    assert task is not None
    assert task.status.value in {"pending", "running"}
    assert task.completed_at is None

    # 避免阻断队列后的残留计划影响同进程后续测试。
    task_service._rerun_plan.pop(task_id, None)


def test_rerun_failure_updates_output_status(monkeypatch) -> None:
    client = TestClient(app)
    task_id = _upload("rerun-failed.zip")
    _wait(task_id)

    def raise_rerun(*args, **kwargs):
        raise RuntimeError("rerun failed")

    monkeypatch.setattr("app.services.tasks.run_single_rule", raise_rerun)
    resp = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202

    deadline = time.time() + 2
    while time.time() < deadline:
        task = task_service.get(task_id)
        assert task is not None
        if task.status.value in {"failed", "completed"}:
            break
        time.sleep(0.02)
    assert task is not None
    assert task.status.value == "failed"
    assert task.completed_at is not None
