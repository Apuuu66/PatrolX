"""基础包上传 API 用例。"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import SAMPLE, Env, setup_env, wait_for_task


def test_upload_windows_path_filename_stays_inside_task_directory(tmp_path: Path, monkeypatch) -> None:
    """客户端携带 Windows 路径分隔符时，后端必须只保留包名并写入任务目录。"""
    env: Env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)

    with SAMPLE.open("rb") as package_file:
        response = client.post(
            "/api/v2/tasks",
            files={"package_file": (r"..\..\sample.zip", package_file, "application/zip")},
            data={"name": "Windows 包上传"},
        )

    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"
    assert (env.uploads / task_id / "sample.zip").is_file()
    assert task["system"] is not None
    assert task["system"]["package_file"] == "sample.zip"


def test_upload_accepts_legacy_database_after_rebuild(tmp_path: Path, monkeypatch) -> None:
    """旧版 system_id 库会在上传前重建，包上传仍应正常执行。"""
    import sqlite3

    from app.models.db import init_db

    env: Env = setup_env(tmp_path, monkeypatch)
    with sqlite3.connect(env.sqlite) as connection:
        connection.execute("DROP TABLE tasks")
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(256) NOT NULL,
                mode VARCHAR(16) NOT NULL,
                status VARCHAR(16) NOT NULL,
                trigger VARCHAR(16) NOT NULL,
                system_id VARCHAR(128) NOT NULL,
                package_file VARCHAR(512) NOT NULL,
                customer JSON NOT NULL,
                version VARCHAR(64),
                stats JSON NOT NULL,
                created_at DATETIME NOT NULL,
                completed_at DATETIME
            )
            """
        )
    init_db()

    client = TestClient(app)
    task_id = ""
    with SAMPLE.open("rb") as package_file:
        response = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", package_file, "application/zip")},
            data={"name": "旧库重建后上传"},
        )
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    task = wait_for_task(client, task_id)
    assert task["status"] == "completed"

    with sqlite3.connect(env.sqlite) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(tasks)")]
    assert "system_id" not in columns
