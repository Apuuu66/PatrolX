"""单规则重跑契约：只替换目标规则，无关结果保持不变。"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.baseline_helpers import (
    SAMPLE,
    load_rule,
    load_task,
    setup_env,
    upload_package,
    wait_for_task,
)

client = TestClient(app)


def test_local_single_rule_rerun_preserves_unrelated_results(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    task_id = "task-sample"
    run_task(SAMPLE, task_id=task_id)
    unrelated_before = load_rule(env, task_id, "kpi.threshold")
    task_before = load_task(env, task_id)
    assert load_rule(env, task_id, "alarm.stat")["status"] == "fail"

    run_single_rule("alarm.stat", package=SAMPLE, task_id=task_id)
    target = load_rule(env, task_id, "alarm.stat")
    unrelated_after = load_rule(env, task_id, "kpi.threshold")
    task_after = load_task(env, task_id)

    assert target["status"] == "fail"
    assert unrelated_after["executed_at"] == unrelated_before["executed_at"]
    assert unrelated_after["duration_ms"] == unrelated_before["duration_ms"]
    assert task_after["stats"] == task_before["stats"]
    assert (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8")


def test_online_single_rule_rerun_refreshes_summary_and_report(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client)
    wait_for_task(client, task_id)
    before = load_rule(env, task_id, "kpi.threshold")
    report_before = (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8")

    response = client.post(f"/api/v1/tasks/{task_id}/rerun", json={"rule_codes": ["kpi.threshold"]})
    assert response.status_code == 202, response.text
    wait_for_task(client, task_id)

    target = load_rule(env, task_id, "kpi.threshold")
    task = load_task(env, task_id)
    assert target["status"] == "fail"
    assert target["executed_at"] != before["executed_at"] or target["duration_ms"] != before["duration_ms"]
    assert task["stats"]["total"] == len(task["system"]["rules"])
    assert (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8") != report_before
