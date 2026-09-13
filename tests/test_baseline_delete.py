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

    upload_dir = tmp_path / "uploads" / task_id
    task_dir = env.task_dir(task_id)
    assert upload_dir.is_dir()
    assert task_dir.is_dir()
    assert (task_dir / "task.json").is_file()
    assert (task_dir / "system.json").is_file()
    assert (task_dir / "report.html").is_file()
    assert (task_dir / "execution.log").is_file()
    rule_files = sorted((task_dir / "rules").glob("*.json"))
    assert rule_files

    for path in (
        f"tasks/{task_id}",
        f"tasks/{task_id}/system",
        f"tasks/{task_id}/report",
        f"tasks/{task_id}/logs",
    ):
        assert client.get(f"/api/v2/{path}").status_code == 200
    assert client.get(f"/api/v2/tasks/{task_id}/rules/alarm.stat").status_code == 200

    assert client.delete(f"/api/v2/tasks/{task_id}").status_code == 204

    assert not upload_dir.exists()
    assert not task_dir.exists()
    list_response = client.get("/api/v2/tasks")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0
    for path in (
        f"tasks/{task_id}",
        f"tasks/{task_id}/system",
        f"tasks/{task_id}/report",
        f"tasks/{task_id}/logs",
    ):
        assert client.get(f"/api/v2/{path}").status_code == 404
    assert client.get(f"/api/v2/tasks/{task_id}/rules/alarm.stat").status_code == 404
    assert client.delete(f"/api/v2/tasks/{task_id}").status_code == 404
