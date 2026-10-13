"""US2：现场缺失时的错误语义（034 / T026）。

现场目录缺失 → 报告 / 日志 / 重跑 / 重建全部返回 410 ``scene_cleaned`` 且不进入队列；
任务不存在仍是 404 ``not_found``；输出目录存在但包缺失保持 409 ``package_missing``。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import Env, setup_env, upload_package, wait_for_task

client = TestClient(app)
REBUILD_BODY = {"mode": "full", "confirmed": True, "trigger_source": "api"}


def _completed_task(env: Env, name: str = "现场缺失") -> str:
    task_id = upload_package(env, client, name=name)
    wait_for_task(client, task_id)
    return task_id


def _remove_scene(env: Env, task_id: str) -> None:
    shutil.rmtree(env.task_dir(task_id))
    shutil.rmtree(env.uploads / task_id)


def _assert_scene_cleaned(response, hint: str) -> dict:
    assert response.status_code == 410, response.text
    body = response.json()
    assert body["code"] == "scene_cleaned"
    assert "现场" in body["message"]
    if hint:
        assert hint in body["message"]
    return body


def test_report_returns_scene_cleaned_after_scene_cleanup(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _completed_task(env)
    _remove_scene(env, task_id)

    response = client.get(f"/api/v2/tasks/{task_id}/report")

    body = _assert_scene_cleaned(response, "报告")
    assert "核心数据" in body["message"], "提示必须说明核心数据仍可查"


def test_logs_returns_scene_cleaned_after_scene_cleanup(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _completed_task(env)
    _remove_scene(env, task_id)

    response = client.get(f"/api/v2/tasks/{task_id}/logs")

    body = _assert_scene_cleaned(response, "日志")
    assert "不入库" in body["message"], "提示必须说明执行日志不入库"


def test_rerun_returns_scene_cleaned_and_does_not_queue(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _completed_task(env)
    _remove_scene(env, task_id)
    before = client.get(f"/api/v2/tasks/{task_id}").json()

    response = client.post(f"/api/v2/tasks/{task_id}/rerun", json={})

    body = _assert_scene_cleaned(response, "重新上传同名且校验和一致")
    assert body["detail"] is not None or body["message"]
    after = client.get(f"/api/v2/tasks/{task_id}").json()
    assert after["status"] == "completed", "拒绝重跑不得把任务改成排队/运行中"
    assert after["last_run_at"] == before["last_run_at"]
    assert after["duration_ms"] == before["duration_ms"]


def test_rebuild_returns_scene_cleaned_and_does_not_queue(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _completed_task(env)
    _remove_scene(env, task_id)
    before = client.get(f"/api/v2/tasks/{task_id}").json()

    response = client.post(f"/api/v2/tasks/{task_id}/rebuild", json=REBUILD_BODY)

    _assert_scene_cleaned(response, "重新上传同名且校验和一致")
    after = client.get(f"/api/v2/tasks/{task_id}").json()
    assert after["status"] == "completed"
    assert after["last_run_at"] == before["last_run_at"]


def test_unknown_task_still_returns_not_found() -> None:
    missing = "task-does-not-exist"

    assert client.get(f"/api/v2/tasks/{missing}/report").status_code == 404
    assert client.get(f"/api/v2/tasks/{missing}/logs").status_code == 404
    rerun = client.post(f"/api/v2/tasks/{missing}/rerun", json={})
    assert rerun.status_code == 404 and rerun.json()["code"] == "not_found"
    rebuild = client.post(f"/api/v2/tasks/{missing}/rebuild", json=REBUILD_BODY)
    assert rebuild.status_code == 404 and rebuild.json()["code"] == "not_found"


def test_output_dir_present_but_package_missing_keeps_409(monkeypatch, tmp_path: Path) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = _completed_task(env)
    shutil.rmtree(env.uploads / task_id)

    rerun = client.post(f"/api/v2/tasks/{task_id}/rerun", json={})
    assert rerun.status_code == 409, rerun.text
    assert rerun.json()["code"] == "package_missing"

    rebuild = client.post(f"/api/v2/tasks/{task_id}/rebuild", json=REBUILD_BODY)
    assert rebuild.status_code == 409, rebuild.text
    assert rebuild.json()["code"] == "package_missing"
