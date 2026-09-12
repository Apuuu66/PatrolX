"""任务删除级联语义测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import setup_env, upload_package, wait_for_task

client = TestClient(app)


def test_delete_removes_all_task_state(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client)
    wait_for_task(client, task_id)
    assert (env.task_dir(task_id) / "task.json").is_file()

    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 204

    assert not env.task_dir(task_id).exists()
    assert not (tmp_path / "uploads" / task_id).exists()
    list_response = client.get("/api/v1/tasks")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0
    for path in (f"tasks/{task_id}", f"tasks/{task_id}/system", f"tasks/{task_id}/rules/alarm.stat"):
        assert client.get(f"/api/v1/{path}").status_code == 404
    assert client.get(f"/api/v1/tasks/{task_id}/report").status_code == 404
    assert client.get(f"/api/v1/tasks/{task_id}/logs").status_code == 404
    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 404
