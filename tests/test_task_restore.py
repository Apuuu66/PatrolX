"""US2：现场已清理的任务可通过重传同名同校验和原始包恢复现场（034 / T025）。

契约口径（contracts/api-delta.md）：现场包缺失时与 ``tasks.package_checksum`` 比对，
一致则写回 ``uploads/<task_id>/<package_file>`` 并返回 202 + Location（不重跑、不改历史
数据、不触发留存清理）；不一致 409 ``package_checksum_conflict``；库无 checksum 且无
可读历史包时 409 并说明无法校验。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.checksum import sha256_file
from app.main import app
from app.models.db import TaskRecord, session_factory
from app.services import retention
from tests.baseline_helpers import SAMPLE, Env, setup_env, upload_package, wait_for_task

client = TestClient(app)


def _post_package(env: Env, package: Path, *, name: str = "恢复现场") -> object:
    with package.open("rb") as fh:
        return client.post(
            "/api/v3/tasks",
            files={"package_file": (package.name, fh, "application/zip")},
            data={
                "package_kind": "inspection",
                "name": name,
                "province": "北京",
                "operator": "移动",
            },
        )


def _remove_scene(env: Env, task_id: str) -> None:
    shutil.rmtree(env.task_dir(task_id))
    shutil.rmtree(env.uploads / task_id)


def _clear_checksum(task_id: str) -> None:
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        assert record is not None
        record.package_checksum = None
        session.commit()


def _task_snapshot(task_id: str) -> dict:
    response = client.get(f"/api/v2/tasks/{task_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_reupload_same_checksum_restores_scene_without_rerun(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="重传恢复")
    wait_for_task(client, task_id)
    before = _task_snapshot(task_id)
    original = (env.uploads / task_id / SAMPLE.name).read_bytes()

    _remove_scene(env, task_id)
    cleanup_calls: list[dict] = []
    monkeypatch.setattr(
        retention,
        "cleanup",
        lambda **kwargs: cleanup_calls.append(kwargs) or retention.CleanupResult(),
    )

    response = _post_package(env, SAMPLE, name="重传恢复")

    assert response.status_code == 202, response.text
    assert response.headers["location"] == f"/api/v3/tasks/{task_id}"
    restored = env.uploads / task_id / SAMPLE.name
    assert restored.read_bytes() == original, "必须写回原始包恢复现场"
    assert cleanup_calls == [], "恢复上传不触发留存清理"
    after = _task_snapshot(task_id)
    for field in ("status", "created_at", "completed_at", "last_run_at", "duration_ms"):
        assert after[field] == before[field], f"恢复不得改写任务历史字段 {field}"

    # 现场恢复后可直接发起重跑。
    assert client.post(f"/api/v2/tasks/{task_id}/rerun", json={}).status_code == 202
    wait_for_task(client, task_id)


def test_reupload_different_checksum_is_rejected(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="重传冲突")
    wait_for_task(client, task_id)
    _remove_scene(env, task_id)

    tampered = tmp_path / SAMPLE.name
    tampered.write_bytes(SAMPLE.read_bytes() + b"tampered")

    response = _post_package(env, tampered, name="重传冲突")

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "package_checksum_conflict"
    assert not (env.uploads / task_id).exists(), "校验失败不得写回现场"


def test_reupload_without_checksum_record_and_history_package_is_unverifiable(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="无法校验")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    _remove_scene(env, task_id)

    response = _post_package(env, SAMPLE, name="无法校验")

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "package_checksum_conflict"
    assert "无法校验" in body["message"]
    assert not (env.uploads / task_id).exists()


def test_reupload_backfills_checksum_from_readable_history_package(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="历史包回填")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    _remove_scene(env, task_id)
    legacy = env.uploads / SAMPLE.name
    shutil.copyfile(SAMPLE, legacy)

    response = _post_package(env, SAMPLE, name="历史包回填")

    assert response.status_code == 202, response.text
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum == sha256_file(SAMPLE), "以可读历史包 checksum 为准并回填库"
    assert (env.uploads / task_id / SAMPLE.name).read_bytes() == SAMPLE.read_bytes()


def _run_fields(task_id: str) -> tuple[object, object, str | None]:
    from app.services import task_db

    return task_db.get_run_fields(task_id)


def test_recovery_does_not_cleanup_and_scene_cleaned_blocks_rerun(monkeypatch, tmp_path: Path) -> None:
    """恢复前后边界：清理过的任务重跑必须先恢复现场给提示。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="恢复边界")
    wait_for_task(client, task_id)
    _remove_scene(env, task_id)

    blocked = client.post(f"/api/v2/tasks/{task_id}/rerun", json={})
    assert blocked.status_code == 410, blocked.text
    assert blocked.json()["code"] == "scene_cleaned"

    deadline = time.time() + 5
    while time.time() < deadline and client.get(f"/api/v2/tasks/{task_id}").json()["status"] == "pending":
        time.sleep(0.05)
    assert client.get(f"/api/v2/tasks/{task_id}").json()["status"] == "completed"
