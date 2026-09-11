"""CLI 无子命令入口回归测试。"""

from pathlib import Path

from app import cli


def test_main_without_subcommand_uses_default_task_id(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []

    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main([]) == 0
    assert calls == [(packages[0], {"task_id": None})]


def test_main_run_subcommand_accepts_task_id(monkeypatch) -> None:
    packages = [Path("sample.zip")]
    calls = []

    monkeypatch.setattr(cli, "find_packages", lambda root=None: packages)
    monkeypatch.setattr(cli, "run_task", lambda package, **kwargs: calls.append((package, kwargs)))

    assert cli.main(["run", "--task-id", "task-sample"]) == 0
    assert calls == [(packages[0], {"task_id": "task-sample"})]
