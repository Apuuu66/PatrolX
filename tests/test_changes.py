"""改动验证：统一任务 ID / API 读 output/ / 重复上传 / 单规则 SKIP 提示。"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli import generate_task_id, run_single_rule, run_task
from app.core.config import settings
from app.main import app

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample" / "sample.zip"
client = TestClient(app)


# ---- 统一任务 ID ----


def test_task_id_format() -> None:
    assert generate_task_id("sample.zip") == "task-sample"
    assert generate_task_id("ServiceLog_20260901.zip") == "task-servicelog_20260901"
    assert generate_task_id("ZZapp01BCN_app_Problem_scene_333.zip") == "task-zzapp01bcn_app_problem_scene_333"


def test_same_package_same_id_online_and_offline(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(settings, "output_dir", out)
    task = run_task(SAMPLE)
    assert task.task_id == generate_task_id(SAMPLE.name)
    assert (out / task.task_id / "task.json").exists()


# ---- API 读 output/（离线结果前端可见） ----


def test_offline_result_visible_via_api(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(settings, "output_dir", out)
    task = run_task(SAMPLE)

    resp = client.get(f"/api/v1/tasks/{task.task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task.task_id
    assert data["status"] == "completed"
    assert data["stats"]["pass"] >= 1


def test_offline_result_in_task_list(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(settings, "output_dir", out)
    task = run_task(SAMPLE)

    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {item["task_id"] for item in items}
    assert task.task_id in ids


# ---- 重复上传 ----


def test_duplicate_upload_returns_409() -> None:
    # 先上传一次
    with SAMPLE.open("rb") as fh:
        resp1 = client.post(
            "/api/v1/tasks",
            params={"force": "true"},
            files={"package_file": ("dup_test.zip", fh, "application/zip")},
        )
    assert resp1.status_code == 202

    # 再上传同一个包（不同名但同内容 → 同 ID）
    with SAMPLE.open("rb") as fh:
        resp2 = client.post(
            "/api/v1/tasks",
            files={"package_file": ("dup_test.zip", fh, "application/zip")},
        )
    assert resp2.status_code == 409
    assert resp2.json()["code"] == "duplicate_package"

    # force=true 覆盖
    with SAMPLE.open("rb") as fh:
        resp3 = client.post(
            "/api/v1/tasks",
            params={"force": "true"},
            files={"package_file": ("dup_test.zip", fh, "application/zip")},
        )
    assert resp3.status_code == 202

    # 清理
    client.delete(f"/api/v1/tasks/{resp3.json()['task_id']}")


# ---- 单规则 SKIP 提示 ----


def test_single_rule_skip_when_no_data(tmp_path: Path, monkeypatch) -> None:
    """没有解压产物时单规则应 SKIP 并提示数据未准备。"""
    out = tmp_path / "out"
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(settings, "output_dir", out)
    monkeypatch.setattr(settings, "uploads_dir", up)

    # 不跑全流程，直接跑单规则 → 应 SKIP（不回溯解压）
    run_single_rule("log.error_density", package=SAMPLE, task_id="task-skip-test")

    result_path = out / "task-skip-test" / "sample" / "rules" / "log.error_density.json"
    assert result_path.exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "skip"
    assert "数据未准备" in result.get("skip_reason", "") or "未发现" in result.get("skip_reason", "")


# ---- 在线重跑离线任务 ----


def test_rerun_offline_task_via_api(tmp_path: Path, monkeypatch) -> None:
    """离线跑完的任务，通过 API 重跑单条规则。"""
    out = tmp_path / "out"
    up = tmp_path / "uploads"
    up.mkdir()
    monkeypatch.setattr(settings, "output_dir", out)
    monkeypatch.setattr(settings, "uploads_dir", up)

    # 先跑全流程
    task = run_task(SAMPLE)
    task_id = task.task_id

    # 把原始包放到 uploads/<task_id>/ 模拟归档
    pkg_dir = up / task_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / SAMPLE.name).write_bytes(SAMPLE.read_bytes())

    # API 重跑
    resp = client.post(f"/api/v1/tasks/{task_id}/rerun", json={"rule_codes": ["log.error_density"]})
    assert resp.status_code == 202

    # 等待完成
    deadline = time.time() + 15
    while time.time() < deadline:
        t = client.get(f"/api/v1/tasks/{task_id}").json()
        if t["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert t["status"] == "completed"

    # 规则结果更新
    rule = client.get(f"/api/v1/tasks/{task_id}/rules/log.error_density").json()
    assert rule["code"] == "log.error_density"
