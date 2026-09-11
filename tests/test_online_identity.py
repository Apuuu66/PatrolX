"""在线任务身份与重跑一致性回归测试。"""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
client = TestClient(app)


def _upload(province: str, operator: str) -> dict:
    with SAMPLE.open("rb") as fh:
        response = client.post(
            "/api/v1/tasks",
            files={"package_file": ("sample.zip", fh, "application/zip")},
            data={"province": province, "operator": operator},
        )
    assert response.status_code == 202, response.text
    return response.json()


def _wait(task_id: str) -> dict:
    for _ in range(300):
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task["status"] in {"completed", "failed"}:
            return task
        time.sleep(0.05)
    raise TimeoutError(task_id)


def test_same_package_and_different_customers_get_unique_tasks() -> None:
    first = _upload("gd", "cmcc")
    second = _upload("js", "cmcc")

    assert first["task_id"] == "task-gd_cmcc"
    assert second["task_id"] == "task-js_cmcc"

    for created in (first, second):
        task = _wait(created["task_id"])
        assert task["status"] == "completed"
        assert task["system"]["system_id"] == created["task_id"].removeprefix("task-")
        assert (settings.output / created["task_id"] / task["system"]["system_id"]).is_dir()

    client.delete(f"/api/v1/tasks/{first['task_id']}")
    client.delete(f"/api/v1/tasks/{second['task_id']}")


def test_single_rule_rerun_uses_original_customer_system_dir() -> None:
    created = _upload("gd", "cmcc")
    task_id = created["task_id"]
    task = _wait(task_id)
    assert task["status"] == "completed"
    assert task["system"]["system_id"] == "gd_cmcc"

    response = client.post(f"/api/v1/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert response.status_code == 202

    task = _wait(task_id)
    assert task["status"] == "completed"
    assert task["system"]["system_id"] == "gd_cmcc"
    assert (settings.output / task_id / "gd_cmcc" / "rules" / "log.error_density.json").is_file()
    assert not (settings.output / task_id / "sample").exists()

    client.delete(f"/api/v1/tasks/{task_id}")
