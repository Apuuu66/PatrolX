"""US2：现场已清理的任务可通过重传同名同校验和原始包恢复现场（034 / T025）。

契约口径（contracts/api-delta.md）：现场包缺失时与 ``tasks.package_checksum`` 比对，
一致则写回 ``uploads/<task_id>/<package_file>`` 并返回 202 + Location（不重跑、不改历史
数据、不触发留存清理）；不一致 409 ``package_checksum_conflict``；库无 checksum 且无
可读历史包时 409 并说明无法校验。
"""

from __future__ import annotations

import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import router as api_router
from app.core.checksum import sha256_file
from app.main import app
from app.models.db import TaskRecord, session_factory
from app.models.schemas import PackageKind
from app.services import retention, task_db
from tests.baseline_helpers import SAMPLE, Env, setup_env, upload_package, wait_for_task

client = TestClient(app)


def _post_package(
    env: Env,
    package: Path,
    *,
    name: str = "恢复现场",
    package_kind: str = "inspection",
    province: str | None = "北京",
    operator: str | None = "移动",
    product: str | None = "UMF",
    http_client: TestClient | None = None,
) -> object:
    data = {"package_kind": package_kind, "name": name}
    if province is not None:
        data["province"] = province
    if operator is not None:
        data["operator"] = operator
    if product is not None:
        data["product"] = product
    with package.open("rb") as fh:
        return (http_client or client).post(
            "/api/v3/tasks",
            files={"package_file": (package.name, fh, "application/zip")},
            data=data,
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


@contextmanager
def _session_with_record(record: object):
    yield SimpleNamespace(get=lambda *_args: record)


def _assert_checksum_conflict(response: object) -> None:
    assert response.status_code == 409, response.text
    body = response.json()
    assert set(body) == {"code", "message", "detail"}, body
    assert body["code"] == "package_checksum_conflict", body
    assert body["message"], body


def test_reupload_same_checksum_restores_scene_without_rerun(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="重传恢复", product="UMF")
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
    task_id = upload_package(env, client, name="重传冲突", product="UMF")
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
    task_id = upload_package(env, client, name="无法校验", product="UMF")
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
    task_id = upload_package(env, client, name="历史包回填", product="UMF")
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


def test_reupload_backfills_checksum_from_readable_existing_scene(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="现场回填", product="UMF")
    wait_for_task(client, task_id)
    before = _task_snapshot(task_id)
    scene_package = env.uploads / task_id / SAMPLE.name
    original = scene_package.read_bytes()
    _clear_checksum(task_id)

    response = _post_package(env, SAMPLE, name="现场回填")

    assert response.status_code == 202, response.text
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum == sha256_file(SAMPLE), "可读且未篡改的现场包必须回填首次接收 checksum"
    assert scene_package.read_bytes() == original, "正向回填不得覆盖或改写现场包"
    after = _task_snapshot(task_id)
    for field in ("status", "created_at", "completed_at", "last_run_at", "duration_ms"):
        assert after[field] == before[field], f"正向回填不得自动重跑或改写历史字段 {field}"


def test_checksum_backfill_unreadable_existing_scene_returns_structured_conflict(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="现场不可读", product="UMF")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    scene_package = env.uploads / task_id / SAMPLE.name
    original = scene_package.read_bytes()

    def unreadable(_path: Path) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(api_router, "sha256_file", unreadable)
    unreadable_client = TestClient(app, raise_server_exceptions=False)
    response = _post_package(env, SAMPLE, name="现场不可读", http_client=unreadable_client)

    _assert_checksum_conflict(response)
    assert scene_package.read_bytes() == original, "不可读现场不得被覆盖"
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum is None


def test_checksum_backfill_unreadable_legacy_package_returns_structured_conflict(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="历史包不可读", product="UMF")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    _remove_scene(env, task_id)
    legacy_package = env.uploads / SAMPLE.name
    original = SAMPLE.read_bytes()
    legacy_package.write_bytes(original)

    def unreadable(_path: Path) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(api_router, "sha256_file", unreadable)
    unreadable_client = TestClient(app, raise_server_exceptions=False)
    response = _post_package(env, SAMPLE, name="历史包不可读", http_client=unreadable_client)

    _assert_checksum_conflict(response)
    assert legacy_package.read_bytes() == original, "不可读历史包不得被覆盖"
    assert not (env.uploads / task_id).exists(), "不可读历史包不得恢复任务现场"
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum is None


def test_checksum_backfill_rejects_tampered_existing_scene_without_persisting_it(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="现场篡改", product="UMF")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    scene_package = env.uploads / task_id / SAMPLE.name
    tampered = SAMPLE.read_bytes() + b"tampered-scene"
    scene_package.write_bytes(tampered)

    response = _post_package(env, SAMPLE, name="现场篡改")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "package_checksum_conflict"
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum is None, "与上传包不一致的历史现场不得污染首次接收 checksum"
    assert scene_package.read_bytes() == tampered, "冲突时不得信任或覆盖既有现场包"


def test_checksum_backfill_rejects_tampered_legacy_package_without_persisting_it(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="历史篡改", product="UMF")
    wait_for_task(client, task_id)
    _clear_checksum(task_id)
    _remove_scene(env, task_id)
    legacy_package = env.uploads / SAMPLE.name
    tampered = SAMPLE.read_bytes() + b"tampered-legacy"
    legacy_package.write_bytes(tampered)

    response = _post_package(env, SAMPLE, name="历史篡改")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "package_checksum_conflict"
    _, _, stored_checksum = _run_fields(task_id)
    assert stored_checksum is None, "与上传包不一致的历史顶层包不得污染首次接收 checksum"
    assert legacy_package.read_bytes() == tampered, "冲突时不得信任或覆盖历史顶层包"
    assert not (env.uploads / task_id).exists(), "校验失败不得恢复任务现场"


def test_historical_inspection_without_product_returns_product_conflict(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="历史缺网元", product="UMF")
    wait_for_task(client, task_id)
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        assert record is not None
        customer = dict(record.customer or {})
        customer.pop("product", None)
        record.customer = customer
        session.commit()

    response = _post_package(env, SAMPLE, name="历史缺网元", product="UMF")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "package_product_conflict"
    assert response.json()["detail"]["existing"] is None


def test_task_identity_falls_back_to_inspection_for_missing_or_invalid_kind(monkeypatch) -> None:
    records = (
        SimpleNamespace(customer={"product": " umf "}),
        SimpleNamespace(package_kind="not-a-kind", customer={"product": " csp "}),
    )

    for record in records:
        monkeypatch.setattr(task_db, "session_factory", lambda record=record: _session_with_record(record))
        identity = task_db.get_task_identity("historical-task")
        assert identity is not None
        assert identity.package_kind is PackageKind.INSPECTION

    assert records[0].customer == {"product": " umf "}
    assert records[1].customer == {"product": " csp "}


def _run_fields(task_id: str) -> tuple[object, object, str | None]:
    from app.services import task_db

    return task_db.get_run_fields(task_id)


def test_recovery_does_not_cleanup_and_scene_cleaned_blocks_rerun(monkeypatch, tmp_path: Path) -> None:
    """恢复前后边界：清理过的任务重跑必须先恢复现场给提示。"""
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="恢复边界", product="UMF")
    wait_for_task(client, task_id)
    _remove_scene(env, task_id)

    blocked = client.post(f"/api/v2/tasks/{task_id}/rerun", json={})
    assert blocked.status_code == 410, blocked.text
    assert blocked.json()["code"] == "scene_cleaned"

    deadline = time.time() + 5
    while time.time() < deadline and client.get(f"/api/v2/tasks/{task_id}").json()["status"] == "pending":
        time.sleep(0.05)
    assert client.get(f"/api/v2/tasks/{task_id}").json()["status"] == "completed"


def test_reupload_after_scene_cleanup_checks_kind_and_product_before_restore(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client, name="清理后冲突", product="UMF")
    wait_for_task(client, task_id)
    before = _task_snapshot(task_id)
    _remove_scene(env, task_id)

    kind_conflict = _post_package(
        env,
        SAMPLE,
        name="清理后冲突",
        package_kind="log_supplement",
        province=None,
        operator=None,
        product=None,
    )
    assert kind_conflict.status_code == 409, kind_conflict.text
    assert kind_conflict.json()["code"] == "package_kind_conflict"
    assert not (env.uploads / task_id).exists(), "包类型冲突不得恢复现场"

    product_conflict = _post_package(env, SAMPLE, name="清理后冲突", product="CSP")
    assert product_conflict.status_code == 409, product_conflict.text
    assert product_conflict.json()["code"] == "package_product_conflict"
    assert not (env.uploads / task_id).exists(), "网元类型冲突不得恢复现场"

    restored = _post_package(env, SAMPLE, name="清理后冲突", product=" umf ")
    assert restored.status_code == 202, restored.text
    assert restored.headers["location"] == f"/api/v3/tasks/{task_id}"
    assert (env.uploads / task_id / SAMPLE.name).read_bytes() == SAMPLE.read_bytes()

    after = _task_snapshot(task_id)
    for field in ("status", "created_at", "completed_at", "last_run_at", "duration_ms"):
        assert after[field] == before[field], f"恢复不得自动重跑或改写历史字段 {field}"


def test_log_supplement_reupload_is_idempotent_and_restores_only_package(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    first = _post_package(
        env,
        SAMPLE,
        name="日志补充恢复",
        package_kind="log_supplement",
        province=None,
        operator=None,
        product=None,
    )
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    wait_for_task(client, task_id)
    before = _task_snapshot(task_id)
    _remove_scene(env, task_id)

    restored = _post_package(
        env,
        SAMPLE,
        name="日志补充恢复",
        package_kind="log_supplement",
        province=None,
        operator=None,
        product=None,
    )

    assert restored.status_code == 202, restored.text
    assert restored.json()["task_id"] == task_id
    assert restored.headers["location"] == f"/api/v3/tasks/{task_id}"
    assert (env.uploads / task_id / SAMPLE.name).read_bytes() == SAMPLE.read_bytes()
    assert not env.task_dir(task_id).exists(), "恢复只写回上传包，不得伪造运行现场或自动重跑"
    after = _task_snapshot(task_id)
    for field in ("status", "created_at", "completed_at", "last_run_at", "duration_ms"):
        assert after[field] == before[field], f"日志补充包恢复不得改写历史字段 {field}"
