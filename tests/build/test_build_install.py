"""install 精确安装流程测试。"""

from __future__ import annotations

from pathlib import Path

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_install_creates_venv_and_uses_exact_lock(tmp_path: Path) -> None:
    (tmp_path / "requirements-lock.txt").write_text("pytest==9.1.1\n", encoding="utf-8")

    def create_venv(command: list[str], cwd: Path | None) -> None:
        (tmp_path / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".venv" / "pyvenv.cfg").write_text("version = 3.12.0\n", encoding="utf-8")

    runner = FakeRunner(callback=create_venv)
    context = build.BuildContext(root=tmp_path, runner=runner)
    assert build.cmd_install(context) == 0
    commands = runner.commands()
    assert commands[0] == [build.sys.executable, "-m", "venv", str(tmp_path / ".venv")]
    normalized = [Path(item) if item.startswith(str(tmp_path)) else item for item in commands[1]]
    assert normalized[:1] == [tmp_path / ".venv" / build.VENV_REL_PYTHON]
    assert normalized[1:5] == ["-m", "pip", "install", "--disable-pip-version-check"]
    assert normalized[5:7] == ["-r", tmp_path / "requirements-lock.txt"]
    assert commands[2][-3:] == ["--no-deps", "-e", "."]
    assert all("shell" not in command for command in commands)


def test_install_reuses_venv(tmp_path: Path) -> None:
    (tmp_path / "requirements-lock.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_install(context) == 0
    assert ["-m", "venv"] not in runner.commands()[0]
