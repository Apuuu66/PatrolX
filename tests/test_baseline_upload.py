"""基础包上传 API 用例。"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.router import _receive_upload
from app.main import app
from app.services.tasks import task_service
from tests.baseline_helpers import SAMPLE, Env, setup_env, wait_for_task


def test_receive_upload_closes_mkstemp_descriptor(tmp_path: Path, monkeypatch) -> None:
    """mkstemp 返回的描述符必须交给写入文件对象管理，不能在上传后残留。"""
    setup_env(tmp_path, monkeypatch)
    captured_fd: dict[str, int] = {}
    original_mkstemp = tempfile.mkstemp

    def capture_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = original_mkstemp(*args, **kwargs)  # type: ignore[arg-type]
        captured_fd["fd"] = fd
        return fd, name

    monkeypatch.setattr("app.api.router.tempfile.mkstemp", capture_mkstemp)
    upload = SAMPLE.read_bytes()
    chunks = iter([upload, b""])

    class UploadStub:
        async def read(self, _size: int = -1) -> bytes:
            return next(chunks, b"")

    digest, size, temp_path = asyncio.run(_receive_upload(UploadStub()))

    assert size == len(upload)
    assert temp_path.is_file()
    assert digest
    temp_path.unlink(missing_ok=True)
    with pytest.raises(OSError):
        os.fstat(captured_fd["fd"])


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


def test_failed_package_copy_does_not_block_retry(tmp_path: Path, monkeypatch) -> None:
    """包落盘失败时必须回收任务记录，同一包随后可以重试创建。"""
    setup_env(tmp_path, monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    real_copy = shutil.copyfile
    copy_calls = 0

    def fail_copy(source: Path, destination: Path) -> None:
        nonlocal copy_calls
        copy_calls += 1
        if copy_calls == 1:
            raise OSError("disk failure")
        real_copy(source, destination)

    monkeypatch.setattr("app.api.router.shutil.copyfile", fail_copy)
    with SAMPLE.open("rb") as package_file:
        failed = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", package_file, "application/zip")},
            data={"name": "落盘失败任务"},
        )

    assert failed.status_code == 500
    assert not task_service.exists("task-sample")

    with SAMPLE.open("rb") as package_file:
        retried = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", package_file, "application/zip")},
            data={"name": "落盘失败重试"},
        )

    assert retried.status_code == 202, retried.text
    task = wait_for_task(client, retried.json()["task_id"])
    assert task["status"] in ("completed", "failed")


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
