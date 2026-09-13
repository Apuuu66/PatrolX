"""可观测性：/metrics Prometheus 指标与任务生命周期执行日志。"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
client = TestClient(app)


def _upload_and_wait() -> str:
    with SAMPLE.open("rb") as fh:
        resp = client.post(
            "/api/v2/tasks",
            files={"package_file": ("observability_sample.zip", fh, "application/zip")},
            data={"name": "可观测性"},
        )
    task_id = resp.json()["task_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        status = client.get(f"/api/v2/tasks/{task_id}").json()["status"]
        if status in ("completed", "failed"):
            return task_id
        time.sleep(0.1)
    raise TimeoutError(f"任务 {task_id} 未完成")


def test_metrics_endpoint() -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "patrolx_tasks_total" in resp.text
    assert "patrolx_rules_total" in resp.text
    assert "patrolx_task_duration_seconds" in resp.text


def test_task_lifecycle_logs() -> None:
    task_id = _upload_and_wait()
    log_file = settings.output / task_id / "execution.log"
    assert log_file.exists()
    messages = [
        json.loads(line)["message"] for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert any("任务创建" in m for m in messages)
    assert any("任务完成" in m for m in messages)
