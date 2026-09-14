"""质量门禁命令测试。"""

from __future__ import annotations

from pathlib import Path

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_lint_runs_check_and_format(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_lint(context) == 0
    python = str(build.venv_python(tmp_path))
    assert runner.commands() == [
        [python, "-m", "ruff", "check", "app", "tests"],
        [python, "-m", "ruff", "format", "--check", "app", "tests"],
    ]


def test_lint_failure_propagates(tmp_path: Path) -> None:
    context = make_context(tmp_path, FakeRunner(result=1))
    assert build.cmd_lint(context) == 1


def test_test_runs_pytest(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_test(context) == 0
    assert runner.commands() == [[str(build.venv_python(tmp_path)), "-m", "pytest"]]


def test_test_failure_propagates(tmp_path: Path) -> None:
    context = make_context(tmp_path, FakeRunner(result=2))
    assert build.cmd_test(context) == 2
