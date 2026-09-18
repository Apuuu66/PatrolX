"""系统基线测试助手：统一临时环境、任务等待与契约结果读取。"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.db import init_db
from tests.kpi_helpers import configure_kpi_catalog

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
VOLATILE_KEYS = {"executed_at", "duration_ms"}


@dataclass(slots=True)
class Env:
    """一次测试可复用的本地/在线运行环境。"""

    root: Path
    uploads: Path
    output: Path
    sqlite: Path

    def task_dir(self, task_id: str) -> Path:
        return self.output / task_id

    def rules_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "rules"


def setup_env(tmp_path: Path, monkeypatch) -> Env:
    """将运行时目录和 SQLite 指向当前测试的临时现场。"""
    env = Env(
        root=tmp_path,
        uploads=tmp_path / "uploads",
        output=tmp_path / "output",
        sqlite=tmp_path / "patrolx.db",
    )
    env.uploads.mkdir(parents=True, exist_ok=True)
    env.output.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "uploads_dir", env.uploads)
    monkeypatch.setattr(settings, "output_dir", env.output)
    monkeypatch.setattr(settings, "sqlite_path", env.sqlite)
    init_db()
    monkeypatch.chdir(env.root)
    configure_kpi_catalog(env.root, monkeypatch, output_dir=env.output, sqlite_path=env.sqlite)
    monkeypatch.setattr(settings, "uploads_dir", env.uploads)
    monkeypatch.setattr(settings, "output_dir", env.output)
    monkeypatch.setattr(settings, "sqlite_path", env.sqlite)
    return env


def wait_for_task(client: TestClient, task_id: str, timeout: float = 180.0) -> dict[str, Any]:
    """轮询在线任务直到 completed/failed；上限覆盖完整月度样例的执行耗时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v2/tasks/{task_id}")
        if response.status_code == 200:
            task = response.json()
            if task["status"] in ("completed", "failed"):
                return task
        time.sleep(0.05)
    raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内完成")


def upload_package(
    env: Env,
    client: TestClient,
    *,
    package: Path = SAMPLE,
    name: str | None = None,
    **metadata: str,
) -> str:
    """以在线 API 创建任务并返回 task_id。"""
    with package.open("rb") as fh:
        response = client.post(
            "/api/v2/tasks",
            files={"package_file": (package.name, fh, "application/zip")},
            data={"name": name or "基线任务", **metadata},
        )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def load_task(env: Env, task_id: str) -> dict[str, Any]:
    """读取 output/<task_id>/task.json 契约。"""
    return json.loads((env.task_dir(task_id) / "task.json").read_text(encoding="utf-8"))


def load_system(env: Env, task_id: str) -> dict[str, Any]:
    """读取 output/<task_id>/system.json 契约。"""
    return json.loads((env.task_dir(task_id) / "system.json").read_text(encoding="utf-8"))


def load_rule(env: Env, task_id: str, code: str) -> dict[str, Any]:
    """读取 output/<task_id>/rules/<code>.json 契约。"""
    return json.loads((env.rules_dir(task_id) / f"{code}.json").read_text(encoding="utf-8"))


def load_logs(env: Env, task_id: str) -> list[dict[str, Any]]:
    """读取结构化执行日志。"""
    path = env.task_dir(task_id) / "execution.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def strip_volatile(data: Any) -> Any:
    """剥离执行时间、耗时等运行态字段，用于双模式一致性比较。"""
    if isinstance(data, dict):
        return {k: strip_volatile(v) for k, v in data.items() if k not in VOLATILE_KEYS}
    if isinstance(data, list):
        return [strip_volatile(item) for item in data]
    return data
