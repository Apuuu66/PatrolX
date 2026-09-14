"""本地全流程入口映射测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_verify_runs_main_with_venv_python(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_verify(context) == 0
    assert runner.commands() == [[str(build.venv_python(tmp_path)), "main.py"]]


def test_verify_missing_venv_has_install_hint(tmp_path: Path) -> None:
    context = build.BuildContext(root=tmp_path, runner=FakeRunner())
    with pytest.raises(build.BuildError, match="python build.py install"):
        build.cmd_verify(context)
