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
    unrelated_path = env.task_dir(task_id) / "rules" / "kpi.api.json"
    unrelated_before = load_rule(env, task_id, "kpi.api")
    task_before = load_task(env, task_id)
    unrelated_mtime_before = unrelated_path.stat().st_mtime_ns
    assert load_rule(env, task_id, "alarm.stat")["status"] == "fail"

    run_single_rule("alarm.stat", package=SAMPLE, task_id=task_id)
    target = load_rule(env, task_id, "alarm.stat")
    unrelated_after = load_rule(env, task_id, "kpi.api")
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
    before = load_rule(env, task_id, "kpi.api")
    unrelated_path = env.task_dir(task_id) / "rules" / "alarm.stat.json"
    unrelated_before = load_rule(env, task_id, "alarm.stat")
    unrelated_mtime_before = unrelated_path.stat().st_mtime_ns
    report_before = (env.task_dir(task_id) / "report.html").read_text(encoding="utf-8")

    response = client.post(f"/api/v2/tasks/{task_id}/rerun", json={"rule_codes": ["kpi.api"]})
    assert response.status_code == 202, response.text
    wait_for_task(client, task_id)

    target = load_rule(env, task_id, "kpi.api")
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
        archive.writestr(
            "kpi/kpi-api-15.csv",
            "API 统计\n测量周期,开始时间,结束时间,请求总数,成功数\n15,2026-09-01 10:00:00,2026-09-01 10:15:00,100,90\n",
        )
    task_id = run_task(package).task_id
    shutil.rmtree(env.task_dir(task_id))

    run_single_rule("kpi.api", package=package, task_id=task_id)

    assert (env.task_dir(task_id) / ".patrolx-extracted.json").is_file()
    assert load_rule(env, task_id, "kpi.api")["status"] != "skip"


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


def test_kpi_rules_rerun_without_prepare_and_deterministically(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task

    package = tmp_path / "kpi-rerun.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "kpi/kpi-api-15.csv",
            "API 统计\n测量周期,开始时间,结束时间,请求总数,成功数\n15,2026-09-01 10:00:00,2026-09-01 10:15:00,100,99\n",
        )
        archive.writestr(
            "kpi/kpi-media-15.csv",
            "媒体统计\n测量周期,开始时间,结束时间,媒体请求\n15,2026-09-01 10:00:00,2026-09-01 10:15:00,88\n",
        )
        call_content = (
            "呼叫会话统计\n"
            "测量周期,开始时间,结束时间,呼叫请求,请求成功,请求失败\n"
            "15,2026-09-01 10:00:00,2026-09-01 10:15:00,100,99,1\n"
        )
        archive.writestr("kpi/kpi-call-15.csv", call_content)
    task_id = run_task(package).task_id
    shutil.rmtree(env.task_dir(task_id) / "prepared", ignore_errors=True)

    kpi_codes = ("kpi.api", "kpi.media", "kpi.call")
    before = {code: load_rule(env, task_id, code) for code in kpi_codes}
    mtimes = {code: (env.rules_dir(task_id) / f"{code}.json").stat().st_mtime_ns for code in kpi_codes}
    for code in kpi_codes:
        run_single_rule(code, package=package, task_id=task_id)

        target = load_rule(env, task_id, code)
        assert target["status"] == "pass"
        assert {key: value for key, value in target.items() if key not in ("executed_at", "duration_ms")} == {
            key: value for key, value in before[code].items() if key not in ("executed_at", "duration_ms")
        }
        mtimes[code] = (env.rules_dir(task_id) / f"{code}.json").stat().st_mtime_ns
        for other in kpi_codes:
            if other == code:
                continue
            path = env.rules_dir(task_id) / f"{other}.json"
            assert path.stat().st_mtime_ns == mtimes[other]


def test_single_rule_rerun_reuses_valid_manifest(tmp_path: Path, monkeypatch) -> None:
    """manifest 与主包 checksum 一致时，单规则重跑不得重建解压现场。"""
    env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_single_rule, run_task
    from app.services import extraction

    package = tmp_path / "reuse-manifest.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "kpi/kpi-api-15.csv",
            "API 统计\n测量周期,开始时间,结束时间,请求总数,成功数\n15,2026-09-01 10:00:00,2026-09-01 10:15:00,100,90\n",
        )
    task_id = run_task(package).task_id
    before = {path.relative_to(env.task_dir(task_id)).as_posix() for path in env.task_dir(task_id).rglob("*")}

    def unexpected_extract(*args, **kwargs):
        raise AssertionError("manifest 有效时单规则重跑不应重建解压现场")

    monkeypatch.setattr(extraction, "extract_main_site", unexpected_extract)
    run_single_rule("kpi.api", package=package, task_id=task_id)

    after = {path.relative_to(env.task_dir(task_id)).as_posix() for path in env.task_dir(task_id).rglob("*")}
    assert load_rule(env, task_id, "kpi.api")["status"] == "pass"
    assert before == after
