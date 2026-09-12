"""基线全流程测试：一个数据包生成一个独立任务现场。"""

import shutil
from pathlib import Path

from tests.baseline_helpers import SAMPLE, Env, load_rule, load_task, setup_env

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
