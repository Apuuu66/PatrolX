"""契约与前端客户端命令测试。"""

from __future__ import annotations

from pathlib import Path

from tests.build.conftest import (
    FakeRunner,
    build,  # noqa: E402
    make_context,
)


def test_contract_maps_module(tmp_path: Path) -> None:
    runner = FakeRunner()
    context = make_context(tmp_path, runner)
    assert build.cmd_contract(context) == 0
    assert runner.commands() == [[str(build.venv_python(tmp_path)), "-m", "app.contract.export"]]


def test_gen_web_api_uses_npx(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    context = build.BuildContext(root=tmp_path, runner=runner)
    monkeypatch.setattr(build, "find_node_tool", lambda name: f"/tools/{name}")
    assert build.cmd_gen_web_api(context) == 0
    assert runner.commands() == [
        [
            "/tools/npx",
            "openapi-typescript",
            "../docs/api/openapi.yaml",
            "-o",
            "src/api/client.ts",
        ]
    ]
    assert runner.calls[0].cwd == tmp_path / "web"
