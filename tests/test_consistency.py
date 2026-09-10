"""双模式一致性测试：同一数据包经 CLI 与 API 执行，契约结果逐字段一致（除时间/耗时）。"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli import clean_system_id, run_task
from app.core.config import settings
from app.main import app

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
client = TestClient(app)

VOLATILE_KEYS = {"executed_at", "duration_ms"}


def _strip_volatile(data: object) -> object:
    if isinstance(data, dict):
        return {k: _strip_volatile(v) for k, v in data.items() if k not in VOLATILE_KEYS}
    if isinstance(data, list):
        return [_strip_volatile(v) for v in data]
    return data


def _wait(task_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.1)
    raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内完成")


def test_cli_api_result_consistency(tmp_path: Path, monkeypatch) -> None:
    cli_out = tmp_path / "cli"
    api_out = tmp_path / "api"
    monkeypatch.setattr(settings, "output_dir", cli_out)
    cli_task = run_task(SAMPLE, name="一致性", task_id="cli-task")
    cli_system = json.loads(
        (cli_out / "cli-task" / clean_system_id(SAMPLE.name) / "system.json").read_text(encoding="utf-8")
    )

    monkeypatch.setattr(settings, "output_dir", api_out)
    with SAMPLE.open("rb") as fh:
        resp = client.post(
            "/api/v1/tasks",
            params={"force": "true"},
            files={"package_file": ("sample.zip", fh, "application/zip")},
            data={"name": "一致性"},
        )
    assert resp.status_code == 202, resp.text
    api_task = _wait(resp.json()["task_id"])
    assert api_task["status"] == "completed"
    api_system = client.get(f"/api/v1/tasks/{api_task['task_id']}/system").json()

    assert _strip_volatile(cli_system) == _strip_volatile(api_system)
    assert cli_task.stats.pass_ == api_task["stats"]["pass"]
