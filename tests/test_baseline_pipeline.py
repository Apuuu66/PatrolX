"""基线全流程测试：一个数据包生成一个独立任务现场。"""

import shutil
from pathlib import Path

from tests.baseline_helpers import SAMPLE, Env, load_logs, load_rule, load_task, setup_env

NORMAL_RULES = (
    "log.filter",
    "alarm.stat",
    "config.check",
    "kpi.threshold",
    "log.error_density",
    "resource.check",
    "traffic.stat",
)


def test_single_package_creates_single_task_site(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, name="基线任务", customer={"province": "北京"}, version="v1")
    task_dir = env.task_dir(task.task_id)

    assert task.task_id == "task-sample"
    for name in ("task.json", "system.json", "report.html", "execution.log", ".patrolx-extracted.json"):
        assert (task_dir / name).is_file(), f"缺少 {name}"
    for category in ("logs", "kpi", "traffic", "alarm", "config", "resource", "other"):
        assert (task_dir / category).is_dir()
    for code in NORMAL_RULES:
        assert (task_dir / "rules" / f"{code}.json").is_file()
        assert load_rule(env, task.task_id, code)["code"] == code
    assert load_task(env, task.task_id)["task_id"] == task.task_id
    assert task.stats.total == len(task.system.rules)
    assert task.stats.total == task.system.summary.total
    assert not (task_dir / "artifacts").exists()


def test_package_name_derives_isolated_task_ids(tmp_path: Path, monkeypatch) -> None:
    env: Env = setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    first_package = env.uploads / "package-a.zip"
    second_package = env.uploads / "package-b.zip"
    shutil.copyfile(SAMPLE, first_package)
    shutil.copyfile(SAMPLE, second_package)
    metadata = {"customer": {"province": "北京"}, "version": "v1"}

    first = run_task(first_package, name="相同系统", task_id=None, **metadata)
    second = run_task(second_package, name="相同系统", task_id=None, **metadata)

    assert first.task_id == "task-package_a"
    assert second.task_id == "task-package_b"
    for task_id in (first.task_id, second.task_id):
        assert (env.task_dir(task_id) / "system.json").is_file()
        assert (env.task_dir(task_id) / "rules" / "alarm.stat.json").is_file()
    assert first.system.rules != second.system.rules
    assert env.task_dir(first.task_id) != env.task_dir(second.task_id)


def test_same_name_reuses_site_and_checksum_conflict_is_rejected(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.baseline_helpers import wait_for_task

    env = setup_env(tmp_path, monkeypatch)
    client = TestClient(app)
    with SAMPLE.open("rb") as fh:
        first = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", fh, "application/zip")},
            data={"name": "同名校验"},
        )
    assert first.status_code == 202, first.text
    task_id = first.json()["task_id"]
    wait_for_task(client, task_id)
    task_dir = env.task_dir(task_id)
    before = {(p.relative_to(task_dir), p.stat().st_mtime_ns) for p in task_dir.rglob("*") if p.is_file()}

    with SAMPLE.open("rb") as fh:
        reuse = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", fh, "application/zip")},
            data={"name": "同名校验"},
        )
    assert reuse.status_code == 202, reuse.text
    assert reuse.json()["task_id"] == task_id
    after_reuse = {(p.relative_to(task_dir), p.stat().st_mtime_ns) for p in task_dir.rglob("*") if p.is_file()}
    assert after_reuse == before

    conflict_package = env.uploads / "different-content.zip"
    conflict_package.write_bytes(b"different package content")
    with conflict_package.open("rb") as fh:
        conflict = client.post(
            "/api/v2/tasks",
            files={"package_file": ("sample.zip", fh, "application/zip")},
        )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "package_checksum_conflict"
    after_conflict = {(p.relative_to(task_dir), p.stat().st_mtime_ns) for p in task_dir.rglob("*") if p.is_file()}
    assert after_conflict == before


def test_rule_exception_becomes_error_and_task_completes(tmp_path: Path, monkeypatch) -> None:
    from app.cli import run_task
    from app.inspectors.base import Inspector
    from app.inspectors.registry import registry
    from app.models.schemas import Priority, RuleCategory, Severity

    env = setup_env(tmp_path, monkeypatch)

    def raise_runtime_error(_ctx) -> None:
        raise RuntimeError("注入的运行时异常")

    rule = Inspector(
        code="test.runtime_error",
        name="运行时异常样例",
        category=RuleCategory.OTHER,
        severity=Severity.LOW,
        priority=Priority.P1,
        rule_version="2.0.0",
        description="测试规则运行时异常",
        recommendation="检查测试规则",
        source_patterns=[".*"],
        run=raise_runtime_error,
    )
    monkeypatch.setitem(registry._rules, rule.code, rule)

    task = run_task(SAMPLE, task_id="task-sample")
    result = load_rule(env, task.task_id, rule.code)
    logs = load_logs(env, task.task_id)

    assert task.status == "completed"
    assert result["status"] == "error"
    assert result["metrics"] == []
    assert result["findings"] == []
    assert any(
        entry.get("rule_code") == rule.code
        and entry.get("task_id") == task.task_id
        and "注入的运行时异常" in entry.get("error", "")
        for entry in logs
    )
    assert load_rule(env, task.task_id, "log.error_density")["status"] in {"pass", "warn", "fail"}
