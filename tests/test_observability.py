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
            "/api/v3/tasks",
            files={"package_file": ("observability_sample.zip", fh, "application/zip")},
            data={
                "package_kind": "inspection",
                "name": "可观测性",
                "province": "北京",
                "operator": "移动",
                "product": "UMF",
            },
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


def _zip(path: Path, files: dict[str, str | bytes]) -> Path:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def test_classification_audit_logs_include_task_and_path_context(tmp_path, monkeypatch) -> None:
    """分类审计日志必须携带任务、规则、源路径、忽略原因和稳定错误码。"""
    from tests.baseline_helpers import setup_env

    setup_env(tmp_path, monkeypatch)
    service_logs = _zip(
        tmp_path / "_build/ServiceLogs_observability.zip",
        {
            "UMFACC/logs/node-1/UMFAcc.log": "2026-09-01T10:00:00Z INFO ready\n",
            "Unmatched/notes.txt": "ignored\n",
        },
    )
    service_name = "UMF Problem Scene/Service Logs (Problem)/ServiceLogs_observability.zip"
    corrupt_name = "UMF Problem Scene/Performance Measurement Results/PerfResult_corrupt.zip"
    package = _zip(
        tmp_path / "uploads/classification-observability.zip",
        {
            "UMF Problem Scene/Basic Information About the UMF/system.ini": "[app]\nname=umf\n",
            service_name: service_logs.read_bytes(),
            corrupt_name: b"not-a-zip",
        },
    )

    from app.cli import run_task

    task = run_task(package, task_id="classification-observability", customer={"product": "UMF"})
    lines = [
        json.loads(line)
        for line in (settings.output / task.task_id / "execution.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    audit = next(item for item in lines if item["message"] == "classification_audit")
    assert audit["task_id"] == task.task_id
    assert audit["rule_code"] == "pkg.extract.classification"
    assert audit["counts"]["ignored"] >= 1
    assert audit["counts"]["failures"] == 1

    ignored = next(item for item in audit["ignored"] if item["member_relative"] == "Unmatched/notes.txt")
    assert ignored["source_relative"] == service_name
    assert ignored["reason"] == "member_not_selected"

    failure = audit["failures"][0]
    assert failure["source_relative"] == corrupt_name
    assert failure["error_code"] == "archive_corrupt"
