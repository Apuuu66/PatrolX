"""在线启动命令测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_run_maps_existing_launcher(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_run(context) == 0
    assert runner.commands() == [[str(build.venv_python(tmp_path)), "run_online.py"]]


def test_run_requires_backend_environment(tmp_path: Path) -> None:
    context = build.BuildContext(root=tmp_path, runner=FakeRunner())
    with pytest.raises(build.BuildError, match="python build.py install"):
        build.cmd_run(context)
