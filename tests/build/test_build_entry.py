"""build.py 入口调度测试。"""

from __future__ import annotations

import pytest

from tests.build.conftest import build  # noqa: E402


def test_command_registry_contains_all_workflows() -> None:
    expected = {
        "help",
        "install",
        "lock",
        "verify",
        "verify-one",
        "run",
        "contract",
        "gen-web-api",
        "test",
        "lint",
        "web-install",
        "web-dev",
        "web-build",
        "e2e-install",
        "e2e",
    }
    assert expected == set(build.COMMANDS)


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert build.main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in build.COMMANDS:
        assert command in output


def test_unknown_command_returns_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert build.main(["does-not-exist"]) == 2
    output = capsys.readouterr().err + capsys.readouterr().out
    assert "does-not-exist" in output
    assert "install" in output


def test_verify_one_requires_rule(capsys: pytest.CaptureFixture[str]) -> None:
    assert build.main(["verify-one"]) == 2
    output = capsys.readouterr().err
    assert "--rule" in output


def test_python_version_check(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(build, "python_version_ok", lambda: False)
    assert build.main(["test"]) == 1
    assert "Python 3.11" in capsys.readouterr().err
