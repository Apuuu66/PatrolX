"""单规则重跑入口映射测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_verify_one_requires_rule() -> None:
    assert build.main(["verify-one"]) == 2


def test_verify_one_maps_rule_to_cli(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_verify_one(context, rule="ABC_SERVICE") == 0
    expected = [
        str(build.venv_python(tmp_path)),
        "-m",
        "app.cli",
        "run-one",
        "--rule",
        "ABC_SERVICE",
    ]
    assert runner.commands() == [expected]


def test_verify_one_missing_venv_has_install_hint(tmp_path: Path) -> None:
    context = build.BuildContext(root=tmp_path, runner=FakeRunner())
    with pytest.raises(build.BuildError, match="python build.py install"):
        build.cmd_verify_one(context, rule="ABC_SERVICE")
