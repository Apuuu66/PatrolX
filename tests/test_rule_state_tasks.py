"""任务执行遵循任务开始时的规则启停集合。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.inspectors.registry import registry
from app.main import app
from app.services.rule_states import RuleStateError, ensure_rule_states, update_rule_state
from app.services.tasks import TaskRebuildError, task_service
from tests.baseline_helpers import setup_env, upload_package, wait_for_task


def _result_codes(env, task_id: str) -> set[str]:
    return {path.stem for path in (env.task_dir(task_id) / "rules").glob("*.json")}


def _system_rule_codes(env, task_id: str) -> set[str]:
    data = json.loads((env.task_dir(task_id) / "system.json").read_text(encoding="utf-8"))
    return {rule["code"] for rule in data["rules"]}


def _mtime_tree(root: Path) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_mtime_ns for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_disabled_rule_is_excluded_then_included_after_enable(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    sample_bytes = (Path(__file__).parent / "fixtures" / "sample" / "sample.zip").read_bytes()
    ensure_rule_states()
    update_rule_state("log.error_density", False)

    first_package = env.uploads / "sample-disabled.zip"
    first_package.write_bytes(sample_bytes)
    second_package = env.uploads / "sample-enabled.zip"
    second_package.write_bytes(sample_bytes)

    with TestClient(app) as client:
        disabled_task_id = upload_package(env, client, package=first_package, name="rule-state-disabled")
        wait_for_task(client, disabled_task_id)
        update_rule_state("log.error_density", True)
        enabled_task_id = upload_package(env, client, package=second_package, name="rule-state-enabled")
        wait_for_task(client, enabled_task_id)

    disabled_files = {path.name for path in (env.task_dir(disabled_task_id) / "rules").iterdir()}
    enabled_files = {path.name for path in (env.task_dir(enabled_task_id) / "rules").iterdir()}
    assert "log.error_density.json" not in disabled_files
    assert "log.error_density.json" in enabled_files
    assert "log.error_density" not in _system_rule_codes(env, disabled_task_id)
    assert "log.error_density" in _system_rule_codes(env, enabled_task_id)

    before = _mtime_tree(env.task_dir(disabled_task_id))
    update_rule_state("log.error_density", False)
    assert _mtime_tree(env.task_dir(disabled_task_id)) == before


def test_all_normal_rules_disabled_still_completes_with_empty_inspection(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    ensure_rule_states()
    for rule in registry.all(include_hidden=True):
        if not rule.hidden:
            update_rule_state(rule.code, False)

    with TestClient(app) as client:
        task_id = upload_package(env, client, name="rule-state-all-disabled")
        completed = wait_for_task(client, task_id)

    assert completed["status"] == "completed"
    assert completed["system"]["rules"] == []
    assert completed["stats"]["total"] == 0


def test_single_rule_and_incremental_rebuild_reject_disabled_rules(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    ensure_rule_states()
    update_rule_state("log.error_density", False)
    package = env.uploads / "rule-state-rejected.zip"
    package.write_bytes((Path(__file__).parent / "fixtures" / "sample" / "sample.zip").read_bytes())

    from app.cli import run_incremental_rebuild, run_single_rule

    with pytest.raises(RuleStateError, match="规则已停用"):
        run_single_rule("log.error_density", package=package, task_id="task-disabled-rerun")
    with pytest.raises(RuleStateError, match="规则已停用"):
        run_incremental_rebuild(
            ["log.error_density"],
            package=package,
            task_id="task-disabled-rebuild",
        )


def test_task_service_rerun_rejects_disabled_rule_without_output_change(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    ensure_rule_states()
    update_rule_state("log.error_density", False)
    package = env.uploads / "rule-state-rerun.zip"
    package.write_bytes((Path(__file__).parent / "fixtures" / "sample" / "sample.zip").read_bytes())

    with TestClient(app) as client:
        task_id = upload_package(env, client, package=package, name="rule-state-rerun")
        wait_for_task(client, task_id)

    before = _mtime_tree(env.task_dir(task_id))
    with pytest.raises(TaskRebuildError) as exc_info:
        task_service.rerun(task_id, ["log.error_density"])
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "rule_disabled"
    assert _mtime_tree(env.task_dir(task_id)) == before


def test_task_service_rebuild_rejects_disabled_rule(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    ensure_rule_states()
    update_rule_state("log.error_density", False)

    with TestClient(app) as client:
        task_id = upload_package(env, client, name="rule-state-rebuild")
        wait_for_task(client, task_id)

    from app.models.schemas import RebuildMode, RebuildRequest
    from app.services.tasks import TaskRebuildError

    with pytest.raises(TaskRebuildError, match="规则已停用"):
        task_service.rebuild(
            task_id,
            RebuildRequest(
                mode=RebuildMode.INCREMENTAL,
                confirmed=True,
                rule_codes=["log.error_density"],
            ),
        )
