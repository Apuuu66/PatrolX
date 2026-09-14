"""构建环境与虚拟环境行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_venv_python_platform_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build, "IS_WINDOWS", True)
    assert build.venv_python(tmp_path) == tmp_path / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(build, "IS_WINDOWS", False)
    assert build.venv_python(tmp_path) == tmp_path / ".venv" / "bin" / "python"


def test_backend_command_requires_virtualenv(tmp_path: Path) -> None:
    context = build.BuildContext(root=tmp_path, runner=FakeRunner())
    with pytest.raises(build.BuildError, match="python build.py install"):
        build.ensure_backend(context)


def test_install_requires_lock(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    with pytest.raises(build.BuildError, match="requirements-lock.txt"):
        build.cmd_install(context)


def test_uv_virtualenv_is_rejected(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("uv = 0.12.10\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="uv"):
        build.cmd_install(context)


def test_python_version_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build.sys, "version_info", (3, 10, 0))
    assert build.python_version_ok() is False
    monkeypatch.setattr(build.sys, "version_info", (3, 11, 0))
    assert build.python_version_ok() is True
