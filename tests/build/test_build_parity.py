"""旧 Make 工作流等价映射测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_backend_command_mapping(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    python = str(build.venv_python(tmp_path))
    assert build.cmd_verify(context) == 0
    assert build.cmd_verify_one(context, rule="R1") == 0
    assert build.cmd_contract(context) == 0
    assert build.cmd_test(context) == 0
    assert build.cmd_lint(context) == 0
    assert runner.commands() == [
        [python, "-m", "app.cli", "run"],
        [python, "-m", "app.cli", "run-one", "--rule", "R1"],
        [python, "-m", "app.contract.export"],
        [python, "-m", "pytest"],
        [python, "-m", "ruff", "check", "app", "tests"],
        [python, "-m", "ruff", "format", "--check", "app", "tests"],
    ]


def test_frontend_command_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build, "find_node_tool", lambda name: name)
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_gen_web_api(context) == 0
    assert build.cmd_web_install(context) == 0
    assert build.cmd_web_build(context) == 0
    assert build.cmd_e2e_install(context) == 0
    assert runner.commands() == [
        ["npx", "openapi-typescript", "../docs/api/openapi.yaml", "-o", "src/api/client.ts"],
        ["npm", "install"],
        ["npm", "run", "build"],
        ["npm", "install"],
        ["npx", "playwright", "install", "chromium"],
    ]
