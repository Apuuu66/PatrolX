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


def _policy_zip(path: Path, files: dict[str, str | bytes]) -> Path:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def _configure_policy(tmp_path: Path, monkeypatch) -> None:
    import shutil

    import yaml

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "deploy/config/classify_rules.yaml",
        config_dir / "classify_rules.yaml",
    )
    (config_dir / "extract_policy.yaml").write_text(
        yaml.safe_dump(
            {
                "nested": {"skip_paths": ["/skip/"]},
                "whitelist": {"name_keywords": ["alarm"]},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "config_dir", config_dir)


def test_policy_extraction_logs_include_task_and_path_context(tmp_path, monkeypatch) -> None:
    """策略保留、白名单恢复、普通文件命中和目标冲突都有可审计日志。"""
    from tests.baseline_helpers import setup_env

    setup_env(tmp_path, monkeypatch)
    _configure_policy(tmp_path, monkeypatch)

    alarm_inner = _policy_zip(tmp_path / "_build/alarm-inner.zip", {"inner.txt": "alarm"})
    conflict_inner = _policy_zip(
        tmp_path / "_build/conflict.zip",
        {
            "conflict.log": "plain log",
            "conflict.log.gz": b"not-real-gzip",
        },
    )
    package = _policy_zip(
        tmp_path / "uploads/policy-observability.zip",
        {
            "skip/normal.zip": _policy_zip(tmp_path / "_build/normal.zip", {"normal": "normal"}).read_bytes(),
            "skip/service_ALARM.zip": _policy_zip(
                tmp_path / "_build/alarm-outer.zip", {"inner.zip": alarm_inner.read_bytes()}
            ).read_bytes(),
            "skip/alarm.txt": "alarm",
            "alarm/conflict.zip": conflict_inner.read_bytes(),
        },
    )

    from app.cli import run_task

    task = run_task(package, task_id="policy-observability")
    lines = [
        json.loads(line)
        for line in (settings.output / task.task_id / "execution.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    skipped = next(item for item in lines if item["message"] == "压缩项按策略保留")
    assert skipped["task_id"] == task.task_id
    assert skipped["source"] == "skip/normal.zip"
    assert skipped["target"] == "other/skip/normal.zip"

    restored = next(
        item for item in lines if item["message"] == "压缩项按白名单恢复" and item["source"] == "skip/service_ALARM.zip"
    )
    assert restored["task_id"] == task.task_id
    assert restored["source"] == "skip/service_ALARM.zip"
    assert restored["target"] == "logs"
    assert restored["keyword"] == "alarm"

    hit = next(item for item in lines if item["message"] == "extract.policy.whitelist")
    assert hit["task_id"] == task.task_id
    assert hit["source"] == "skip/alarm.txt"
    assert hit["target"] == "alarm/alarm.txt"

    conflict = next(item for item in lines if item["message"] == "日志 gzip 目标冲突")
    assert conflict["task_id"] == task.task_id
    assert conflict["source"] == "conflict.log.gz"
    assert conflict["target"] == "logs/conflict.log"
