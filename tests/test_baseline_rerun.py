"""单规则重跑契约：只替换目标规则，无关结果保持不变。"""

import shutil
import zipfile
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
    unrelated_path = env.task_dir(task_id) / "rules" / "kpi.threshold.json"
    unrelated_before = load_rule(env, task_id, "kpi.threshold")
    task_before = load_task(env, task_id)
    unrelated_mtime_before = unrelated_path.stat().st_mtime_ns
    assert load_rule(env, task_id, "alarm.stat")["status"] == "fail"

    run_single_rule("alarm.stat", package=SAMPLE, task_id=task_id)
    target = load_rule(env, task_id, "alarm.stat")
    unrelated_after = load_rule(env, task_id, "kpi.threshold")
    task_after = load_task(env, task_id)

    assert target["status"] == "fail"
    assert unrelated_after == unrelated_before
    assert unrelated_path.stat().st_mtime_ns == unrelated_mtime_before
    assert task_after["stats"] == task_before["stats"]
    assert (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8")


def test_online_single_rule_rerun_refreshes_summary_and_report(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = upload_package(env, client)
    wait_for_task(client, task_id)
    before = load_rule(env, task_id, "kpi.threshold")
    unrelated_path = env.task_dir(task_id) / "rules" / "alarm.stat.json"
    unrelated_before = load_rule(env, task_id, "alarm.stat")
    unrelated_mtime_before = unrelated_path.stat().st_mtime_ns
    report_before = (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8")

    response = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["kpi.threshold"]})
    assert response.status_code == 202, response.text
    wait_for_task(client, task_id)

    target = load_rule(env, task_id, "kpi.threshold")
    task = load_task(env, task_id)
    unrelated_after = load_rule(env, task_id, "alarm.stat")
    assert target["status"] == "fail"
    assert target["executed_at"] != before["executed_at"] or target["duration_ms"] != before["duration_ms"]
    assert unrelated_after == unrelated_before
    assert unrelated_path.stat().st_mtime_ns == unrelated_mtime_before
    assert task["stats"]["total"] == len(task["system"]["rules"])
    assert (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8") != report_before


def test_single_rule_rerun_rebuilds_missing_task_site(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    package = tmp_path / "missing-site.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("kpi/kpi.csv", "metric,value\ncall_success_rate,90\nattach_success_rate,96.5\n")
    task_id = run_task(package).task_id
    shutil.rmtree(env.task_dir(task_id))

    run_single_rule("kpi.threshold", package=package, task_id=task_id)

    assert (env.task_dir(task_id) / ".patrolx-extracted.json").is_file()
    assert load_rule(env, task_id, "kpi.threshold")["status"] != "skip"


def test_single_rule_rerun_reports_skip_for_unmatched_sources(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    package = tmp_path / "no-config.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("logs/app.log", "2026-01-01 INFO ready\n")
    task_id = run_task(package).task_id

    run_single_rule("config.check", package=package, task_id=task_id)

    target = load_rule(env, task_id, "config.check")
    assert target["status"] == "skip"
    assert target["skip_reason"] == "source_patterns 未匹配到文件: ^config/.*$"
