"""精确依赖锁维护测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def _report(path: Path) -> dict:
    return {
        "install": [
            {
                "metadata": {
                    "name": "fastapi",
                    "version": "1.2.3",
                    "requires_dist": ["starlette>=1.0; sys_platform == 'win32'"],
                }
            },
            {"metadata": {"name": "starlette", "version": "2.0.0"}},
        ]
    }


def test_lock_generates_exact_versions_and_markers(tmp_path: Path) -> None:
    def create_report(command: list[str], cwd: Path | None) -> None:
        assert "--dry-run" in command
        report_path = Path(command[command.index("--report") + 1])
        report_path.write_text(json.dumps(_report(report_path)), encoding="utf-8")

    runner = FakeRunner(callback=create_report)
    context = make_context(tmp_path, runner)
    assert build.cmd_lock(context) == 0
    content = (tmp_path / "requirements-lock.txt").read_text(encoding="utf-8")
    assert "fastapi==1.2.3" in content
    assert "starlette==2.0.0; sys_platform == 'win32'" in content
    assert all("--dry-run" in command for command in runner.commands())
    assert all("uv" not in command for command in runner.commands())


def test_lock_check_detects_non_exact_line(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    (tmp_path / "requirements-lock.txt").write_text("fastapi>=1.0\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="精确版本"):
        build.cmd_lock(context, check=True)


def test_lock_needs_virtualenv(tmp_path: Path) -> None:
    context = build.BuildContext(root=tmp_path, runner=FakeRunner())
    with pytest.raises(build.BuildError, match="python build.py install"):
        build.cmd_lock(context)
