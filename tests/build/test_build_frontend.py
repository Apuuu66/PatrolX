"""前端与端到端命令测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_find_node_tool_prefers_windows_cmd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build, "IS_WINDOWS", True)
    monkeypatch.setattr(build.shutil, "which", lambda name: f"/tools/{name}" if name == "npm.cmd" else None)
    assert build.find_node_tool("npm") == "/tools/npm.cmd"


def test_web_commands_use_argument_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build, "find_node_tool", lambda name: name)
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_web_install(context) == 0
    assert build.cmd_web_dev(context) == 0
    assert build.cmd_web_build(context) == 0
    assert build.cmd_e2e(context) == 0
    assert runner.commands() == [
        ["npm", "install"],
        ["npm", "run", "dev"],
        ["npm", "run", "build"],
        ["npm", "run", "e2e"],
    ]
    assert all(call.cwd == tmp_path / "web" for call in runner.calls)


def test_e2e_install_installs_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build, "find_node_tool", lambda name: name)
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_e2e_install(context) == 0
    assert runner.commands() == [
        ["npm", "install"],
        ["npx", "playwright", "install", "chromium"],
    ]


def test_missing_npm_has_node_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = make_context(tmp_path, FakeRunner())
    monkeypatch.setattr(build, "find_node_tool", lambda name: "")
    with pytest.raises(build.BuildError, match="Node.js"):
        build.cmd_web_install(context)
