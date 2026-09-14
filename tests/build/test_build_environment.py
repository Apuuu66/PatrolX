"""构建环境与虚拟环境行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def _venv_dir(tmp_path: Path) -> Path:
    return tmp_path / ".venv"


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
    (_venv_dir(tmp_path) / "pyvenv.cfg").write_text("uv = 0.12.10\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="uv"):
        build.cmd_install(context)


def test_backend_rejects_missing_install_marker(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (_venv_dir(tmp_path) / build.VENV_STATE_FILE).unlink()
    with pytest.raises(build.BuildError, match="缺少标准安装标记"):
        build.ensure_backend(context)


def test_backend_rejects_invalid_install_marker(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (_venv_dir(tmp_path) / build.VENV_STATE_FILE).write_text("{bad-json", encoding="utf-8")
    with pytest.raises(build.BuildError, match="标准安装标记无效"):
        build.ensure_backend(context)


def test_backend_rejects_stale_lock(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    state_path = _venv_dir(tmp_path) / build.VENV_STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["lock_sha256"] = "not-current"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(build.BuildError, match="当前锁文件或 Python 版本不匹配"):
        build.ensure_backend(context)


def test_backend_rejects_old_python(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (_venv_dir(tmp_path) / "pyvenv.cfg").write_text("version = 3.10.0\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="低于 3.11"):
        build.ensure_backend(context)


def test_install_repairs_missing_install_marker(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (_venv_dir(tmp_path) / build.VENV_STATE_FILE).unlink()
    (tmp_path / "requirements-lock.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    assert build.cmd_install(context) == 0
    assert (_venv_dir(tmp_path) / build.VENV_STATE_FILE).exists()


def test_python_version_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build.sys, "version_info", (3, 10, 0))
    assert build.python_version_ok() is False
    monkeypatch.setattr(build.sys, "version_info", (3, 11, 0))
    assert build.python_version_ok() is True
