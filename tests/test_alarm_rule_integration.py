"""告警双规则在本地、在线与单规则重跑路径上的一致性验收。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.inspectors.registry import registry
from app.main import app
from tests.baseline_helpers import (
    load_rule,
    setup_env,
    strip_volatile,
    upload_package,
    wait_for_task,
)
from tests.fixtures.make_real_package import build_real_package

client = TestClient(app)
ALARM_RULES = ("alarm.active_state", "alarm.recurrence")
METADATA_NAMESPACE = {
    "alarm.active_state": "alarm_active",
    "alarm.recurrence": "alarm_recurrence",
}


def _semantic(rule: dict[str, Any]) -> dict[str, Any]:
    """只比较规则判定语义，剔除每次执行自然变化的运行态字段。"""
    value = strip_volatile(rule)
    value.pop("execution_order", None)
    return value


def _assert_alarm_contract(rule: dict[str, Any], code: str) -> None:
    assert rule["code"] == code
    assert rule["status"] == "fail"
    assert rule["metrics"]
    assert rule["findings"]
    namespace = METADATA_NAMESPACE[code]
    metadata = rule["metadata"][namespace]
    assert metadata["coverage"]["end_at"]
    assert metadata["coverage"]["end_basis"] == "max_valid_alarm_timestamp"
    assert metadata["coverage"]["observation_note"] == "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻"
    assert metadata["totals"]["failed_files"] == 1
    assert all(
        Path(item["source_file"]).parent.as_posix() == "alarm"
        for item in metadata["files"]
        if item["status"] == "matched"
    )


def _assert_alarm_rules_have_no_prepare(env, task_id: str) -> None:
    registry.load_all()
    for code in ALARM_RULES:
        assert registry.prepare_for_owner(code) is None
        assert not (env.task_dir(task_id) / "prepared" / code).exists()


def _add_uncatalogued_file(env, task_id: str) -> None:
    """加入不在 catalog 中的无关文件，验证扫描与规则结果只依赖源文件匹配。"""
    path = env.task_dir(task_id) / "other" / "alarm-integration-unrelated.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not an alarm source\n", encoding="utf-8")


def test_local_alarm_rules_survive_single_rule_reruns_and_unrelated_changes(tmp_path: Path, monkeypatch) -> None:
    env = setup_env(tmp_path / "local", monkeypatch)
    from app.cli import run_single_rule, run_task

    package = build_real_package(tmp_path / "fixtures")
    task = run_task(
        package,
        task_id="task-alarm-integration-local",
        name="告警规则本地集成",
        customer={"province": "江苏", "operator": "移动", "product": "UMF"},
    )

    initial = {code: load_rule(env, task.task_id, code) for code in ALARM_RULES}
    for code in ALARM_RULES:
        _assert_alarm_contract(initial[code], code)
    _assert_alarm_rules_have_no_prepare(env, task.task_id)

    manifest = json.loads((env.task_dir(task.task_id) / "manifest.json").read_text(encoding="utf-8"))
    catalog_alarm_paths = {item["path"] for item in manifest["catalog"] if item["path"].startswith("alarm/")}
    assert catalog_alarm_paths
    assert not any(path.startswith("alarm/alarm_history_202609010101137101.zip/") for path in catalog_alarm_paths)

    _add_uncatalogued_file(env, task.task_id)
    recurrence_path = env.rules_dir(task.task_id) / "alarm.recurrence.json"
    recurrence_path.unlink()

    run_single_rule(
        "alarm.active_state",
        package=package,
        task_id=task.task_id,
        product="UMF",
        trigger_retention=False,
    )
    active_after = load_rule(env, task.task_id, "alarm.active_state")
    assert _semantic(active_after) == _semantic(initial["alarm.active_state"])
    assert not recurrence_path.exists(), "重跑活动告警规则不得补写另一条告警规则"
    _assert_alarm_contract(active_after, "alarm.active_state")

    active_bytes = (env.rules_dir(task.task_id) / "alarm.active_state.json").read_bytes()
    run_single_rule(
        "alarm.recurrence",
        package=package,
        task_id=task.task_id,
        product="UMF",
        trigger_retention=False,
    )
    recurrence_after = load_rule(env, task.task_id, "alarm.recurrence")
    assert _semantic(recurrence_after) == _semantic(initial["alarm.recurrence"])
    assert (env.rules_dir(task.task_id) / "alarm.active_state.json").read_bytes() == active_bytes
    assert not any((env.task_dir(task.task_id) / "prepared").glob("alarm.*"))
    _assert_alarm_contract(recurrence_after, "alarm.recurrence")


def test_online_alarm_rules_match_local_and_rerun_independently(tmp_path: Path, monkeypatch) -> None:
    package = build_real_package(tmp_path / "fixtures")

    local_env = setup_env(tmp_path / "local", monkeypatch)
    from app.cli import run_task

    local_task = run_task(
        package,
        task_id="task-alarm-contract-local",
        name="告警规则一致性",
        customer={"province": "江苏", "operator": "移动", "product": "UMF"},
    )
    local_rules = {code: load_rule(local_env, local_task.task_id, code) for code in ALARM_RULES}

    online_env = setup_env(tmp_path / "online", monkeypatch)
    online_task_id = upload_package(
        online_env,
        client,
        package=package,
        name="告警规则一致性",
        province="江苏",
        operator="移动",
        product="UMF",
    )
    wait_for_task(client, online_task_id)
    _assert_alarm_rules_have_no_prepare(online_env, online_task_id)

    online_rules = {code: load_rule(online_env, online_task_id, code) for code in ALARM_RULES}
    for code in ALARM_RULES:
        _assert_alarm_contract(online_rules[code], code)
        assert _semantic(online_rules[code]) == _semantic(local_rules[code])

        detail = client.get(f"/api/v2/tasks/{online_task_id}/rules/{code}")
        assert detail.status_code == 200, detail.text
        assert _semantic(detail.json()) == _semantic(online_rules[code])

    _add_uncatalogued_file(online_env, online_task_id)
    for code in ALARM_RULES:
        untouched = next(item for item in ALARM_RULES if item != code)
        untouched_bytes = (online_env.rules_dir(online_task_id) / f"{untouched}.json").read_bytes()
        response = client.post(
            f"/api/v2/tasks/{online_task_id}/rerun",
            json={"rule_codes": [code]},
        )
        assert response.status_code == 202, response.text
        wait_for_task(client, online_task_id)

        rerun_rule = load_rule(online_env, online_task_id, code)
        assert _semantic(rerun_rule) == _semantic(online_rules[code])
        assert (online_env.rules_dir(online_task_id) / f"{untouched}.json").read_bytes() == untouched_bytes
        _assert_alarm_contract(rerun_rule, code)
